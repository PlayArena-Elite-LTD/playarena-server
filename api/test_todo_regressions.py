"""Regression tests for the result-submission 500, organisation login and
referral accrual issues investigated on 2026-10-21."""
import base64
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import Organisation
from api.test_tournament_updates import _Base
from matches import brackets, leagues
from matches.models import Match, TournamentMatchSubmission
from referrals.models import Referral, ReferralCommissionLedger, Referrer, ReferralWallet
from wallet.models import Wallet

User = get_user_model()

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)


def screenshot():
    return SimpleUploadedFile('shot.png', PNG, content_type='image/png')


class TournamentResultSubmissionTests(_Base):
    """POST /api/player/tournaments/{id}/matches/{match_id}/report/ must not 500."""

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

    def _ready_match(self, fmt):
        players = [self.make_player('p1'), self.make_player('p2')]
        tournament = self.make_tournament(format=fmt, max_players=2)
        for player in players:
            self.assertIn(self.join(player, tournament).status_code, (200, 201))
        tournament.refresh_from_db()
        if fmt == 'LEAGUE':
            leagues.generate_league(tournament, shuffle=False)
        else:
            brackets.generate_bracket(tournament, shuffle=False)
        tournament.status = 'ONGOING'
        tournament.save(update_fields=['status'])
        return tournament, tournament.bracket_matches.exclude(status='BYE').first()

    def _report(self, tournament, match, user_id, body):
        self.client.force_authenticate(User.objects.get(pk=user_id))
        return self.client.post(
            f'/api/player/tournaments/{tournament.id}/matches/{match.id}/report/',
            body, format='multipart',
        )

    def test_knockout_report_with_evidence_saves_file(self):
        with override_settings(MEDIA_ROOT=self.media_root):
            tournament, match = self._ready_match('KNOCKOUT')
            for uid in (match.player1_id, match.player2_id):
                response = self._report(
                    tournament, match, uid,
                    {'winner_id': str(match.player1_id), 'evidence': screenshot()},
                )
                self.assertEqual(response.status_code, 200, response.content)
            match.refresh_from_db()
            self.assertEqual(match.status, 'CONFIRMED')
            self.assertEqual(match.winner_id, match.player1_id)
            self.assertTrue(all(
                s.evidence for s in TournamentMatchSubmission.objects.filter(match=match)
            ))

    def test_league_report_with_evidence(self):
        with override_settings(MEDIA_ROOT=self.media_root):
            tournament, match = self._ready_match('LEAGUE')
            for uid in (match.player1_id, match.player2_id):
                response = self._report(
                    tournament, match, uid,
                    {'player1_score': '2', 'player2_score': '1', 'evidence': screenshot()},
                )
                self.assertEqual(response.status_code, 200, response.content)
            match.refresh_from_db()
            self.assertEqual(match.status, 'CONFIRMED')


class OrganisationLoginTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            'orgowner', 'owner+personal@example.com', 'Sup3rSecret!',
        )
        self.organisation = Organisation.objects.create(
            owner=self.owner, name='PLAYARENA ELITE LIMITED', contact_name='Owner',
            email='hello@playarena.example', phone='+260970000000',
            organisation_type=Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            city='Lusaka',
        )

    def _login(self, email, password='Sup3rSecret!'):
        return self.client.post(
            '/api/auth/organisations/login/', {'email': email, 'password': password}, format='json',
        )

    def test_login_with_organisation_email_when_owner_email_differs(self):
        response = self._login('Hello@PlayArena.example')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['organisation']['id'], self.organisation.id)

    def test_login_with_owner_account_email_still_works(self):
        self.assertEqual(self._login('owner+personal@example.com').status_code, 200)

    def test_wrong_password_is_rejected(self):
        self.assertEqual(self._login('hello@playarena.example', 'nope').status_code, 400)

    def test_ambiguous_identifier_does_not_500(self):
        # Another user's *username* equals the owner's email.
        User.objects.create_user('owner+personal@example.com', 'other@example.com', 'x-Other-123')
        self.assertEqual(self._login('owner+personal@example.com').status_code, 200)


class ReferralAccrualViaApiTests(APITestCase):
    def test_commission_accumulates_for_every_settled_match(self):
        referrer_user = User.objects.create_user('bless', 'bless@example.com', 'pass1234')
        Referrer.objects.create(user=referrer_user, referral_code='BLESS', status='APPROVED')
        response = self.client.post('/api/auth/register/', {
            'username': 'referred', 'email': 'referred@example.com',
            'password': 'Str0ngPass!x', 'password_confirm': 'Str0ngPass!x',
            'referral_code': 'BLESS',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        referred = User.objects.get(username='referred')
        self.assertTrue(Referral.objects.filter(referred_user=referred).exists())

        opponent = User.objects.create_user('opp', 'opp@example.com', 'pass1234')
        for user in (referred, opponent):
            wallet, _ = Wallet.objects.get_or_create(user=user)
            wallet.balance = 1000
            wallet.save()

        for mine, theirs in (('WON', 'LOST'), ('LOST', 'WON'), ('DRAW', 'DRAW')):
            match = Match.objects.create(
                creator=referred, joiner=opponent, game='FIFA_MOBILE', device='MOBILE',
                privacy='PUBLIC', amount=50, status='JOINED',
            )
            for user, submission in ((referred, mine), (opponent, theirs)):
                self.client.force_authenticate(user)
                r = self.client.post(
                    f'/api/matches/{match.id}/submit-result/', {'submission': submission}, format='json',
                )
                self.assertEqual(r.status_code, 200, r.content)

        entries = ReferralCommissionLedger.objects.filter(referrer__user=referrer_user)
        self.assertEqual(entries.count(), 3)
        wallet = ReferralWallet.objects.get(user=referrer_user)
        self.assertEqual(str(wallet.balance), '4.50')  # 3 x (50 * 10% * 30%)
        self.assertTrue(wallet.verify_balance_integrity()['is_valid'])

"""Tests for the PlayArena tournament + wallet feature updates.

Covers: registration-deadline extension, standardized player metadata
(team name + phone), configurable PlayArena %, home-and-away leagues,
manual fixture/result management, the withdrawal history endpoint and the
'never withdraw more than balance' rule, and the payout percentage field.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from accounts.models import Organisation, OrganisationMembership
from matches.models import (
    Tournament, TournamentFeeSettlement, TournamentRegistration, TournamentPrize,
    TournamentMatch, TournamentStanding, TournamentPayout,
)
from wallet.models import Wallet, Transaction, Withdrawal

User = get_user_model()


class _Base(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user('owner', 'owner@t.com', 'pass1234')
        self.organisation = Organisation.objects.create(
            owner=self.owner, name='Lusaka Hub', contact_name='M B',
            email='hub@t.com', phone='+260971234567',
            organisation_type=Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            city='Lusaka',
        )

    def make_player(self, username, balance='500.00', approve=True):
        u = User.objects.create_user(username, f'{username}@t.com', 'pass1234')
        if approve:
            OrganisationMembership.objects.create(
                organisation=self.organisation, player=u,
                status=OrganisationMembership.Status.APPROVED,
            )
        w, _ = Wallet.objects.get_or_create(user=u)
        w.balance = Decimal(balance)
        w.save()
        # Return a fresh instance so the reverse wallet relation isn't cached
        # with a stale balance (mirrors production, where request.user is loaded
        # per request).
        return User.objects.get(pk=u.pk)

    def make_tournament(self, **kw):
        defaults = dict(
            organisation=self.organisation, name='T', game='FIFA_MOBILE',
            participation_amount=Decimal('20.00'), max_players=16, status='OPEN',
        )
        defaults.update(kw)
        return Tournament.objects.create(**defaults)

    def join(self, player, tournament, team='Power Dynamos', phone='0974930662'):
        self.client.force_authenticate(player)
        body = {}
        if team is not None:
            body['team_name'] = team
        if phone is not None:
            body['phone'] = phone
        return self.client.post(f'/api/player/tournaments/{tournament.id}/join/', body, format='json')


class ExtendRegistrationTests(_Base):
    def test_extend_reopens_closed_registration_and_keeps_players(self):
        past = timezone.now() - timedelta(days=1)
        t = self.make_tournament(registration_closes_at=past)
        # Deadline is in the past -> display status is closed, joining blocked.
        p = self.make_player('p1')
        blocked = self.join(p, t)
        self.assertEqual(blocked.status_code, 400)

        # Owner extends the deadline.
        self.client.force_authenticate(self.owner)
        future = (timezone.now() + timedelta(days=3)).isoformat()
        res = self.client.post(
            f'/api/organisations/tournaments/{t.id}/extend-registration/',
            {'registration_closes_at': future}, format='json',
        )
        self.assertEqual(res.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.status, 'OPEN')
        self.assertGreater(t.registration_closes_at, timezone.now())
        # Now joining works again.
        ok = self.join(p, t)
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_extend_rejects_past_deadline(self):
        t = self.make_tournament()
        self.client.force_authenticate(self.owner)
        past = (timezone.now() - timedelta(days=1)).isoformat()
        res = self.client.post(
            f'/api/organisations/tournaments/{t.id}/extend-registration/',
            {'registration_closes_at': past}, format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_only_owner_can_extend(self):
        t = self.make_tournament()
        stranger = User.objects.create_user('str', 'str@t.com', 'pass1234')
        self.client.force_authenticate(stranger)
        res = self.client.post(
            f'/api/organisations/tournaments/{t.id}/extend-registration/',
            {'registration_closes_at': (timezone.now() + timedelta(days=1)).isoformat()},
            format='json',
        )
        self.assertIn(res.status_code, (403, 404))


class PlayerMetadataTests(_Base):
    def test_join_captures_team_and_normalises_phone(self):
        t = self.make_tournament()
        p = self.make_player('lewis')
        res = self.join(p, t, team='Power Dynamos', phone='0974930662')
        self.assertEqual(res.status_code, 200, res.data)
        reg = TournamentRegistration.objects.get(tournament=t, player=p)
        self.assertEqual(reg.team_name, 'Power Dynamos')
        self.assertEqual(reg.phone, '+260974930662')

    def test_team_and_phone_are_required(self):
        t = self.make_tournament()
        p = self.make_player('noteam')
        self.assertEqual(self.join(p, t, team='', phone='0974930662').status_code, 400)
        p2 = self.make_player('nophone')
        self.assertEqual(self.join(p2, t, team='X', phone='').status_code, 400)

    def test_participant_list_shows_username_and_team_label(self):
        t = self.make_tournament()
        p = self.make_player('lewis')
        self.join(p, t, team='Power Dynamos')
        self.client.force_authenticate(self.owner)
        res = self.client.get(f'/api/organisations/tournaments/{t.id}/registrations/')
        self.assertEqual(res.status_code, 200)
        row = res.data[0]
        self.assertEqual(row['team_name'], 'Power Dynamos')
        self.assertEqual(row['player_label'], 'lewis (Power Dynamos)')
        self.assertEqual(row['phone'], '+260974930662')


class ConfigurableFeeTests(_Base):
    def test_fee_is_not_allocated_until_all_slots_are_filled(self):
        t = self.make_tournament(participation_amount=Decimal('20.00'))
        p = self.make_player('a')
        self.join(p, t)
        reg = TournamentRegistration.objects.get(tournament=t, player=p)
        self.assertEqual(reg.platform_fee, Decimal('0.00'))
        self.assertEqual(reg.prize_contribution, Decimal('20.00'))
        self.assertFalse(TournamentFeeSettlement.objects.filter(tournament=t).exists())
        t.refresh_from_db()
        self.assertEqual(t.status, 'OPEN')

    def test_full_tournament_allocates_ten_percent_once_to_pool(self):
        t = self.make_tournament(
            participation_amount=Decimal('10.00'),
            max_players=2,
        )
        first = self.make_player('fee_a')
        second = self.make_player('fee_b')

        self.assertEqual(self.join(first, t).status_code, 200)
        self.assertFalse(TournamentFeeSettlement.objects.filter(tournament=t).exists())
        response = self.join(second, t)
        self.assertEqual(response.status_code, 200, response.data)

        t.refresh_from_db()
        settlement = TournamentFeeSettlement.objects.get(tournament=t)
        self.assertEqual(t.status, 'READY_TO_START')
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.RESERVED)
        self.assertEqual(settlement.gross_pool, Decimal('20.00'))
        self.assertEqual(settlement.platform_fee, Decimal('2.00'))
        self.assertEqual(settlement.net_prize_pool, Decimal('18.00'))
        self.assertEqual(t.platform_fee_total, Decimal('2.00'))
        self.assertEqual(t.prize_pool, Decimal('18.00'))
        self.assertEqual(
            TournamentRegistration.objects.filter(
                tournament=t,
                status=TournamentRegistration.Status.REGISTERED,
            ).aggregate(total=Sum('platform_fee'))['total'],
            Decimal('2.00'),
        )

    def test_custom_platform_fee_is_rejected(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post('/api/organisations/tournaments/', {
            'name': 'Configured', 'game': 'FIFA_MOBILE',
            'participation_amount': '50.00', 'max_players': 8,
            'platform_fee_percent': '15',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_tournament_fee_percent_is_mandatory_ten_percent(self):
        self.client.force_authenticate(self.owner)
        res = self.client.post('/api/organisations/tournaments/', {
            'name': 'Configured', 'game': 'FIFA_MOBILE',
            'participation_amount': '50.00', 'max_players': 8,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        t = Tournament.objects.get(id=res.data['id'])
        self.assertEqual(t.platform_fee_percent, Decimal('10.00'))

    def test_cancelling_before_launch_refunds_full_entries_and_voids_fee(self):
        t = self.make_tournament(
            participation_amount=Decimal('10.00'),
            max_players=2,
        )
        players = [self.make_player('cancel_a'), self.make_player('cancel_b')]
        for player in players:
            self.assertEqual(self.join(player, t).status_code, 200)

        t.refresh_from_db()
        settlement = TournamentFeeSettlement.objects.get(tournament=t)
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.RESERVED)
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f'/api/organisations/tournaments/{t.id}/lifecycle/',
            {'action': 'cancel'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        settlement.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(t.status, 'CANCELLED')
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.REFUNDED)
        self.assertEqual(settlement.platform_fee, Decimal('2.00'))
        for player in players:
            wallet = Wallet.objects.get(user=player)
            self.assertEqual(wallet.balance, Decimal('500.00'))
            self.assertTrue(wallet.transactions.filter(
                transaction_type='TOURNAMENT_REFUND', amount=Decimal('10.00')
            ).exists())

    def test_tournament_cannot_start_until_full_and_fee_is_recognized_on_start(self):
        t = self.make_tournament(
            participation_amount=Decimal('10.00'),
            max_players=2,
        )
        first = self.make_player('start_a')
        second = self.make_player('start_b')
        self.assertEqual(self.join(first, t).status_code, 200)

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f'/api/organisations/tournaments/{t.id}/bracket/'
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TournamentFeeSettlement.objects.filter(tournament=t).exists())

        self.assertEqual(self.join(second, t).status_code, 200)
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f'/api/organisations/tournaments/{t.id}/bracket/'
        )
        self.assertEqual(response.status_code, 201, response.data)
        settlement = TournamentFeeSettlement.objects.get(tournament=t)
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.RECOGNIZED)
        self.assertIsNotNone(settlement.recognized_at)


class HomeAndAwayLeagueTests(_Base):
    def _league(self, n, home_and_away):
        t = self.make_tournament(format='LEAGUE', home_and_away=home_and_away,
                                 max_players=n)
        for i in range(n):
            self.join(self.make_player(f'pl{i}'), t)
        self.client.force_authenticate(self.owner)
        res = self.client.post(f'/api/organisations/tournaments/{t.id}/bracket/')
        self.assertEqual(res.status_code, 201, res.data)
        return t

    def test_single_round_robin_counts(self):
        n = 4
        t = self._league(n, home_and_away=False)
        matches = TournamentMatch.objects.filter(tournament=t)
        self.assertEqual(matches.count(), n * (n - 1) // 2)  # 6

    def test_home_and_away_doubles_fixtures(self):
        n = 4
        t = self._league(n, home_and_away=True)
        matches = list(TournamentMatch.objects.filter(tournament=t))
        self.assertEqual(len(matches), n * (n - 1))  # 12
        # every player plays 2*(n-1) fixtures
        from collections import Counter
        plays = Counter()
        for m in matches:
            plays[m.player1_id] += 1
            plays[m.player2_id] += 1
        self.assertTrue(all(v == 2 * (n - 1) for v in plays.values()))


class ManualFixtureTests(_Base):
    def test_manual_fixture_records_result_and_updates_league(self):
        t = self.make_tournament(format='LEAGUE', home_and_away=False)
        p1 = self.make_player('home')
        p2 = self.make_player('away')
        self.join(p1, t, team='Power Dynamos')
        self.join(p2, t, team='Jasam Starz FC')
        self.client.force_authenticate(self.owner)
        res = self.client.post(f'/api/organisations/tournaments/{t.id}/matches/', {
            'player1_id': p1.id, 'player2_id': p2.id,
            'player1_score': 2, 'player2_score': 1,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        m = TournamentMatch.objects.get(id=res.data['match']['id'])
        self.assertEqual(m.status, TournamentMatch.Status.CONFIRMED)
        self.assertEqual(m.winner_id, p1.id)
        # league standings rebuilt: winner ranked 1st
        top = TournamentStanding.objects.get(tournament=t, position=1)
        self.assertEqual(top.player_id, p1.id)

    def test_manual_fixture_rejects_unregistered_or_duplicate(self):
        t = self.make_tournament(format='LEAGUE')
        p1 = self.make_player('h')
        self.join(p1, t)
        outsider = self.make_player('out', approve=True)  # registered? no, not joined
        self.client.force_authenticate(self.owner)
        # unregistered player2
        r1 = self.client.post(f'/api/organisations/tournaments/{t.id}/matches/', {
            'player1_id': p1.id, 'player2_id': outsider.id,
        }, format='json')
        self.assertEqual(r1.status_code, 400)
        # duplicate players
        r2 = self.client.post(f'/api/organisations/tournaments/{t.id}/matches/', {
            'player1_id': p1.id, 'player2_id': p1.id,
        }, format='json')
        self.assertEqual(r2.status_code, 400)


class WithdrawalTests(_Base):
    def test_cannot_withdraw_more_than_balance(self):
        u = self.make_player('rich', balance='50.00')
        self.client.force_authenticate(u)
        res = self.client.post('/api/wallet/withdraw/', {
            'amount': '100.00', 'payment_method': 'BANK_TRANSFER',
            'account_details': 'Bank X 123456',
        }, format='json')
        self.assertEqual(res.status_code, 400, res.data)
        # balance untouched
        u.wallet.refresh_from_db()
        self.assertEqual(u.wallet.balance, Decimal('50.00'))

    def test_withdrawal_debits_and_lists_with_status(self):
        u = self.make_player('w', balance='100.00')
        self.client.force_authenticate(u)
        res = self.client.post('/api/wallet/withdraw/', {
            'amount': '30.00', 'payment_method': 'BANK_TRANSFER',
            'account_details': 'Bank X 998877',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        u.wallet.refresh_from_db()
        self.assertEqual(u.wallet.balance, Decimal('70.00'))  # debited at request
        lst = self.client.get('/api/wallet/withdrawals/')
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(len(lst.data), 1)
        row = lst.data[0]
        self.assertEqual(Decimal(row['amount']), Decimal('30.00'))
        self.assertEqual(row['status'], 'PENDING')
        self.assertIn('7', row['account_details_masked'])  # last-4 masking


class PayoutTests(_Base):
    def test_lock_pays_out_and_records_percentage(self):
        t = self.make_tournament(format='LEAGUE', home_and_away=False,
                                 participation_amount=Decimal('100.00'), max_players=2)
        TournamentPrize.objects.create(tournament=t, position=1, percentage=Decimal('70'))
        p1 = self.make_player('champ', balance='500')
        p2 = self.make_player('runner', balance='500')
        self.join(p1, t)
        self.join(p2, t)
        self.client.force_authenticate(self.owner)
        # generate + confirm the single fixture
        self.client.post(f'/api/organisations/tournaments/{t.id}/bracket/')
        m = TournamentMatch.objects.filter(tournament=t).first()
        self.client.post(
            f'/api/organisations/tournaments/{t.id}/matches/{m.id}/confirm/',
            {'player1_score': 3, 'player2_score': 0}, format='json',
        )
        # lock -> payouts
        lock = self.client.post(f'/api/organisations/tournaments/{t.id}/lock/')
        self.assertEqual(lock.status_code, 200, lock.data)
        payouts = self.client.get(f'/api/organisations/tournaments/{t.id}/payouts/')
        self.assertEqual(payouts.status_code, 200)
        self.assertTrue(len(payouts.data) >= 1)
        first = payouts.data[0]
        self.assertEqual(first['percentage'], '70.00')
        self.assertEqual(first['status'], 'PAID')
        # pool = 2 * (100 - 10% fee) = 180; 70% = 126
        self.assertEqual(Decimal(first['amount']), Decimal('126.00'))

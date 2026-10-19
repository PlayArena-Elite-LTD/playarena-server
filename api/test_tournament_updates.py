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
from api.views import _process_tournament_payout
from matches.models import (
    Tournament, TournamentFeeSettlement, TournamentRegistration, TournamentPrize,
    TournamentMatch, TournamentStanding, TournamentPayout,
)
from matches.tournament_fees import recognize_tournament_fee
from wallet.models import (
    OrganisationTransaction,
    OrganisationWallet,
    PlatformTransaction,
    PlatformWallet,
    Wallet,
    Transaction,
    Withdrawal,
)

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


class TournamentFeeSettlementTests(_Base):
    def test_fee_is_not_allocated_until_all_slots_are_filled(self):
        t = self.make_tournament(participation_amount=Decimal('20.00'))
        p = self.make_player('a')
        self.join(p, t)
        reg = TournamentRegistration.objects.get(tournament=t, player=p)
        self.assertEqual(reg.platform_fee, Decimal('0.00'))
        self.assertEqual(reg.organiser_fee, Decimal('0.00'))
        self.assertEqual(reg.prize_contribution, Decimal('20.00'))
        self.assertFalse(TournamentFeeSettlement.objects.filter(tournament=t).exists())
        t.refresh_from_db()
        self.assertEqual(t.status, 'OPEN')

    def test_full_tournament_allocates_configured_fee_once_to_pool(self):
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
        entry_breakdown = response.data['tournament']['entry_breakdown']
        self.assertEqual(entry_breakdown['platform_fee'], '1.00')
        self.assertEqual(entry_breakdown['organiser_fee'], '0.90')
        self.assertEqual(entry_breakdown['prize_contribution'], '9.00')

        t.refresh_from_db()
        settlement = TournamentFeeSettlement.objects.get(tournament=t)
        self.assertEqual(t.status, 'READY_TO_START')
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.RESERVED)
        self.assertEqual(settlement.gross_pool, Decimal('20.00'))
        self.assertEqual(settlement.platform_fee, Decimal('2.00'))
        self.assertEqual(settlement.organiser_fee, Decimal('1.80'))
        self.assertEqual(settlement.net_prize_pool, Decimal('18.00'))
        self.assertEqual(t.platform_fee_total, Decimal('2.00'))
        self.assertEqual(t.organiser_fee_total, Decimal('1.80'))
        self.assertEqual(t.prize_pool, Decimal('18.00'))
        self.assertEqual(
            TournamentRegistration.objects.filter(
                tournament=t,
                status=TournamentRegistration.Status.REGISTERED,
            ).aggregate(total=Sum('platform_fee'))['total'],
            Decimal('2.00'),
        )
        self.assertEqual(
            TournamentRegistration.objects.filter(
                tournament=t,
                status=TournamentRegistration.Status.REGISTERED,
            ).aggregate(total=Sum('organiser_fee'))['total'],
            Decimal('0.00'),
        )
        self.assertFalse(PlatformWallet.objects.exists())
        self.assertFalse(OrganisationTransaction.objects.filter(
            transaction_type='TOURNAMENT_EARNINGS'
        ).exists())

    def test_create_persists_configured_organiser_fee_percent_and_fixed_platform_fee(self):
        self.client.force_authenticate(self.owner)
        for index, fee_percent in enumerate(('0', '5', '7.5', '10')):
            response = self.client.post('/api/organisations/tournaments/', {
                'name': f'Configured {index}',
                'game': 'FIFA_MOBILE',
                'participation_amount': '50.00',
                'max_players': 8,
                'platform_fee_percent': '10.00',
                'organiser_fee_percent': fee_percent,
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            tournament = Tournament.objects.get(id=response.data['id'])
            self.assertEqual(tournament.platform_fee_percent, Decimal('10.00'))
            self.assertEqual(tournament.organiser_fee_percent, Decimal(fee_percent))
            self.assertEqual(Decimal(response.data['platform_fee_percent']), Decimal('10.00'))
            self.assertEqual(Decimal(response.data['organiser_fee_percent']), Decimal(fee_percent))

    def test_create_defaults_platform_and_organiser_fees_to_ten_percent(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post('/api/organisations/tournaments/', {
            'name': 'Default fee', 'game': 'FIFA_MOBILE',
            'participation_amount': '50.00', 'max_players': 8,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        tournament = Tournament.objects.get(id=response.data['id'])
        self.assertEqual(tournament.platform_fee_percent, Decimal('10.00'))
        self.assertEqual(tournament.organiser_fee_percent, Decimal('10.00'))

    def test_create_rejects_invalid_organiser_fee_values(self):
        self.client.force_authenticate(self.owner)
        invalid_rates = ('-1', '10.01', '11', '1.001', 'NaN', 'Infinity', 'not-a-number', None)
        for index, fee_percent in enumerate(invalid_rates):
            with self.subTest(fee_percent=fee_percent):
                response = self.client.post('/api/organisations/tournaments/', {
                    'name': f'Invalid fee {index}',
                    'game': 'FIFA_MOBILE',
                    'participation_amount': '50.00',
                    'max_players': 8,
                    'organiser_fee_percent': fee_percent,
                }, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('organiser_fee_percent', response.data)

    def test_create_rejects_platform_fee_overrides(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post('/api/organisations/tournaments/', {
            'name': 'Invalid platform fee',
            'game': 'FIFA_MOBILE',
            'participation_amount': '50.00',
            'max_players': 8,
            'platform_fee_percent': '9.99',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('platform_fee_percent', response.data)

    def test_fixed_platform_and_configured_organiser_fees_are_used_for_settlement(self):
        organiser_rates = (Decimal('0.00'), Decimal('5.00'), Decimal('7.50'), Decimal('10.00'))
        for index, organiser_rate in enumerate(organiser_rates):
            with self.subTest(organiser_fee_percent=organiser_rate):
                tournament = self.make_tournament(
                    name=f'Fee {index}',
                    participation_amount=Decimal('50.00'),
                    max_players=2,
                    organiser_fee_percent=organiser_rate,
                )
                first = self.make_player(f'configured_{index}_a')
                second = self.make_player(f'configured_{index}_b')
                self.assertEqual(self.join(first, tournament).status_code, 200)
                self.assertEqual(self.join(second, tournament).status_code, 200)

                tournament.refresh_from_db()
                settlement = TournamentFeeSettlement.objects.get(tournament=tournament)
                self.assertEqual(settlement.gross_pool, Decimal('100.00'))
                self.assertEqual(settlement.fee_percent, Decimal('10.00'))
                self.assertEqual(settlement.platform_fee, Decimal('10.00'))
                self.assertEqual(settlement.organiser_fee_percent, organiser_rate)
                organiser_fee = (Decimal('90.00') * organiser_rate / Decimal('100')).quantize(
                    Decimal('0.01')
                )
                self.assertEqual(settlement.organiser_fee, organiser_fee)
                self.assertEqual(settlement.net_prize_pool, Decimal('90.00'))
                self.assertEqual(tournament.platform_fee_percent, Decimal('10.00'))
                self.assertEqual(tournament.split_entry(Decimal('100.00')), (
                    Decimal('10.00'), organiser_fee, Decimal('90.00')
                ))

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
        self.assertEqual(settlement.organiser_fee, Decimal('1.80'))
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
        self.assertEqual(settlement.organiser_fee, Decimal('1.80'))
        self.assertFalse(OrganisationTransaction.objects.filter(
            transaction_type='TOURNAMENT_EARNINGS'
        ).exists())
        self.assertEqual(self.organisation.wallet.balance, Decimal('0.00'))
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
        platform_wallet = PlatformWallet.objects.get(pk=1)
        self.assertEqual(platform_wallet.balance, Decimal('2.00'))
        organisation_wallet = OrganisationWallet.objects.get(
            organisation=self.organisation
        )
        self.assertEqual(organisation_wallet.balance, Decimal('0.00'))
        self.assertFalse(OrganisationTransaction.objects.filter(
            transaction_type='TOURNAMENT_EARNINGS'
        ).exists())
        self.assertEqual(
            PlatformTransaction.objects.get(fee_settlement=settlement).amount,
            Decimal('2.00'),
        )
        recognize_tournament_fee(t)

        platform_wallet.refresh_from_db()
        organisation_wallet.refresh_from_db()
        self.assertEqual(platform_wallet.balance, Decimal('2.00'))
        self.assertEqual(organisation_wallet.balance, Decimal('0.00'))
        self.assertEqual(
            PlatformTransaction.objects.filter(fee_settlement=settlement).count(),
            1,
        )
        self.assertEqual(
            OrganisationTransaction.objects.filter(
                transaction_type='TOURNAMENT_EARNINGS'
            ).count(),
            0,
        )
        wallet_transactions = self.client.get(
            '/api/organisations/wallet/transactions/'
        )
        self.assertEqual(wallet_transactions.status_code, 200)
        self.assertEqual(wallet_transactions.data, [])

    def test_zero_organiser_rate_does_not_credit_organisation_wallet(self):
        tournament = self.make_tournament(
            participation_amount=Decimal('10.00'),
            max_players=2,
            organiser_fee_percent=Decimal('0.00'),
        )
        for username in ('zero_fee_a', 'zero_fee_b'):
            self.assertEqual(
                self.join(self.make_player(username), tournament).status_code,
                200,
            )

        self.client.force_authenticate(self.owner)
        response = self.client.post(f'/api/organisations/tournaments/{tournament.id}/bracket/')

        self.assertEqual(response.status_code, 201, response.data)
        settlement = TournamentFeeSettlement.objects.get(tournament=tournament)
        self.assertEqual(settlement.status, TournamentFeeSettlement.Status.RECOGNIZED)
        self.assertEqual(settlement.platform_fee, Decimal('2.00'))
        self.assertEqual(settlement.organiser_fee, Decimal('0.00'))
        self.assertEqual(PlatformWallet.objects.get(pk=1).balance, Decimal('2.00'))
        self.assertEqual(
            OrganisationWallet.objects.get(organisation=self.organisation).balance,
            Decimal('0.00'),
        )
        self.assertFalse(OrganisationTransaction.objects.filter(
            transaction_type='TOURNAMENT_EARNINGS'
        ).exists())


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
        TournamentPrize.objects.create(tournament=t, position=2, percentage=Decimal('30'))
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
        self.assertEqual(len(payouts.data), 2)
        first = payouts.data[0]
        self.assertEqual(first['percentage'], '70.00')
        self.assertEqual(first['status'], 'PAID')
        second = payouts.data[1]
        self.assertEqual(second['percentage'], '30.00')
        self.assertEqual(second['status'], 'PAID')
        # Pool after platform fee = 180; the 18 organiser fee is split
        # proportionally across the 70% and 30% scheduled prizes.
        self.assertEqual(Decimal(first['gross_amount']), Decimal('126.00'))
        self.assertEqual(Decimal(first['organiser_fee']), Decimal('12.60'))
        self.assertEqual(Decimal(first['amount']), Decimal('113.40'))
        self.assertEqual(Decimal(second['gross_amount']), Decimal('54.00'))
        self.assertEqual(Decimal(second['organiser_fee']), Decimal('5.40'))
        self.assertEqual(Decimal(second['amount']), Decimal('48.60'))
        self.organisation.refresh_from_db()
        self.organisation.wallet.refresh_from_db()
        self.assertEqual(self.organisation.wallet.balance, Decimal('18.00'))
        fee_transactions = OrganisationTransaction.objects.filter(
            transaction_type='TOURNAMENT_EARNINGS'
        )
        self.assertEqual(fee_transactions.count(), 2)
        self.assertEqual(
            sum(fee_transactions.values_list('amount', flat=True), Decimal('0.00')),
            Decimal('18.00'),
        )
        self.assertSetEqual(
            set(fee_transactions.values_list('tournament_payout_id', flat=True)),
            {first['id'], second['id']},
        )
        history = self.client.get('/api/organisations/wallet/transactions/')
        self.assertEqual(history.status_code, 200, history.data)
        self.assertEqual(len(history.data), 2)
        self.assertEqual(
            {Decimal(row['amount']) for row in history.data},
            {Decimal('12.60'), Decimal('5.40')},
        )
        self.assertTrue(all(row['related_tournament'] == t.id for row in history.data))
        for payout in (first, second):
            winner = next(player for player in (p1, p2) if player.id == payout['player_id'])
            self.assertEqual(
                TournamentRegistration.objects.get(tournament=t, player=winner).organiser_fee,
                Decimal(payout['organiser_fee']),
            )
            _process_tournament_payout(TournamentPayout.objects.get(pk=payout['id']))
        self.assertEqual(
            OrganisationTransaction.objects.filter(
                transaction_type='TOURNAMENT_EARNINGS'
            ).count(),
            2,
        )
        for player in (p1, p2):
            player.wallet.refresh_from_db()
        self.assertEqual(
            p1.wallet.balance + p2.wallet.balance,
            Decimal('962.00'),
        )

    def test_lock_rejects_prize_payouts_that_cannot_cover_organiser_earnings(self):
        t = self.make_tournament(
            format='LEAGUE',
            home_and_away=False,
            participation_amount=Decimal('100.00'),
            max_players=2,
        )
        TournamentPrize.objects.create(tournament=t, position=1, percentage=Decimal('5'))
        p1 = self.make_player('small_champ', balance='500')
        p2 = self.make_player('small_runner', balance='500')
        self.join(p1, t)
        self.join(p2, t)
        self.client.force_authenticate(self.owner)
        self.client.post(f'/api/organisations/tournaments/{t.id}/bracket/')
        match = TournamentMatch.objects.filter(tournament=t).first()
        self.client.post(
            f'/api/organisations/tournaments/{t.id}/matches/{match.id}/confirm/',
            {'player1_score': 3, 'player2_score': 0},
            format='json',
        )

        response = self.client.post(f'/api/organisations/tournaments/{t.id}/lock/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('too small to cover organiser earnings', response.data['detail'])
        self.assertFalse(TournamentPayout.objects.filter(tournament=t).exists())
        self.assertEqual(self.organisation.wallet.balance, Decimal('0.00'))

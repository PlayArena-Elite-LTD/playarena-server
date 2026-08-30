"""7-day league engine: single round-robin fixtures + football 3/1/0 table.

Reuses ``TournamentMatch`` (round_number = matchday) so the tournament has one
match model across formats. Players submit scorelines; organisers confirm. The
league table (P/W/D/L/GF/GA/GD/Pts) is computed live and, on confirmation,
written into ``TournamentStanding`` as final positions that feed the existing
lock → payout flow.
"""

from django.db import transaction

from .models import TournamentMatch, TournamentRegistration, TournamentStanding

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0


def registered_player_ids(tournament):
    return list(
        TournamentRegistration.objects.filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        ).values_list('player_id', flat=True)
    )


def _round_robin_rounds(player_ids, double=False):
    """Round-robin schedule via the circle method.

    Returns a list of matchdays; each matchday is a list of (home, away) pairs.
    An odd field gets a ``None`` placeholder — the player paired with it rests.
    When ``double`` is true a second (home-and-away) half is appended with venues
    reversed, so every pair meets twice — once at home, once away. A 10-player
    league then runs 18 matchdays and each player plays 18 fixtures.
    """
    players = list(player_ids)
    if len(players) % 2:
        players.append(None)
    n = len(players)
    half = n // 2
    fixed = players[0]
    rotating = players[1:]
    rounds = []
    for _ in range(n - 1):
        ordered = [fixed] + rotating
        pairs = []
        for i in range(half):
            home = ordered[i]
            away = ordered[n - 1 - i]
            if home is not None and away is not None:
                pairs.append((home, away))
        rounds.append(pairs)
        rotating = [rotating[-1]] + rotating[:-1]
    if double:
        reversed_half = [[(away, home) for (home, away) in rnd] for rnd in rounds]
        rounds = rounds + reversed_half
    return rounds


@transaction.atomic
def generate_league(tournament, shuffle=True, seed=None):
    """Create single round-robin fixtures for a tournament."""
    if tournament.bracket_matches.exists():
        raise ValueError("Fixtures already exist for this tournament.")

    players = registered_player_ids(tournament)
    if len(players) < 2:
        raise ValueError("At least 2 registered players are required to generate fixtures.")

    if shuffle:
        import random
        random.Random(seed).shuffle(players)

    double = bool(getattr(tournament, 'home_and_away', False))
    rounds = _round_robin_rounds(players, double=double)
    for matchday, pairs in enumerate(rounds, start=1):
        for slot, (home, away) in enumerate(pairs):
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=matchday,
                slot_number=slot,
                player1_id=home,
                player2_id=away,
                status=TournamentMatch.Status.READY,
            )

    return list(tournament.bracket_matches.all().order_by('round_number', 'slot_number'))


def _winner_from_scores(match, s1, s2):
    if s1 > s2:
        return match.player1_id
    if s2 > s1:
        return match.player2_id
    return None  # draw


def report_score(match, reporter_id, s1, s2):
    """A participant reports a scoreline; awaits organiser confirmation."""
    if match.status not in (TournamentMatch.Status.READY, TournamentMatch.Status.REPORTED):
        raise ValueError("This fixture is not awaiting a result.")
    if reporter_id not in (match.player1_id, match.player2_id):
        raise ValueError("Only a participant of this fixture can report its result.")
    s1, s2 = _validate_scores(s1, s2)
    match.player1_score = s1
    match.player2_score = s2
    match.reported_by_id = reporter_id
    match.reported_winner_id = _winner_from_scores(match, s1, s2)
    match.status = TournamentMatch.Status.REPORTED
    match.save(update_fields=[
        'player1_score', 'player2_score', 'reported_by', 'reported_winner', 'status',
    ])
    return match


def _validate_scores(s1, s2):
    try:
        s1 = int(s1)
        s2 = int(s2)
    except (TypeError, ValueError):
        raise ValueError("Scores must be whole numbers.")
    if s1 < 0 or s2 < 0:
        raise ValueError("Scores cannot be negative.")
    return s1, s2


@transaction.atomic
def confirm_score(tournament, match, s1=None, s2=None):
    """Organiser confirms (or corrects) a fixture result and updates standings."""
    if match.status == TournamentMatch.Status.CONFIRMED:
        raise ValueError("This fixture result is already final.")
    if not (match.player1_id and match.player2_id):
        raise ValueError("Both players must be present to confirm a result.")

    if s1 is None or s2 is None:
        if match.player1_score is None or match.player2_score is None:
            raise ValueError("No scoreline to confirm — provide scores or wait for a report.")
        s1, s2 = match.player1_score, match.player2_score
    s1, s2 = _validate_scores(s1, s2)

    match.player1_score = s1
    match.player2_score = s2
    match.winner_id = _winner_from_scores(match, s1, s2)
    match.reported_winner_id = None
    match.reported_by_id = None
    match.status = TournamentMatch.Status.CONFIRMED
    match.save(update_fields=[
        'player1_score', 'player2_score', 'winner', 'reported_winner', 'reported_by', 'status',
    ])

    rebuild_league_standings(tournament)
    return match


def compute_table(tournament):
    """Compute the live league table, ranked by Pts, then GD, then GF, then id."""
    rows = {pid: {
        'player_id': pid, 'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
        'gf': 0, 'ga': 0, 'gd': 0, 'points': 0,
    } for pid in registered_player_ids(tournament)}

    confirmed = tournament.bracket_matches.filter(
        status=TournamentMatch.Status.CONFIRMED,
    )
    for m in confirmed:
        if m.player1_id not in rows or m.player2_id not in rows:
            continue
        if m.player1_score is None or m.player2_score is None:
            continue
        a, b = rows[m.player1_id], rows[m.player2_id]
        s1, s2 = m.player1_score, m.player2_score
        a['played'] += 1; b['played'] += 1
        a['gf'] += s1; a['ga'] += s2
        b['gf'] += s2; b['ga'] += s1
        if s1 > s2:
            a['won'] += 1; a['points'] += POINTS_WIN
            b['lost'] += 1; b['points'] += POINTS_LOSS
        elif s2 > s1:
            b['won'] += 1; b['points'] += POINTS_WIN
            a['lost'] += 1; a['points'] += POINTS_LOSS
        else:
            a['drawn'] += 1; a['points'] += POINTS_DRAW
            b['drawn'] += 1; b['points'] += POINTS_DRAW

    table = list(rows.values())
    for r in table:
        r['gd'] = r['gf'] - r['ga']
    table.sort(key=lambda r: (-r['points'], -r['gd'], -r['gf'], r['player_id']))
    return table


@transaction.atomic
def rebuild_league_standings(tournament):
    """Write current table positions into TournamentStanding (position + points)."""
    table = compute_table(tournament)
    TournamentStanding.objects.filter(tournament=tournament).delete()
    for position, row in enumerate(table, start=1):
        TournamentStanding.objects.create(
            tournament=tournament,
            player_id=row['player_id'],
            position=position,
            points=row['points'],
        )
    return table

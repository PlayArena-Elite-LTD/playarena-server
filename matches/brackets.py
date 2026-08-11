"""Single-elimination bracket engine for tournaments.

Pure-Python-friendly logic (no view/request coupling) so it can be unit-tested
and reused. Handles bracket generation with byes, player result reporting,
organiser confirmation with winner advancement, and final-standings rebuild.
"""

import math
import random

from django.db import transaction

from .models import (
    TournamentMatch,
    TournamentRegistration,
    TournamentStanding,
)


def _next_power_of_two(n):
    p = 1
    while p < n:
        p *= 2
    return p


def registered_player_ids(tournament):
    return list(
        TournamentRegistration.objects.filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        ).values_list('player_id', flat=True)
    )


@transaction.atomic
def generate_bracket(tournament, shuffle=True, seed=None):
    """Create a single-elimination bracket for a tournament.

    Pads the field to the next power of two; empty slots become byes that
    auto-advance their opponent. Returns the created matches ordered by
    round then slot.
    """
    if tournament.bracket_matches.exists():
        raise ValueError("A bracket already exists for this tournament.")

    players = registered_player_ids(tournament)
    if len(players) < 2:
        raise ValueError("At least 2 registered players are required to generate a bracket.")

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(players)

    size = _next_power_of_two(len(players))
    rounds = int(math.log2(size))

    # Create all matches, round by round.
    grid = []  # grid[r-1] = list of matches in round r
    for r in range(1, rounds + 1):
        count = size // (2 ** r)
        row = [
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=r,
                slot_number=i,
                status=TournamentMatch.Status.PENDING,
            )
            for i in range(count)
        ]
        grid.append(row)

    # Link each match to the parent its winner advances into.
    for r in range(rounds - 1):
        for i, match in enumerate(grid[r]):
            parent = grid[r + 1][i // 2]
            match.next_match = parent
            match.next_slot = 1 if i % 2 == 0 else 2
            match.save(update_fields=['next_match', 'next_slot'])

    # Seat round-1 players: one per match first, then pair up the remainder.
    # Matches left without a second player are byes — this guarantees byes land
    # in distinct matches (never two empty slots in one match).
    first_round = grid[0]
    round1_count = len(first_round)  # == size // 2
    for i, match in enumerate(first_round):
        match.player1_id = players[i] if i < len(players) else None
    for j, player_id in enumerate(players[round1_count:]):
        first_round[j].player2_id = player_id
    for match in first_round:
        if match.player1_id and match.player2_id:
            match.status = TournamentMatch.Status.READY
        match.save(update_fields=['player1', 'player2', 'status'])

    # Resolve byes (exactly one seat filled) — auto-advance.
    for match in first_round:
        if match.player1_id and not match.player2_id:
            _finalise_winner(match, match.player1_id, bye=True)
        elif match.player2_id and not match.player1_id:
            _finalise_winner(match, match.player2_id, bye=True)

    return list(
        tournament.bracket_matches.all().order_by('round_number', 'slot_number')
    )


def _advance_winner(match):
    """Push a confirmed match's winner into its next match slot."""
    if not match.next_match_id:
        return
    parent = match.next_match
    if match.next_slot == 1:
        parent.player1_id = match.winner_id
    else:
        parent.player2_id = match.winner_id
    if parent.player1_id and parent.player2_id and parent.status == TournamentMatch.Status.PENDING:
        parent.status = TournamentMatch.Status.READY
    parent.save(update_fields=['player1', 'player2', 'status'])


def _finalise_winner(match, winner_id, bye=False):
    match.winner_id = winner_id
    match.reported_winner_id = None
    match.reported_by_id = None
    match.status = TournamentMatch.Status.BYE if bye else TournamentMatch.Status.CONFIRMED
    match.save(update_fields=['winner', 'reported_winner', 'reported_by', 'status'])
    _advance_winner(match)


def report_result(match, reporter_id, winner_id):
    """A participant reports a match winner; awaits organiser confirmation."""
    if match.status not in (TournamentMatch.Status.READY, TournamentMatch.Status.REPORTED):
        raise ValueError("This match is not awaiting a result.")
    if not match.has_player(reporter_id):
        raise ValueError("Only a participant of this match can report its result.")
    if winner_id not in (match.player1_id, match.player2_id):
        raise ValueError("The reported winner must be one of the two players.")
    match.reported_winner_id = winner_id
    match.reported_by_id = reporter_id
    match.status = TournamentMatch.Status.REPORTED
    match.save(update_fields=['reported_winner', 'reported_by', 'status'])
    return match


@transaction.atomic
def confirm_result(match, winner_id=None):
    """Organiser confirms (or corrects) a match result and advances the winner.

    If ``winner_id`` is omitted, the player-reported winner is used. Returns
    ``(match, final_confirmed)`` where ``final_confirmed`` is True when this
    completes the final match.
    """
    if match.status in (TournamentMatch.Status.CONFIRMED, TournamentMatch.Status.BYE):
        raise ValueError("This match result is already final.")
    if not (match.player1_id and match.player2_id):
        raise ValueError("Both players must be present before confirming a result.")

    resolved = winner_id or match.reported_winner_id
    if not resolved:
        raise ValueError("No winner to confirm — provide a winner or wait for a report.")
    if resolved not in (match.player1_id, match.player2_id):
        raise ValueError("The winner must be one of the two players.")

    _finalise_winner(match, resolved, bye=False)

    is_final = match.next_match_id is None
    if is_final:
        rebuild_standings_from_bracket(match.tournament)
    return match, is_final


def _loser_id(match):
    if not match.winner_id:
        return None
    if match.winner_id == match.player1_id:
        return match.player2_id
    if match.winner_id == match.player2_id:
        return match.player1_id
    return None


@transaction.atomic
def rebuild_standings_from_bracket(tournament):
    """Derive unique final positions from a completed bracket.

    Champion is 1st, the final's loser is 2nd, then losers ranked by the round
    they were eliminated (later round = higher finish), tie-broken by slot so
    positions are unique. No-op if the final isn't decided yet.
    """
    matches = list(tournament.bracket_matches.all())
    if not matches:
        return None
    rounds = max(m.round_number for m in matches)
    finals = [m for m in matches if m.round_number == rounds]
    final = finals[0]
    if final.status not in (TournamentMatch.Status.CONFIRMED, TournamentMatch.Status.BYE) or not final.winner_id:
        return None

    ranking = [final.winner_id]

    losers_by_round = {}
    for m in matches:
        if m.status in (TournamentMatch.Status.CONFIRMED, TournamentMatch.Status.BYE) and m.winner_id:
            loser = _loser_id(m)
            if loser:
                losers_by_round.setdefault(m.round_number, []).append((m.slot_number, loser))

    for r in sorted(losers_by_round.keys(), reverse=True):
        for _slot, loser in sorted(losers_by_round[r]):
            if loser not in ranking:
                ranking.append(loser)

    TournamentStanding.objects.filter(tournament=tournament).delete()
    for position, player_id in enumerate(ranking, start=1):
        TournamentStanding.objects.create(
            tournament=tournament,
            player_id=player_id,
            position=position,
        )
    return ranking

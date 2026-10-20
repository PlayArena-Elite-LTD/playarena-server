"""Dual-submission result resolution for tournament matches.

Both participants submit their result. When both are in:
  * they agree  -> the match auto-confirms (advances bracket / updates table),
  * they disagree -> the match becomes DISPUTED for the organiser to resolve.

Knockout submissions carry a winner; league submissions carry a scoreline.
Reuses `brackets.confirm_result` / `leagues.confirm_score` for the actual
finalisation so advancement and standings stay in one place.
"""

from django.db import transaction

from . import brackets, leagues
from .models import TournamentMatch, TournamentMatchSubmission


# Outcome codes returned to the caller so it can notify appropriately.
AWAITING_OPPONENT = 'AWAITING_OPPONENT'
CONFIRMED = 'CONFIRMED'
DISPUTED = 'DISPUTED'


def _validate_scores(s1, s2):
    try:
        s1, s2 = int(s1), int(s2)
    except (TypeError, ValueError):
        raise ValueError("Scores must be whole numbers.")
    if s1 < 0 or s2 < 0:
        raise ValueError("Scores cannot be negative.")
    # The model uses PositiveSmallIntegerField, whose maximum is 32767.
    if s1 > 32767 or s2 > 32767:
        raise ValueError("Scores cannot exceed 32767.")
    return s1, s2


@transaction.atomic
def submit_result(tournament, match, player_id, *, winner_id=None, s1=None, s2=None, evidence=None):
    """Record a participant's submission and resolve if both are in.

    Returns ``(match, outcome)`` where outcome is one of AWAITING_OPPONENT,
    CONFIRMED or DISPUTED.
    """
    # Lock and refresh the match row so simultaneous submissions cannot both
    # resolve the same match using stale state. Verify the supplied tournament
    # really owns this match before accepting a result.
    match = TournamentMatch.objects.select_for_update().get(pk=match.pk)
    if match.tournament_id != tournament.pk:
        raise ValueError("This match does not belong to the supplied tournament.")

    if match.status not in (
        TournamentMatch.Status.READY,
        TournamentMatch.Status.REPORTED,
        TournamentMatch.Status.DISPUTED,
    ):
        raise ValueError("This match is not awaiting a result.")
    if player_id not in (match.player1_id, match.player2_id):
        raise ValueError("Only a participant of this match can submit a result.")

    is_league = tournament.format == 'LEAGUE'
    defaults = {'evidence': evidence} if evidence is not None else {}

    if is_league:
        s1, s2 = _validate_scores(s1, s2)
        defaults.update({'player1_score': s1, 'player2_score': s2, 'winner': None})
    else:
        if winner_id not in (match.player1_id, match.player2_id):
            raise ValueError("The winner must be one of the two players.")
        defaults.update({'winner_id': winner_id, 'player1_score': None, 'player2_score': None})

    TournamentMatchSubmission.objects.update_or_create(
        match=match, player_id=player_id, defaults=defaults,
    )

    subs = {s.player_id: s for s in TournamentMatchSubmission.objects.filter(match_id=match.pk)}

    # Only one player in so far — wait for the other.
    if len(subs) < 2:
        match.status = TournamentMatch.Status.REPORTED
        match.reported_by_id = player_id
        match.reported_winner_id = winner_id if not is_league else None
        match.save(update_fields=['status', 'reported_by', 'reported_winner'])
        return match, AWAITING_OPPONENT

    a = subs.get(match.player1_id)
    b = subs.get(match.player2_id)

    if is_league:
        agree = (
            a and b
            and a.player1_score == b.player1_score
            and a.player2_score == b.player2_score
        )
        if agree:
            leagues.confirm_score(tournament, match, a.player1_score, a.player2_score)
            return match, CONFIRMED
    else:
        agree = a and b and a.winner_id and a.winner_id == b.winner_id
        if agree:
            brackets.confirm_result(match, winner_id=a.winner_id)
            return match, CONFIRMED

    # Both submitted but disagree — hand off to the organiser.
    match.status = TournamentMatch.Status.DISPUTED
    match.save(update_fields=['status'])
    return match, DISPUTED

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone

from accounts.decorators import support_staff_required
from matches.models import Match, Evidence


@support_staff_required
def match_list(request):
    status = request.GET.get('status', '')
    game = request.GET.get('game', '')
    q = request.GET.get('q', '').strip()

    matches = Match.objects.select_related('creator', 'joiner').order_by('-created_at')
    if status:
        matches = matches.filter(status=status)
    if game:
        matches = matches.filter(game=game)
    if q:
        matches = matches.filter(
            Q(joining_code__icontains=q) |
            Q(creator__username__icontains=q) |
            Q(joiner__username__icontains=q)
        )

    paginator = Paginator(matches, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'status': status,
        'game': game,
        'q': q,
        'status_choices': Match._meta.get_field('status').choices,
        'game_choices': Match.GAME_CHOICES,
    }
    return render(request, 'panel/matches_list.html', context)


@support_staff_required
def match_detail(request, match_id):
    match = get_object_or_404(Match.objects.select_related('creator', 'joiner', 'winner'), id=match_id)
    evidence_list = Evidence.objects.filter(match=match).select_related('user', 'verified_by').order_by('-uploaded_at')

    context = {
        'match': match,
        'evidence_list': evidence_list,
    }
    return render(request, 'panel/match_detail.html', context)


@support_staff_required
def verify_evidence(request, evidence_id):
    evidence = get_object_or_404(Evidence, id=evidence_id)
    if not evidence.is_verified:
        evidence.is_verified = True
        evidence.verified_by = request.user
        evidence.verified_at = timezone.now()
        evidence.save()
        messages.success(request, "Evidence marked as verified.")
    else:
        messages.info(request, "Evidence is already verified.")
    return redirect('match_detail', match_id=evidence.match_id)

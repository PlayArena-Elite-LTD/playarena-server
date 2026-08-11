from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from wallet.models import Wallet, Transaction
from alert.models import Notification
from .models import Match, Evidence, Tournament

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    change_list_template = 'admin/matches/match/change_list.html'
    list_display = (
        'id',
        'creator',
        'joiner',
        'game',
        'amount',
        'winnings',
        'status',
        'privacy',
        'device',
        'joining_code',
        'created_at',
        'declare_winner_action',
    )
    list_filter = (
        'game',
        'amount',
        'status',
        'privacy',
        'device',
        'created_at',
    )
    search_fields = (
        'creator__username',
        'joiner__username',
        'joining_code',
    )
    readonly_fields = ('joining_code', 'winnings', 'created_at')

    fieldsets = (
        (None, {
            'fields': ('creator', 'joiner', 'game', 'device', 'privacy', 'amount')
        }),
        ('Auto-generated Fields', {
            'fields': ('joining_code', 'winnings', 'status', 'created_at')
        }),
    )

    def declare_winner_action(self, obj):
        """Button that opens a modal to declare a winner when a player won't upload results."""
        if obj.status == 'COMPLETED':
            return format_html(
                '<span class="dispute-actions__empty">Winner: {}</span>',
                obj.winner.username if obj.winner else '-'
            )
        if not obj.joiner:
            return format_html('<span class="dispute-actions__empty">Awaiting joiner</span>')

        url = reverse('admin:matches_match_declare_winner', args=[obj.pk])
        return format_html(
            '<button type="button" class="dispute-action dispute-action--primary" '
            'data-action="declare-winner" data-url="{}" data-code="{}" '
            'data-creator-id="{}" data-creator-name="{}" '
            'data-joiner-id="{}" data-joiner-name="{}">Declare Winner</button>',
            url, obj.joining_code,
            obj.creator_id, obj.creator.username,
            obj.joiner_id, obj.joiner.username,
        )
    declare_winner_action.short_description = 'Declare Winner'

    def get_urls(self):
        custom_urls = [
            path(
                '<int:match_id>/declare-winner/',
                self.admin_site.admin_view(self.declare_winner_view),
                name='matches_match_declare_winner',
            ),
        ]
        return custom_urls + super().get_urls()

    @transaction.atomic
    def declare_winner_view(self, request, match_id):
        """Manually declare a match winner, e.g. when the losing player refuses to upload evidence."""
        match = get_object_or_404(Match, pk=match_id)
        changelist_url = reverse('admin:matches_match_changelist')

        if not self.has_change_permission(request, match):
            messages.error(request, "You don't have permission to do that.")
            return redirect(changelist_url)

        if request.method != 'POST':
            return redirect(changelist_url)

        if match.status == 'COMPLETED':
            messages.info(request, f"Match {match.joining_code} has already been completed.")
            return redirect(changelist_url)

        if not match.joiner:
            messages.error(request, "This match doesn't have a second player yet.")
            return redirect(changelist_url)

        winner_id = request.POST.get('winner_id')
        if winner_id not in (str(match.creator_id), str(match.joiner_id)):
            messages.error(request, "Please select a valid winner.")
            return redirect(changelist_url)

        winner = match.creator if winner_id == str(match.creator_id) else match.joiner
        loser = match.joiner if winner is match.creator else match.creator

        wallet = Wallet.objects.get(user=winner)
        wallet.balance += match.winnings
        wallet.save()
        Transaction.objects.create(
            wallet=wallet,
            amount=match.winnings,
            transaction_type='MATCH_WINNINGS',
            description=f"Winnings from {match.get_game_display()} match {match.joining_code} (declared by admin)",
            related_match=match,
        )

        Notification.objects.create(
            user=winner,
            message=f"You were declared the winner of the {match.get_game_display()} match against {loser.username}. ZMW {match.winnings} has been credited to your wallet."
        )
        Notification.objects.create(
            user=loser,
            message=f"{winner.username} was declared the winner of your {match.get_game_display()} match."
        )

        match.winner = winner
        match.status = 'COMPLETED'
        match.save(update_fields=['winner', 'status'])

        messages.success(request, f"{winner.username} declared winner of match {match.joining_code}.")
        return redirect(changelist_url)


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    """Admin interface for Evidence model"""
    list_display = ('id', 'match', 'user', 'file_type', 'uploaded_at', 'is_verified')
    list_filter = ('file_type', 'is_verified', 'uploaded_at')
    search_fields = ('match__joining_code', 'user__username', 'description')
    readonly_fields = ('uploaded_at', 'file_size', 'file_hash', 'ip_address', 'user_agent')
    date_hierarchy = 'uploaded_at'
    
    fieldsets = (
        ('Evidence Info', {
            'fields': ('match', 'user', 'file', 'file_type', 'description')
        }),
        ('Security Info', {
            'fields': ('file_size', 'file_hash', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('is_verified', 'verified_by', 'verified_at')
        }),
        ('Timestamps', {
            'fields': ('uploaded_at',)
        }),
    )


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'organisation',
        'game',
        'participation_amount',
        'max_players',
        'status',
        'start_date',
        'created_at',
    )
    list_filter = ('organisation', 'game', 'status', 'start_date', 'created_at')
    search_fields = ('name', 'organisation__name', 'organisation__email')
    readonly_fields = ('created_at', 'updated_at')

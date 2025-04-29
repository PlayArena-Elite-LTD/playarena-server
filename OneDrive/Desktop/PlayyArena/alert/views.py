from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib import messages
from django.utils import timezone

from .models import Notification, ReadNotification

@login_required
def notifications_list(request):
    """Display a list of user's notifications"""
    # Get all notifications for this user
    all_notifications = request.user.notifications.all()
    
    # Get read notifications IDs
    read_notifications = ReadNotification.objects.filter(
        user=request.user,
        notification__in=all_notifications
    ).values_list('notification_id', flat=True)
    
    # Get unread and read notifications separately
    unread_notifications = all_notifications.exclude(id__in=read_notifications)
    read_notifications_objects = all_notifications.filter(id__in=read_notifications)
    
    context = {
        'unread_notifications': unread_notifications,
        'read_notifications': read_notifications_objects,
        'username': request.user.username
    }
    
    return render(request, 'alert/notifications.html', context)

@login_required
def mark_notification_read(request, notification_id):
    """Mark a specific notification as read"""
    try:
        notification = Notification.objects.get(id=notification_id, user=request.user)
        ReadNotification.objects.get_or_create(
            user=request.user,
            notification=notification,
            defaults={'read_at': timezone.now()}
        )
        messages.success(request, "Notification marked as read.")
    except Notification.DoesNotExist:
        messages.error(request, "Notification not found.")
    
    return redirect('notifications_list')
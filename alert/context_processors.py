def notification_count(request):
    """Context processor to add unread notification count to all templates"""
    if request.user.is_authenticated:
        # Get all notifications for this user
        all_notifications = request.user.notifications.all()
        
        # Get all read notifications for this user
        from alert.models import ReadNotification
        read_notifications = ReadNotification.objects.filter(
            user=request.user,
            notification__in=all_notifications
        ).values_list('notification_id', flat=True)
        
        # Count unread notifications
        unread_count = all_notifications.exclude(id__in=read_notifications).count()
        
        return {'notification_unread_count': unread_count}
    return {'notification_unread_count': 0}
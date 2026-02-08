from django.core.cache import caches
from alert.models import Notification


def notification_count(request):
    """Context processor to add unread notification count to all templates"""
    if request.user.is_authenticated:
        cache = caches["ratelimit"]
        key = f"notif_unread_count:{request.user.id}"
        cached = cache.get(key)
        if cached is not None:
            return {"notification_unread_count": cached}

        # Single-query unread count using reverse relation to ReadNotification
        unread_count = (
            Notification.objects.filter(user=request.user)
            .exclude(readnotification__user=request.user)
            .count()
        )
        cache.set(key, unread_count, 10)
        return {"notification_unread_count": unread_count}
    return {'notification_unread_count': 0}
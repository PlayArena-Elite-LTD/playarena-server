from django.db.models import Q, Count, Exists, OuterRef
from .models import Message, ReadMessage
from django.core.cache import caches

def unread_messages_count(request):
    if request.user.is_authenticated:
        cache = caches["ratelimit"]
        key = f"msg_unread_conv_count:{request.user.id}"
        cached = cache.get(key)
        if cached is not None:
            return {"unread_conversations_count": cached}

        # Count distinct conversations (users) that have unread messages
        users_with_unread = Message.objects.filter(
            receiver=request.user
        ).exclude(
            read_marks__receiver=request.user
        ).values('sender').distinct().count()

        cache.set(key, users_with_unread, 10)
        return {'unread_conversations_count': users_with_unread}
    return {'unread_conversations_count': 0}
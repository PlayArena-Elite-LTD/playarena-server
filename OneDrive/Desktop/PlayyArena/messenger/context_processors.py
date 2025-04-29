from django.db.models import Q, Count, Exists, OuterRef
from .models import Message, ReadMessage

def unread_messages_count(request):
    if request.user.is_authenticated:
        # Count distinct conversations (users) that have unread messages
        users_with_unread = Message.objects.filter(
            receiver=request.user
        ).exclude(
            read_marks__receiver=request.user
        ).values('sender').distinct().count()
        
        return {'unread_conversations_count': users_with_unread}
    return {'unread_conversations_count': 0}
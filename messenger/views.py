from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import Message, ReadMessage
from .forms import MessageForm

User = get_user_model()

@login_required
def messages_list(request):
    """View to list all conversations for the current user."""
    # Get all users the current user has exchanged messages with
    conversations = User.objects.filter(
        Q(sent_messages__receiver=request.user) | 
        Q(received_messages__sender=request.user)
    ).distinct()
    
    # For each conversation, get the latest message
    conversation_data = []
    for user in conversations:
        latest_message = Message.objects.filter(
            (Q(sender=request.user) & Q(receiver=user)) |
            (Q(sender=user) & Q(receiver=request.user))
        ).order_by('-created_at').first()
        
        # Count unread messages
        unread_count = Message.objects.filter(
            sender=user, 
            receiver=request.user
        ).exclude(
            id__in=ReadMessage.objects.filter(
                message__sender=user,
                receiver=request.user
            ).values_list('message_id', flat=True)
        ).count()
        
        conversation_data.append({
            'user': user,
            'latest_message': latest_message,
            'unread_count': unread_count
        })
    
    # Sort conversations by latest message time
    conversation_data.sort(
        key=lambda x: x['latest_message'].created_at if x['latest_message'] else timezone.now(),
        reverse=True
    )
    
    context = {
        'conversations': conversation_data,
    }
    return render(request, 'messenger/messages_list.html', context)

@login_required
def conversation(request, user_id=None):
    """
    View to display a conversation with another user and allow sending new messages.
    Shows message history and provides a form to send new messages.
    """
    # If no user_id provided, it might be in the POST data
    if user_id is None and 'receiver' in request.POST:
        user_id = request.POST.get('receiver')
    
    other_user = get_object_or_404(User, id=user_id)
    
    # Check that users are not messaging themselves
    if other_user == request.user:
        messages.error(request, "You cannot send messages to yourself.")
        return redirect('messages_list')
    
    # Handle form submission for new message
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            new_message = form.save(commit=False)
            new_message.sender = request.user
            new_message.receiver = other_user
            new_message.save()
            
            # Redirect to same conversation to avoid form resubmission
            return redirect('conversation', user_id=other_user.id)
    else:
        form = MessageForm()
    
    # Get all messages between these two users
    conversation_messages = Message.objects.filter(
        (Q(sender=request.user) & Q(receiver=other_user)) |
        (Q(sender=other_user) & Q(receiver=request.user))
    ).order_by('created_at')
    
    # Mark all received messages as read
    unread_messages = Message.objects.filter(
        sender=other_user,
        receiver=request.user
    ).exclude(
        id__in=ReadMessage.objects.filter(
            message__in=conversation_messages,
            receiver=request.user
        ).values_list('message_id', flat=True)
    )
    
    # Create ReadMessage objects for all unread messages
    for msg in unread_messages:
        ReadMessage.objects.create(
            message=msg,
            receiver=request.user
        )
    
    context = {
        'other_user': other_user,
        'messages': conversation_messages,
        'form': form,
    }
    
    return render(request, 'messenger/conversation.html', context)
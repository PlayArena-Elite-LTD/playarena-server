from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from accounts.decorators import support_staff_required

User = get_user_model()


@support_staff_required
def user_list(request):
    """List users with search (username/email) and status/role filters."""
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    role = request.GET.get('role', '')

    users = User.objects.all().order_by('-date_joined')
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q))
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'disabled':
        users = users.filter(is_active=False)
    if role == 'support_staff':
        users = users.filter(is_support_staff=True)
    elif role == 'staff':
        users = users.filter(is_staff=True)

    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'q': q,
        'status': status,
        'role': role,
    }
    return render(request, 'panel/users_list.html', context)


@support_staff_required
def disable_user(request, user_id):
    """Disable a user account. Mirrors accounts.admin.CustomUserAdmin.disable_users guards."""
    user = get_object_or_404(User, id=user_id)
    if user.is_superuser:
        messages.error(request, "Cannot disable a superuser account.")
    elif user.id == request.user.id:
        messages.error(request, "You cannot disable your own account.")
    elif not user.is_active:
        messages.info(request, "User is already disabled.")
    else:
        user.is_active = False
        user.save()
        messages.success(request, f"User {user.username} has been disabled.")
    return redirect('user_list')


@support_staff_required
def enable_user(request, user_id):
    """Re-enable a user account."""
    user = get_object_or_404(User, id=user_id)
    if user.is_active:
        messages.info(request, "User is already active.")
    else:
        user.is_active = True
        user.save()
        messages.success(request, f"User {user.username} has been enabled.")
    return redirect('user_list')

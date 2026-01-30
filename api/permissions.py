from rest_framework import permissions


class IsWalletOwner(permissions.BasePermission):
    """Allow access only to the owner of a wallet object."""

    def has_object_permission(self, request, view, obj):
        return getattr(obj, 'user_id', None) == request.user.id

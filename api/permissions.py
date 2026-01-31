from rest_framework import permissions


class IsWalletOwner(permissions.BasePermission):
    """Allow access only to the owner of a wallet object."""

    def has_object_permission(self, request, view, obj):
        return getattr(obj, 'user_id', None) == request.user.id


class IsMatchParticipant(permissions.BasePermission):
    """Allow access only to match participants (creator or joiner)."""

    def has_object_permission(self, request, view, obj):
        return request.user in [getattr(obj, 'creator', None), getattr(obj, 'joiner', None)]

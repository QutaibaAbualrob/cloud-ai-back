"""
Custom DRF permissions for user-scoped data access.

All CloudAI resources are owned by a user. These permissions ensure
users can only access their own data, enforced at the object level.
"""

from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """
    Object-level permission: only allow access if the requesting user
    owns the object.

    Assumes the model has a `user` ForeignKey field.
    Used by ModelViewSets with get_queryset() already filtered by user
    as a defence-in-depth layer.
    """

    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

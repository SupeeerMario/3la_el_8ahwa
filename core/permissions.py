from rest_framework.permissions import BasePermission

from groups.models import Group, GroupMember


def _group_of(obj):
    """Return the Group an object belongs to (or is)."""
    if isinstance(obj, Group):
        return obj

    group = getattr(obj, "group", None)
    if group is not None:
        return group

    event = getattr(obj, "event", None)
    if event is None:
        event = getattr(getattr(obj, "location", None), "event", None)

    return getattr(event, "group", None)


class IsGroupMember(BasePermission):
    """Object-level: the requesting user belongs to the object's group."""

    message = "You are not a member of this group."

    def has_object_permission(self, request, view, obj):
        group = _group_of(obj)
        if group is None:
            return False
        return GroupMember.objects.filter(
            user=request.user, group=group
        ).exists()


class IsGroupAdmin(BasePermission):
    """Object-level: the requesting user is an admin of the object's group."""

    message = "You must be an admin of this group to perform this action."

    def has_object_permission(self, request, view, obj):
        group = _group_of(obj)
        if group is None:
            return False
        return GroupMember.objects.filter(
            user=request.user, group=group, role="admin"
        ).exists()


class IsEventCreator(BasePermission):
    """Object-level: the requesting user created the event."""

    message = "Only the event creator can perform this action."

    def has_object_permission(self, request, view, obj):
        return getattr(obj, "created_by_id", None) == request.user.id


class IsLocationProposer(BasePermission):
    """Object-level: the requesting user proposed this location."""

    message = "Only the member who proposed this location can change it."

    def has_object_permission(self, request, view, obj):
        return getattr(obj, "proposed_by_id", None) == request.user.id

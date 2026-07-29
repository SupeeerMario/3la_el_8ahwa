from django.db import transaction
from django.db.models import Q

from core import errors
from notifications.services import notify_group
from . import room
from .models import GroupInvitaion, GroupInviteToken, GroupMember


def token_query(value):
    raw = (value or '').strip()
    return GroupInviteToken.objects.filter(Q(token = raw) | Q(code = raw.upper()))


def token_for(value):
    return token_query(value).select_related('group', 'created_by').first()


def unusable_reason(invite_token):
    if invite_token.revoked:
        return errors.INVITE_TOKEN_REVOKED
    if invite_token.is_expired:
        return errors.INVITE_TOKEN_EXPIRED
    if invite_token.is_exhausted:
        return errors.INVITE_TOKEN_EXHAUSTED
    return None


def redeem(value, user):
    """Join `user` to the group behind an invite token or short code.

    Returns (group, error_code). Exactly one of the two is None.
    """
    with transaction.atomic():
        try:
            invite_token = token_query(value).select_for_update().get()
        except GroupInviteToken.DoesNotExist:
            return None, errors.INVITE_TOKEN_NOT_FOUND

        reason = unusable_reason(invite_token)
        if reason is not None:
            return None, reason

        group = invite_token.group

        if GroupMember.objects.filter(user = user, group = group).exists():
            return None, errors.ALREADY_MEMBER

        GroupMember.objects.create(user = user, group = group, role = "member")

        invite_token.uses += 1
        invite_token.save(update_fields=["uses"])

        GroupInvitaion.objects.filter(group = group, invited_user = user).delete()

    room.member_joined(group, user)

    notify_group(
        group,
        'new_member',
        {
            'group_id': group.id,
            'group_name': group.name,
            'user_id': user.id,
            'username': user.username,
        },
        exclude=[user],
    )

    return group, None

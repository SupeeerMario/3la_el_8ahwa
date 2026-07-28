from .models import Notification


def notify(user, kind, payload):
    return Notification.objects.create(user=user, kind=kind, payload=payload)


def notify_many(users, kind, payload):
    users = [user for user in users if user is not None]
    if not users:
        return []

    return Notification.objects.bulk_create([
        Notification(user=user, kind=kind, payload=payload) for user in users
    ])


def notify_group(group, kind, payload, exclude=None):
    excluded_ids = {user.id for user in (exclude or []) if user is not None}

    from groups.models import GroupMember

    recipients = [
        membership.user
        for membership in GroupMember.objects.filter(group=group).select_related("user")
        if membership.user_id not in excluded_ids
    ]

    return notify_many(recipients, kind, payload)

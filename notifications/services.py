from .models import Notification


def notify(user, notification_type, payload):
    return Notification.objects.create(
        user=user, notification_type=notification_type, payload=payload
    )


def notify_many(users, notification_type, payload):
    users = [user for user in users if user is not None]
    if not users:
        return []

    return Notification.objects.bulk_create([
        Notification(user=user, notification_type=notification_type, payload=payload)
        for user in users
    ])


def notify_group(group, notification_type, payload, exclude=None):
    excluded_ids = {user.id for user in (exclude or []) if user is not None}

    from groups.models import GroupMember

    recipients = [
        membership.user
        for membership in GroupMember.objects.filter(group=group).select_related("user")
        if membership.user_id not in excluded_ids
    ]

    return notify_many(recipients, notification_type, payload)

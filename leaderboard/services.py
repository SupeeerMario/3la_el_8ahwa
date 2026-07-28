from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from groups.models import Group

User = get_user_model()


def _ranked(rows, key):
    standings = []
    previous_score = None
    previous_rank = 0

    for position, row in enumerate(rows, start=1):
        score = key(row)
        if score == previous_score:
            row['rank'] = previous_rank
        else:
            row['rank'] = position
            previous_rank = position
            previous_score = score
        standings.append(row)

    return standings


def group_member_standings(group):
    members = User.objects.filter(group_members__group=group).annotate(
        checkin_count=Count(
            'checkins',
            filter=Q(checkins__is_valid=True, checkins__event__group=group),
            distinct=True,
        )
    ).order_by('-checkin_count', 'id')

    return _ranked(
        [{'user': member, 'checkins': member.checkin_count} for member in members],
        lambda row: row['checkins'],
    )


def user_standings():
    users = User.objects.annotate(
        checkin_count=Count('checkins', filter=Q(checkins__is_valid=True), distinct=True)
    ).filter(checkin_count__gt=0).order_by('-checkin_count', 'id')

    return _ranked(
        [{'user': user, 'checkins': user.checkin_count} for user in users],
        lambda row: row['checkins'],
    )


def group_standings():
    groups = Group.objects.annotate(
        member_count=Count('members', distinct=True),
        event_count=Count(
            'events',
            filter=Q(events__winning_location__isnull=False),
            distinct=True,
        ),
        checkin_count=Count(
            'events__checkins',
            filter=Q(events__checkins__is_valid=True),
            distinct=True,
        ),
    )

    rows = []
    for group in groups:
        possible = group.member_count * group.event_count
        if possible == 0:
            continue

        rows.append({
            'group': group,
            'checkins': group.checkin_count,
            'members': group.member_count,
            'events': group.event_count,
            'rate': round(group.checkin_count / possible, 4),
        })

    rows.sort(key=lambda row: (-row['rate'], -row['members'], row['group'].id))

    return _ranked(rows, lambda row: (row['rate'], row['members']))

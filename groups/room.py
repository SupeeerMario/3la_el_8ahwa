from .models import Message


def post_system_message(group, event, body, **context):
    payload = {"event": event}
    payload.update(context)

    return Message.objects.create(
        group=group, sender=None, kind="system", body=body, payload=payload
    )


def member_joined(group, user):
    return post_system_message(
        group,
        "member_joined",
        f"{user.username} joined the group",
        actor_id=user.id,
        actor_username=user.username,
    )


def member_left(group, user):
    return post_system_message(
        group,
        "member_left",
        f"{user.username} left the group",
        actor_id=user.id,
        actor_username=user.username,
    )


def event_created(event, actor):
    return post_system_message(
        event.group,
        "event_created",
        f"{actor.username} created {event.title}",
        actor_id=actor.id,
        actor_username=actor.username,
        event_id=event.id,
        target=event.title,
        start_time=event.start_time.isoformat(),
    )


def location_proposed(location, actor):
    return post_system_message(
        location.event.group,
        "location_proposed",
        f"{actor.username} proposed {location.name}",
        actor_id=actor.id,
        actor_username=actor.username,
        event_id=location.event_id,
        location_id=location.id,
        target=location.name,
    )


def vote_cast(location, actor):
    return post_system_message(
        location.event.group,
        "vote_cast",
        f"{actor.username} voted for {location.name}",
        actor_id=actor.id,
        actor_username=actor.username,
        event_id=location.event_id,
        location_id=location.id,
        target=location.name,
    )


def voting_closed(event):
    winner = event.winning_location

    if winner is None:
        return post_system_message(
            event.group,
            "voting_closed",
            f"Voting closed for {event.title} with no winner",
            event_id=event.id,
            target=None,
        )

    return post_system_message(
        event.group,
        "voting_closed",
        f"{winner.name} won the vote for {event.title}",
        event_id=event.id,
        location_id=winner.id,
        target=winner.name,
    )


def checkin_recorded(checkin, actor):
    event = checkin.event
    place = event.winning_location.name if event.winning_location else event.title

    if checkin.is_valid:
        return post_system_message(
            event.group,
            "checkin_valid",
            f"{actor.username} checked in at {place}",
            actor_id=actor.id,
            actor_username=actor.username,
            event_id=event.id,
            checkin_id=checkin.id,
            target=place,
        )

    return post_system_message(
        event.group,
        "checkin_rejected",
        f"{actor.username} tried to check in at {place} but was too far away",
        actor_id=actor.id,
        actor_username=actor.username,
        event_id=event.id,
        checkin_id=checkin.id,
        target=place,
    )

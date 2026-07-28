from celery import shared_task

from .voting import freeze_due_winners, freeze_winner


@shared_task(name="events.freeze_due_winners", ignore_result=True)
def freeze_due_winners_task():
    return freeze_due_winners()


@shared_task(name="events.freeze_event_winner", ignore_result=True)
def freeze_event_winner_task(event_id):
    event = freeze_winner(event_id)
    return None if event is None else event.id

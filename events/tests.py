from datetime import timedelta

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from groups.models import Group, GroupMember
from events.models import Event, EventLocation, LocationVote

User = get_user_model()


def _future(hours=0):
    return timezone.now() + timedelta(days=1, hours=hours)


class EventCreateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u1", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.user)
        GroupMember.objects.create(group=self.group, user=self.user, role="admin")

    def _payload(self, **over):
        data = {
            "group_id": self.group.id,
            "title": "Meetup",
            "start_time": _future().isoformat(),
            "end_time": _future(hours=2).isoformat(),
        }
        data.update(over)
        return data

    def test_member_can_create_event(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/events/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Event.objects.filter(title="Meetup", created_by=self.user).exists())

    def test_non_member_cannot_create_event(self):
        outsider = User.objects.create_user(username="outsider", password="pw12345678")
        self.client.force_authenticate(outsider)
        resp = self.client.post("/events/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_end_time_before_start_time_is_rejected(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/events/", self._payload(
            end_time=(_future() - timedelta(hours=1)).isoformat(),
        ))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_start_time_in_the_past_is_rejected(self):
        self.client.force_authenticate(self.user)
        past = timezone.now() - timedelta(days=1)
        resp = self.client.post("/events/", self._payload(start_time=past.isoformat()))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_winning_location_cannot_be_set_by_client(self):
        # winning_location was removed from the write serializer; a client value
        # must be ignored, leaving the event with no winner on creation.
        self.client.force_authenticate(self.user)
        event = Event.objects.create(
            created_by=self.user, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )
        loc = EventLocation.objects.create(
            event=event, proposed_by=self.user, name="Cafe", latitude=1.0, longitude=2.0,
        )
        resp = self.client.post("/events/", self._payload(winning_location=loc.id))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(Event.objects.get(title="Meetup").winning_location)


class EventCreatorPermissionTests(APITestCase):
    """Locks in creator-only enforcement on update/destroy (destroy was
    previously unguarded)."""

    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="pw12345678")
        self.member = User.objects.create_user(username="member", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.creator)
        GroupMember.objects.create(group=self.group, user=self.creator, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")
        self.event = Event.objects.create(
            created_by=self.creator, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )

    def test_other_member_cannot_delete_event(self):
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/events/{self.event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Event.objects.filter(id=self.event.id).exists())

    def test_creator_can_delete_event(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.delete(f"/events/{self.event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Event.objects.filter(id=self.event.id).exists())


class EventLocationSerializerTests(APITestCase):
    """The location detail serializer used to raise on use; it must now return
    vote_count and voted_by."""

    def setUp(self):
        self.user = User.objects.create_user(username="u", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.user)
        GroupMember.objects.create(group=self.group, user=self.user, role="admin")
        self.event = Event.objects.create(
            created_by=self.user, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )
        self.loc = EventLocation.objects.create(
            event=self.event, proposed_by=self.user, name="Cafe", latitude=1.0, longitude=2.0,
        )

    def test_location_list_returns_vote_data_without_erroring(self):
        LocationVote.objects.create(location=self.loc, voted_by=self.user)
        self.client.force_authenticate(self.user)
        resp = self.client.get(f"/event-locations/?event={self.event.id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["vote_count"], 1)
        self.assertIn("u", resp.data[0]["voted_by"])


class EventLocationCreateTests(APITestCase):
    """Covers the EventLocationViewSet.create proposal flow."""

    def setUp(self):
        self.user = User.objects.create_user(username="proposer", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.user)
        GroupMember.objects.create(group=self.group, user=self.user, role="admin")

    def _upcoming_event(self):
        return Event.objects.create(
            created_by=self.user, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )

    def _payload(self, event):
        return {
            "event_id": event.id,
            "name": "Cafe",
            "latitude": 1.0,
            "longitude": 2.0,
        }

    def test_member_can_propose_location_for_upcoming_event(self):
        event = self._upcoming_event()
        self.client.force_authenticate(self.user)
        resp = self.client.post("/event-locations/", self._payload(event))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            EventLocation.objects.filter(event=event, proposed_by=self.user).exists()
        )

    def test_non_member_cannot_propose_location(self):
        event = self._upcoming_event()
        outsider = User.objects.create_user(username="outsiderL", password="pw12345678")
        self.client.force_authenticate(outsider)
        resp = self.client.post("/event-locations/", self._payload(event))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_propose_for_unknown_event(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/event-locations/", {
            "event_id": 999999, "name": "Cafe", "latitude": 1.0, "longitude": 2.0,
        })
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposing_for_finished_event_is_closed(self):
        past_event = Event.objects.create(
            created_by=self.user, group=self.group, title="Done",
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
        )
        self.client.force_authenticate(self.user)
        resp = self.client.post("/event-locations/", self._payload(past_event))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

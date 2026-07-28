from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from groups.models import Group, GroupMember, Message
from events.models import Event, EventLocation, LocationVote
from events.reminders import send_due_reminders, send_reminder
from events.voting import freeze_due_winners, freeze_winner
from notifications.models import Notification

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


class EventLocationScopingTests(APITestCase):
    """Locks in two fixes on EventLocationViewSet:

    - get_queryset() is now scoped by group membership FIRST, then filtered
      by the attacker-supplied ?event= query param -- previously it filtered
      on ?event= alone, so any authenticated user could read (and, through
      the detail routes, edit or delete) another group's proposed locations.
    - the detail routes had no object-level guard at all; only the member who
      proposed a location may edit or delete it (IsLocationProposer).
    """

    def setUp(self):
        self.admin = User.objects.create_user(username="loc_admin", password="pw12345678")
        self.member = User.objects.create_user(username="loc_member", password="pw12345678")
        self.outsider = User.objects.create_user(username="loc_outsider", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")
        self.event = Event.objects.create(
            created_by=self.admin, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )
        self.loc = EventLocation.objects.create(
            event=self.event, proposed_by=self.admin, name="Cafe", latitude=1.0, longitude=2.0,
        )

    def test_non_member_listing_gets_empty_list_not_leaked_data(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/event-locations/?event={self.event.id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_non_member_cannot_patch_or_delete_location(self):
        self.client.force_authenticate(self.outsider)
        url = f"/event-locations/{self.loc.id}/?event={self.event.id}"

        patch_resp = self.client.patch(url, {"name": "Hacked"})
        self.assertEqual(patch_resp.status_code, status.HTTP_404_NOT_FOUND)

        delete_resp = self.client.delete(url)
        self.assertEqual(delete_resp.status_code, status.HTTP_404_NOT_FOUND)

        self.loc.refresh_from_db()
        self.assertEqual(self.loc.name, "Cafe")
        self.assertTrue(EventLocation.objects.filter(id=self.loc.id).exists())

    def test_group_member_who_did_not_propose_gets_403(self):
        self.client.force_authenticate(self.member)
        url = f"/event-locations/{self.loc.id}/?event={self.event.id}"

        patch_resp = self.client.patch(url, {"name": "Hacked"})
        self.assertEqual(patch_resp.status_code, status.HTTP_403_FORBIDDEN)

        delete_resp = self.client.delete(url)
        self.assertEqual(delete_resp.status_code, status.HTTP_403_FORBIDDEN)

        self.loc.refresh_from_db()
        self.assertEqual(self.loc.name, "Cafe")
        self.assertTrue(EventLocation.objects.filter(id=self.loc.id).exists())

    def test_proposer_can_patch_and_delete_own_location(self):
        self.client.force_authenticate(self.admin)
        url = f"/event-locations/{self.loc.id}/?event={self.event.id}"

        patch_resp = self.client.patch(url, {"name": "Renamed"})
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.loc.refresh_from_db()
        self.assertEqual(self.loc.name, "Renamed")

        delete_resp = self.client.delete(url)
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EventLocation.objects.filter(id=self.loc.id).exists())


class NonNumericIdTests(APITestCase):
    """A non-numeric *_id used to reach the ORM as an integer lookup and raise
    ValueError -> uncaught 500. _as_int() now coerces it to None first, so it
    funnels into the same 403/404 a missing id already produced."""

    def setUp(self):
        self.user = User.objects.create_user(username="idcheck", password="pw12345678")

    def test_create_event_with_non_numeric_group_id_is_403_not_500(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/events/", {
            "group_id": "abc",
            "title": "T",
            "start_time": _future().isoformat(),
            "end_time": _future(hours=2).isoformat(),
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_location_with_non_numeric_event_id_is_404_not_500(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/event-locations/", {
            "event_id": "abc",
            "name": "Cafe",
            "latitude": 1.0,
            "longitude": 2.0,
        })
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class EventUpdateTests(APITestCase):
    """EventViewSet update/partial_update coverage, previously missing
    entirely: creator-only enforcement (the destroy analogue is covered by
    EventCreatorPermissionTests) and the partial-update fallback path in
    EventSerializer.validate(), which falls back to self.instance's stored
    bound when a PATCH body only supplies one of start_time/end_time."""

    def setUp(self):
        self.creator = User.objects.create_user(username="ev_creator", password="pw12345678")
        self.member = User.objects.create_user(username="ev_member", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.creator)
        GroupMember.objects.create(group=self.group, user=self.creator, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")
        self.event = Event.objects.create(
            created_by=self.creator, group=self.group, title="E",
            start_time=_future(hours=2), end_time=_future(hours=4),
        )

    def test_non_creator_member_cannot_update_event(self):
        self.client.force_authenticate(self.member)
        resp = self.client.patch(f"/events/{self.event.id}/", {"title": "Hacked"})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "E")

    def test_creator_patching_end_time_alone_before_stored_start_time_is_rejected(self):
        original_end_time = self.event.end_time
        self.client.force_authenticate(self.creator)
        resp = self.client.patch(
            f"/events/{self.event.id}/",
            {"end_time": _future(hours=1).isoformat()},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.event.refresh_from_db()
        self.assertEqual(self.event.end_time, original_end_time)


class VotingBaseTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username="voter", password="pw12345678")
        self.other = User.objects.create_user(username="voter2", password="pw12345678")
        self.outsider = User.objects.create_user(username="outsider", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.member)
        GroupMember.objects.create(group=self.group, user=self.member, role="admin")
        GroupMember.objects.create(group=self.group, user=self.other, role="member")
        self.event = Event.objects.create(
            created_by=self.member, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )
        self.cafe = EventLocation.objects.create(
            event=self.event, proposed_by=self.member,
            name="Cafe", latitude=1.0, longitude=2.0,
        )
        self.diner = EventLocation.objects.create(
            event=self.event, proposed_by=self.other,
            name="Diner", latitude=3.0, longitude=4.0,
        )

    def _start_event_now(self):
        Event.objects.filter(pk=self.event.pk).update(
            start_time=timezone.now() - timedelta(minutes=1)
        )
        self.event.refresh_from_db()


class CastVoteTests(VotingBaseTests):
    def test_member_can_vote(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        vote = LocationVote.objects.get(voted_by=self.member)
        self.assertEqual(vote.location_id, self.cafe.id)
        self.assertEqual(vote.event_id, self.event.id)

    def test_voting_twice_for_the_same_location_is_rejected(self):
        self.client.force_authenticate(self.member)
        self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "already_voted")
        self.assertEqual(LocationVote.objects.filter(voted_by=self.member).count(), 1)

    def test_voting_for_a_second_location_moves_the_vote(self):
        self.client.force_authenticate(self.member)
        self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        resp = self.client.post(f"/event-locations/{self.diner.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        votes = LocationVote.objects.filter(voted_by=self.member)
        self.assertEqual(votes.count(), 1)
        self.assertEqual(votes.first().location_id, self.diner.id)

    def test_one_vote_per_event_is_enforced_by_the_database(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LocationVote.objects.create(location=self.diner, voted_by=self.member)

    def test_unauthenticated_cannot_vote(self):
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_member_cannot_vote(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(LocationVote.objects.exists())

    def test_voting_after_start_time_is_rejected(self):
        self._start_event_now()
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "voting_closed")
        self.assertFalse(LocationVote.objects.exists())

    def test_voting_after_the_winner_is_frozen_is_rejected(self):
        Event.objects.filter(pk=self.event.pk).update(winner_frozen=True)
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "voting_closed")


class UnvoteTests(VotingBaseTests):
    def test_member_can_withdraw_a_vote(self):
        self.client.force_authenticate(self.member)
        self.client.post(f"/event-locations/{self.cafe.id}/vote/")
        resp = self.client.delete(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LocationVote.objects.exists())

    def test_withdrawing_a_vote_that_was_never_cast_is_404(self):
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "vote_not_found")

    def test_withdrawing_another_members_vote_is_404(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.other)
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(LocationVote.objects.filter(voted_by=self.other).exists())

    def test_unauthenticated_cannot_withdraw_a_vote(self):
        resp = self.client.delete(f"/event-locations/{self.cafe.id}/vote/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class LocationDetailRouteTests(VotingBaseTests):
    """Detail routes must resolve without the ?event= list filter."""

    def test_retrieve_without_event_query_param_succeeds(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/event-locations/{self.cafe.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], self.cafe.id)

    def test_list_without_event_query_param_is_empty(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/event-locations/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_non_numeric_location_id_is_404(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/event-locations/abc/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_vote_count_reflects_cast_votes(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        LocationVote.objects.create(location=self.cafe, voted_by=self.other)
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/event-locations/?event={self.event.id}")
        counts = {row["name"]: row["vote_count"] for row in resp.data}
        self.assertEqual(counts, {"Cafe": 2, "Diner": 0})


class TallyEndpointTests(VotingBaseTests):
    def test_tally_ranks_locations_and_reports_my_vote(self):
        LocationVote.objects.create(location=self.diner, voted_by=self.member)
        LocationVote.objects.create(location=self.diner, voted_by=self.other)
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/events/{self.event.id}/tally/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(row["name"], row["vote_count"]) for row in resp.data["locations"]],
            [("Diner", 2), ("Cafe", 0)],
        )
        self.assertEqual(resp.data["my_vote"], self.diner.id)
        self.assertTrue(resp.data["voting_open"])
        self.assertFalse(resp.data["winner_frozen"])
        self.assertIsNone(resp.data["winning_location"])

    def test_tally_my_vote_is_null_when_the_member_has_not_voted(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/events/{self.event.id}/tally/")
        self.assertIsNone(resp.data["my_vote"])

    def test_tally_does_not_freeze_the_winner_on_read(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        self._start_event_now()
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/events/{self.event.id}/tally/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        self.assertFalse(self.event.winner_frozen)
        self.assertIsNone(self.event.winning_location)

    def test_non_member_cannot_read_the_tally(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/events/{self.event.id}/tally/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_read_the_tally(self):
        resp = self.client.get(f"/events/{self.event.id}/tally/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class FreezeWinnerTests(VotingBaseTests):
    def test_most_voted_location_wins(self):
        LocationVote.objects.create(location=self.diner, voted_by=self.member)
        LocationVote.objects.create(location=self.diner, voted_by=self.other)
        freeze_winner(self.event.id)
        self.event.refresh_from_db()
        self.assertEqual(self.event.winning_location_id, self.diner.id)
        self.assertTrue(self.event.winner_frozen)

    def test_a_tie_is_broken_at_random_among_the_tied_locations(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        LocationVote.objects.create(location=self.diner, voted_by=self.other)
        with mock.patch("events.voting.random.choice") as choice:
            choice.side_effect = lambda candidates: candidates[-1]
            freeze_winner(self.event.id)
            tied = [loc.id for loc in choice.call_args.args[0]]
        self.assertEqual(sorted(tied), sorted([self.cafe.id, self.diner.id]))
        self.event.refresh_from_db()
        self.assertEqual(self.event.winning_location_id, self.diner.id)

    def test_the_other_tied_location_is_equally_reachable(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        LocationVote.objects.create(location=self.diner, voted_by=self.other)
        with mock.patch("events.voting.random.choice", lambda candidates: candidates[0]):
            freeze_winner(self.event.id)
        self.event.refresh_from_db()
        self.assertEqual(self.event.winning_location_id, self.cafe.id)

    def test_a_location_with_fewer_votes_never_enters_the_tiebreak(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        with mock.patch("events.voting.random.choice") as choice:
            choice.side_effect = lambda candidates: candidates[0]
            freeze_winner(self.event.id)
            tied = [loc.id for loc in choice.call_args.args[0]]
        self.assertEqual(tied, [self.cafe.id])

    def test_an_event_with_no_votes_freezes_without_a_winner(self):
        freeze_winner(self.event.id)
        self.event.refresh_from_db()
        self.assertTrue(self.event.winner_frozen)
        self.assertIsNone(self.event.winning_location)

    def test_a_frozen_winner_is_never_recomputed(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        freeze_winner(self.event.id)
        self.event.refresh_from_db()
        self.assertEqual(self.event.winning_location_id, self.cafe.id)

        LocationVote.objects.create(location=self.diner, voted_by=self.other)
        LocationVote.objects.create(
            location=self.diner,
            voted_by=User.objects.create_user(username="v3", password="pw12345678"),
        )
        freeze_winner(self.event.id)
        self.event.refresh_from_db()
        self.assertEqual(self.event.winning_location_id, self.cafe.id)

    def test_freezing_a_missing_event_returns_none(self):
        self.assertIsNone(freeze_winner(self.event.id + 999))


class FreezeDueWinnersTests(VotingBaseTests):
    def test_only_started_events_are_frozen(self):
        LocationVote.objects.create(location=self.cafe, voted_by=self.member)
        self.assertEqual(freeze_due_winners(), 0)
        self.event.refresh_from_db()
        self.assertFalse(self.event.winner_frozen)

        self._start_event_now()
        self.assertEqual(freeze_due_winners(), 1)
        self.event.refresh_from_db()
        self.assertTrue(self.event.winner_frozen)
        self.assertEqual(self.event.winning_location_id, self.cafe.id)

    def test_already_frozen_events_are_not_revisited(self):
        self._start_event_now()
        self.assertEqual(freeze_due_winners(), 1)
        self.assertEqual(freeze_due_winners(), 0)


class EventDeleteLockTests(APITestCase):
    """The 'no deleting an event close to its start' rule, implemented in Phase 4."""

    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="pw12345678")
        self.member = User.objects.create_user(username="member", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.creator)
        GroupMember.objects.create(group=self.group, user=self.creator, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def _event(self, starts_in_minutes):
        now = timezone.now()
        return Event.objects.create(
            created_by=self.creator, group=self.group, title="E",
            start_time=now + timedelta(minutes=starts_in_minutes),
            end_time=now + timedelta(minutes=starts_in_minutes + 120),
        )

    def test_an_event_far_from_starting_can_be_deleted(self):
        event = self._event(starts_in_minutes=180)
        self.client.force_authenticate(self.creator)
        resp = self.client.delete(f"/events/{event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())

    def test_an_event_starting_within_the_hour_cannot_be_deleted(self):
        event = self._event(starts_in_minutes=30)
        self.client.force_authenticate(self.creator)
        resp = self.client.delete(f"/events/{event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "event_starting_soon")
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    def test_an_event_already_started_cannot_be_deleted(self):
        event = self._event(starts_in_minutes=-30)
        self.client.force_authenticate(self.creator)
        resp = self.client.delete(f"/events/{event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "event_starting_soon")

    def test_the_lock_window_is_configurable(self):
        event = self._event(starts_in_minutes=90)
        self.client.force_authenticate(self.creator)
        with override_settings(EVENT_DELETE_LOCK_MINUTES=120):
            resp = self.client.delete(f"/events/{event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_non_creator_is_still_refused_before_the_lock_is_considered(self):
        event = self._event(starts_in_minutes=180)
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/events/{event.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())


class EventReminderTests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="pw12345678")
        self.member = User.objects.create_user(username="member", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.creator)
        GroupMember.objects.create(group=self.group, user=self.creator, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def _event(self, starts_in_minutes):
        now = timezone.now()
        return Event.objects.create(
            created_by=self.creator, group=self.group, title="E",
            start_time=now + timedelta(minutes=starts_in_minutes),
            end_time=now + timedelta(minutes=starts_in_minutes + 120),
        )

    def test_an_event_inside_the_lead_window_reminds_every_member(self):
        event = self._event(starts_in_minutes=30)
        self.assertEqual(send_due_reminders(), 1)

        recipients = set(
            Notification.objects.filter(kind="event_reminder")
            .values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.creator.id, self.member.id})

        event.refresh_from_db()
        self.assertTrue(event.reminder_sent)

    def test_an_event_beyond_the_lead_window_is_not_reminded(self):
        self._event(starts_in_minutes=180)
        self.assertEqual(send_due_reminders(), 0)
        self.assertFalse(Notification.objects.exists())

    def test_an_event_that_already_started_is_not_reminded(self):
        self._event(starts_in_minutes=-10)
        self.assertEqual(send_due_reminders(), 0)
        self.assertFalse(Notification.objects.exists())

    def test_reminders_are_sent_only_once(self):
        self._event(starts_in_minutes=30)
        self.assertEqual(send_due_reminders(), 1)
        self.assertEqual(send_due_reminders(), 0)
        self.assertEqual(
            Notification.objects.filter(kind="event_reminder").count(), 2
        )

    def test_the_lead_window_is_configurable(self):
        self._event(starts_in_minutes=180)
        with override_settings(EVENT_REMINDER_LEAD_MINUTES=240):
            self.assertEqual(send_due_reminders(), 1)

    def test_reminding_a_missing_event_returns_none(self):
        self.assertIsNone(send_reminder(999999))


class EventRoomMessageTests(APITestCase):
    """Voting and event actions write structured system rows into the group room."""

    def setUp(self):
        self.me = User.objects.create_user(username="roomer", password="pw12345678")
        self.mate = User.objects.create_user(username="roommate", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.me)
        GroupMember.objects.create(group=self.group, user=self.me, role="admin")
        GroupMember.objects.create(group=self.group, user=self.mate, role="member")

    def _events(self):
        return {
            m.payload["event"]: m
            for m in Message.objects.filter(group=self.group, kind="system")
        }

    def _event_with_locations(self):
        event = Event.objects.create(
            created_by=self.me, group=self.group, title="E",
            start_time=_future(), end_time=_future(hours=2),
        )
        cafe = EventLocation.objects.create(
            event=event, proposed_by=self.me, name="Cafe", latitude=1.0, longitude=2.0,
        )
        return event, cafe

    def test_creating_an_event_writes_event_created(self):
        self.client.force_authenticate(self.me)
        self.client.post("/events/", {
            "group_id": self.group.id, "title": "Meetup",
            "start_time": _future().isoformat(),
            "end_time": _future(hours=2).isoformat(),
        })
        message = self._events()["event_created"]
        self.assertEqual(message.payload["target"], "Meetup")
        self.assertEqual(message.payload["actor_id"], self.me.id)

    def test_proposing_a_location_writes_location_proposed(self):
        event, _ = self._event_with_locations()
        self.client.force_authenticate(self.mate)
        self.client.post("/event-locations/", {
            "event_id": event.id, "name": "Diner", "latitude": 3.0, "longitude": 4.0,
        })
        message = self._events()["location_proposed"]
        self.assertEqual(message.payload["target"], "Diner")
        self.assertEqual(message.payload["actor_id"], self.mate.id)

    def test_voting_writes_vote_cast_and_moving_writes_another(self):
        event, cafe = self._event_with_locations()
        diner = EventLocation.objects.create(
            event=event, proposed_by=self.mate, name="Diner", latitude=3.0, longitude=4.0,
        )
        self.client.force_authenticate(self.me)
        self.client.post(f"/event-locations/{cafe.id}/vote/")
        self.client.post(f"/event-locations/{diner.id}/vote/")

        cast = Message.objects.filter(kind="system", payload__event="vote_cast")
        self.assertEqual(cast.count(), 2)
        self.assertEqual(
            sorted(m.payload["target"] for m in cast), ["Cafe", "Diner"]
        )

    def test_freezing_a_winner_writes_voting_closed(self):
        event, cafe = self._event_with_locations()
        LocationVote.objects.create(location=cafe, voted_by=self.me)
        freeze_winner(event.id)

        message = self._events()["voting_closed"]
        self.assertEqual(message.payload["target"], "Cafe")
        self.assertIn("Cafe", message.body)

    def test_freezing_with_no_votes_still_writes_voting_closed(self):
        event, _ = self._event_with_locations()
        freeze_winner(event.id)

        message = self._events()["voting_closed"]
        self.assertIsNone(message.payload["target"])

    def test_a_refused_vote_writes_nothing(self):
        outsider = User.objects.create_user(username="outsideroom", password="pw12345678")
        _, cafe = self._event_with_locations()
        self.client.force_authenticate(outsider)
        self.client.post(f"/event-locations/{cafe.id}/vote/")
        self.assertFalse(
            Message.objects.filter(payload__event="vote_cast").exists()
        )

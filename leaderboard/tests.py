from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from checkins.models import CheckIn
from events.models import Event, EventLocation
from groups.models import Group, GroupMember

User = get_user_model()

# Create your tests here.


class LeaderboardBaseTests(APITestCase):
    def _make_group(self, name, users):
        group = Group.objects.create(name=name, created_by=users[0])
        for index, user in enumerate(users):
            GroupMember.objects.create(
                group=group, user=user, role="admin" if index == 0 else "member",
            )
        return group

    def _make_event(self, group, with_winner=True):
        now = timezone.now()
        event = Event.objects.create(
            created_by=group.created_by, group=group, title="E",
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1),
        )
        if with_winner:
            location = EventLocation.objects.create(
                event=event, proposed_by=group.created_by,
                name="Cafe", latitude=30.0, longitude=31.0,
            )
            Event.objects.filter(pk=event.pk).update(
                winning_location=location, winner_frozen=True
            )
            event.refresh_from_db()
        return event

    def _check_in(self, event, user, valid=True):
        return CheckIn.objects.create(
            event=event, user=user, latitude=30.0, longitude=31.0, is_valid=valid,
        )


class GroupMemberBoardTests(LeaderboardBaseTests):
    def setUp(self):
        self.a = User.objects.create_user(username="a", password="pw12345678")
        self.b = User.objects.create_user(username="b", password="pw12345678")
        self.c = User.objects.create_user(username="c", password="pw12345678")
        self.outsider = User.objects.create_user(username="out", password="pw12345678")
        self.group = self._make_group("G", [self.a, self.b, self.c])

        self.e1 = self._make_event(self.group)
        self.e2 = self._make_event(self.group)

        self._check_in(self.e1, self.a)
        self._check_in(self.e2, self.a)
        self._check_in(self.e1, self.b)

    def test_members_are_ranked_by_valid_check_ins(self):
        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(row["user"]["username"], row["checkins"], row["rank"])
             for row in resp.data["standings"]],
            [("a", 2, 1), ("b", 1, 2), ("c", 0, 3)],
        )

    def test_invalid_check_ins_do_not_count(self):
        self._check_in(self.e2, self.c, valid=False)
        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        scores = {row["user"]["username"]: row["checkins"] for row in resp.data["standings"]}
        self.assertEqual(scores["c"], 0)

    def test_ties_share_a_rank_and_the_next_rank_is_skipped(self):
        self._check_in(self.e2, self.b)
        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        self.assertEqual(
            [(row["user"]["username"], row["checkins"], row["rank"])
             for row in resp.data["standings"]],
            [("a", 2, 1), ("b", 2, 1), ("c", 0, 3)],
        )

    def test_check_ins_in_another_group_do_not_count(self):
        other_group = self._make_group("Other", [self.c])
        other_event = self._make_event(other_group)
        self._check_in(other_event, self.c)

        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        scores = {row["user"]["username"]: row["checkins"] for row in resp.data["standings"]}
        self.assertEqual(scores["c"], 0)

    def test_the_board_never_exposes_an_email(self):
        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        for row in resp.data["standings"]:
            self.assertNotIn("email", row["user"])

    def test_a_non_member_is_refused(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "group_not_found")

    def test_a_non_member_cannot_tell_a_real_group_from_a_missing_one(self):
        self.client.force_authenticate(self.outsider)
        real = self.client.get(f"/leaderboard/?group={self.group.id}")
        missing = self.client.get(f"/leaderboard/?group={self.group.id + 999}")
        self.assertEqual(real.status_code, missing.status_code)
        self.assertEqual(real.data["code"], missing.data["code"])

    def test_an_unknown_group_is_404(self):
        self.client.force_authenticate(self.a)
        resp = self.client.get(f"/leaderboard/?group={self.group.id + 999}")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "group_not_found")

    def test_a_missing_group_parameter_is_400(self):
        self.client.force_authenticate(self.a)
        resp = self.client.get("/leaderboard/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "missing_field")

    def test_a_non_numeric_group_parameter_is_400_not_500(self):
        self.client.force_authenticate(self.a)
        resp = self.client.get("/leaderboard/?group=abc")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_is_refused(self):
        resp = self.client.get(f"/leaderboard/?group={self.group.id}")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class UserBoardTests(LeaderboardBaseTests):
    def setUp(self):
        self.a = User.objects.create_user(username="a", password="pw12345678")
        self.b = User.objects.create_user(username="b", password="pw12345678")
        self.idle = User.objects.create_user(username="idle", password="pw12345678")

        self.g1 = self._make_group("G1", [self.a, self.b])
        self.g2 = self._make_group("G2", [self.a])

        self._check_in(self._make_event(self.g1), self.a)
        self._check_in(self._make_event(self.g2), self.a)
        self._check_in(self._make_event(self.g1), self.b)

    def test_totals_span_every_group(self):
        self.client.force_authenticate(self.b)
        resp = self.client.get("/leaderboard/users/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(row["user"]["username"], row["checkins"]) for row in resp.data["standings"]],
            [("a", 2), ("b", 1)],
        )

    def test_users_with_no_valid_check_ins_are_absent(self):
        self.client.force_authenticate(self.b)
        resp = self.client.get("/leaderboard/users/")
        usernames = [row["user"]["username"] for row in resp.data["standings"]]
        self.assertNotIn("idle", usernames)

    def test_invalid_check_ins_do_not_count(self):
        self._check_in(self._make_event(self.g1), self.idle, valid=False)
        self.client.force_authenticate(self.b)
        resp = self.client.get("/leaderboard/users/")
        usernames = [row["user"]["username"] for row in resp.data["standings"]]
        self.assertNotIn("idle", usernames)

    def test_unauthenticated_is_refused(self):
        resp = self.client.get("/leaderboard/users/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(LEADERBOARD_MIN_EVENTS=1)
class GroupBoardTests(LeaderboardBaseTests):
    def setUp(self):
        self.users = [
            User.objects.create_user(username=f"u{i}", password="pw12345678")
            for i in range(6)
        ]

    def test_a_small_committed_group_beats_a_large_flaky_one(self):
        tight = self._make_group("Tight", self.users[:2])
        loose = self._make_group("Loose", self.users[2:6])

        tight_event = self._make_event(tight)
        for user in self.users[:2]:
            self._check_in(tight_event, user)

        loose_event = self._make_event(loose)
        self._check_in(loose_event, self.users[2])

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        rows = {row["group"]["name"]: row for row in resp.data["standings"]}

        self.assertEqual(rows["Tight"]["rate"], 1.0)
        self.assertEqual(rows["Loose"]["rate"], 0.25)
        self.assertEqual(rows["Tight"]["rank"], 1)
        self.assertEqual(rows["Loose"]["rank"], 2)

    def test_the_rate_divides_by_members_times_events(self):
        group = self._make_group("G", self.users[:3])
        first = self._make_event(group)
        self._make_event(group)

        self._check_in(first, self.users[0])
        self._check_in(first, self.users[1])
        self._check_in(first, self.users[2])

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        row = resp.data["standings"][0]
        self.assertEqual(row["members"], 3)
        self.assertEqual(row["events"], 2)
        self.assertEqual(row["checkins"], 3)
        self.assertEqual(row["rate"], 0.5)

    def test_member_count_breaks_a_rate_tie(self):
        big = self._make_group("Big", self.users[:4])
        small = self._make_group("Small", self.users[4:6])

        big_event = self._make_event(big)
        for user in self.users[:4]:
            self._check_in(big_event, user)

        small_event = self._make_event(small)
        for user in self.users[4:6]:
            self._check_in(small_event, user)

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        names = [row["group"]["name"] for row in resp.data["standings"]]
        self.assertEqual(names, ["Big", "Small"])
        self.assertEqual([row["rank"] for row in resp.data["standings"]], [1, 2])

    def test_a_group_with_no_eligible_events_is_absent(self):
        self._make_group("Empty", self.users[:2])
        scored = self._make_group("Scored", self.users[2:4])
        self._check_in(self._make_event(scored), self.users[2])

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        names = [row["group"]["name"] for row in resp.data["standings"]]
        self.assertEqual(names, ["Scored"])

    def test_an_event_that_never_got_a_winner_is_not_counted(self):
        group = self._make_group("G", self.users[:2])
        self._make_event(group, with_winner=False)
        winning_event = self._make_event(group)
        self._check_in(winning_event, self.users[0])
        self._check_in(winning_event, self.users[1])

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        row = resp.data["standings"][0]
        self.assertEqual(row["events"], 1)
        self.assertEqual(row["rate"], 1.0)

    def test_invalid_check_ins_do_not_count(self):
        group = self._make_group("G", self.users[:2])
        event = self._make_event(group)
        self._check_in(event, self.users[0], valid=True)
        self._check_in(event, self.users[1], valid=False)

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        row = resp.data["standings"][0]
        self.assertEqual(row["checkins"], 1)
        self.assertEqual(row["rate"], 0.5)

    def test_unauthenticated_is_refused(self):
        resp = self.client.get("/leaderboard/groups/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class GroupBoardThresholdTests(LeaderboardBaseTests):
    """A rate is fragile at small n: without a minimum, one perfect event tops
    the board forever."""

    def setUp(self):
        self.users = [
            User.objects.create_user(username=f"t{i}", password="pw12345678")
            for i in range(4)
        ]

    def _group_with(self, name, users, event_count, checkins_per_event):
        group = self._make_group(name, users)
        for _ in range(event_count):
            event = self._make_event(group)
            for user in users[:checkins_per_event]:
                self._check_in(event, user)
        return group

    def test_a_group_below_the_minimum_is_unranked(self):
        self._group_with("Fluke", self.users[:2], event_count=1, checkins_per_event=2)
        self._group_with("Steady", self.users[2:4], event_count=3, checkins_per_event=1)

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        names = [row["group"]["name"] for row in resp.data["standings"]]
        self.assertEqual(names, ["Steady"])

    def test_a_perfect_one_off_no_longer_outranks_a_long_record(self):
        self._group_with("Fluke", self.users[:2], event_count=1, checkins_per_event=2)
        self._group_with("Steady", self.users[2:4], event_count=4, checkins_per_event=2)

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        top = resp.data["standings"][0]
        self.assertEqual(top["group"]["name"], "Steady")
        self.assertEqual(top["rate"], 1.0)

    def test_reaching_the_minimum_puts_a_group_on_the_board(self):
        group = self._group_with("Rising", self.users[:2], event_count=2, checkins_per_event=2)

        self.client.force_authenticate(self.users[0])
        before = self.client.get("/leaderboard/groups/")
        self.assertEqual(list(before.data["standings"]), [])

        third = self._make_event(group)
        self._check_in(third, self.users[0])
        after = self.client.get("/leaderboard/groups/")
        self.assertEqual(
            [row["group"]["name"] for row in after.data["standings"]], ["Rising"]
        )

    def test_the_minimum_is_configurable(self):
        self._group_with("Fluke", self.users[:2], event_count=1, checkins_per_event=2)

        self.client.force_authenticate(self.users[0])
        with override_settings(LEADERBOARD_MIN_EVENTS=1):
            resp = self.client.get("/leaderboard/groups/")
        self.assertEqual(
            [row["group"]["name"] for row in resp.data["standings"]], ["Fluke"]
        )

    def test_events_without_a_winner_do_not_count_toward_the_minimum(self):
        group = self._make_group("Talkers", self.users[:2])
        for _ in range(5):
            self._make_event(group, with_winner=False)

        self.client.force_authenticate(self.users[0])
        resp = self.client.get("/leaderboard/groups/")
        self.assertEqual(list(resp.data["standings"]), [])

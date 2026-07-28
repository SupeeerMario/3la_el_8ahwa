from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from checkins.models import CheckIn
from core.geo import haversine_meters
from events.models import Event, EventLocation
from groups.models import Group, GroupMember

User = get_user_model()

CAFE_LAT = 30.0444
CAFE_LNG = 31.2357
NEARBY_LAT = CAFE_LAT + 0.0005
FAR_LAT = CAFE_LAT + 0.01

# Create your tests here.


class HaversineTests(APITestCase):
    """The distance helper is what every is_valid decision rests on."""

    def test_identical_points_are_zero_apart(self):
        self.assertEqual(haversine_meters(CAFE_LAT, CAFE_LNG, CAFE_LAT, CAFE_LNG), 0)

    def test_half_a_milli_degree_of_latitude_is_about_55_metres(self):
        distance = haversine_meters(CAFE_LAT, CAFE_LNG, NEARBY_LAT, CAFE_LNG)
        self.assertAlmostEqual(distance, 55.6, delta=1.0)

    def test_a_hundredth_of_a_degree_of_latitude_is_about_1100_metres(self):
        distance = haversine_meters(CAFE_LAT, CAFE_LNG, FAR_LAT, CAFE_LNG)
        self.assertAlmostEqual(distance, 1112.0, delta=5.0)

    def test_distance_is_symmetric(self):
        there = haversine_meters(CAFE_LAT, CAFE_LNG, FAR_LAT, CAFE_LNG + 0.01)
        back = haversine_meters(FAR_LAT, CAFE_LNG + 0.01, CAFE_LAT, CAFE_LNG)
        self.assertAlmostEqual(there, back, places=6)


class CheckInBaseTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username="m1", password="pw12345678")
        self.other = User.objects.create_user(username="m2", password="pw12345678")
        self.outsider = User.objects.create_user(username="out", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.member)
        GroupMember.objects.create(group=self.group, user=self.member, role="admin")
        GroupMember.objects.create(group=self.group, user=self.other, role="member")

        self.event = self._make_event()
        self.cafe = EventLocation.objects.create(
            event=self.event, proposed_by=self.member,
            name="Cafe", latitude=CAFE_LAT, longitude=CAFE_LNG,
        )
        Event.objects.filter(pk=self.event.pk).update(
            winning_location=self.cafe, winner_frozen=True
        )
        self.event.refresh_from_db()

    def _make_event(self, starts_in=-1, ends_in=2):
        now = timezone.now()
        return Event.objects.create(
            created_by=self.member, group=self.group, title="E",
            start_time=now + timedelta(hours=starts_in),
            end_time=now + timedelta(hours=ends_in),
        )

    def _payload(self, lat=NEARBY_LAT, lng=CAFE_LNG, **over):
        data = {"event_id": self.event.id, "latitude": lat, "longitude": lng}
        data.update(over)
        return data


class CheckInCreateTests(CheckInBaseTests):
    def test_member_inside_the_radius_checks_in_valid(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["checkin"]["is_valid"])
        self.assertEqual(resp.data["radius_m"], 200)
        self.assertLess(resp.data["distance_m"], 200)
        self.assertTrue(CheckIn.objects.get(user=self.member).is_valid)

    def test_member_outside_the_radius_is_recorded_but_not_valid(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload(lat=FAR_LAT))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertFalse(resp.data["checkin"]["is_valid"])
        self.assertGreater(resp.data["distance_m"], 200)
        self.assertFalse(CheckIn.objects.get(user=self.member).is_valid)

    def test_an_invalid_check_in_can_be_retried_closer(self):
        self.client.force_authenticate(self.member)
        first = self.client.post("/checkins/", self._payload(lat=FAR_LAT))
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post("/checkins/", self._payload())
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data["checkin"]["is_valid"])
        self.assertEqual(second.data["checkin"]["id"], first.data["checkin"]["id"])
        self.assertEqual(CheckIn.objects.filter(user=self.member).count(), 1)

    def test_a_valid_check_in_cannot_be_repeated(self):
        self.client.force_authenticate(self.member)
        self.client.post("/checkins/", self._payload())
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "already_checked_in")

    def test_a_valid_check_in_cannot_be_downgraded_by_moving_away(self):
        self.client.force_authenticate(self.member)
        self.client.post("/checkins/", self._payload())
        resp = self.client.post("/checkins/", self._payload(lat=FAR_LAT))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(CheckIn.objects.get(user=self.member).is_valid)

    @override_settings(CHECKIN_RADIUS_METERS=2000)
    def test_the_radius_setting_is_honoured(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload(lat=FAR_LAT))
        self.assertEqual(resp.data["radius_m"], 2000)
        self.assertTrue(resp.data["checkin"]["is_valid"])

    def test_unauthenticated_cannot_check_in(self):
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(CheckIn.objects.exists())

    def test_non_member_cannot_check_in(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "not_a_member")
        self.assertFalse(CheckIn.objects.exists())

    def test_unknown_event_is_404(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload(event_id=self.event.id + 999))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "event_not_found")

    def test_non_numeric_event_id_is_404_not_500(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload(event_id="abc"))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "event_not_found")

    def test_missing_coordinates_are_rejected(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", {"event_id": self.event.id})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "validation_error")

    def test_one_check_in_per_event_and_user_is_enforced_by_the_database(self):
        CheckIn.objects.create(
            event=self.event, user=self.member, latitude=CAFE_LAT, longitude=CAFE_LNG,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CheckIn.objects.create(
                    event=self.event, user=self.member,
                    latitude=CAFE_LAT, longitude=CAFE_LNG,
                )


class CheckInEventStateTests(CheckInBaseTests):
    def test_checking_in_before_the_event_starts_is_rejected(self):
        Event.objects.filter(pk=self.event.pk).update(
            start_time=timezone.now() + timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=3),
        )
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "event_not_active")

    def test_checking_in_after_the_event_ends_is_rejected(self):
        Event.objects.filter(pk=self.event.pk).update(
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=1),
        )
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "event_not_active")

    def test_an_event_with_no_winning_location_cannot_be_checked_in_to(self):
        Event.objects.filter(pk=self.event.pk).update(winning_location=None)
        self.client.force_authenticate(self.member)
        resp = self.client.post("/checkins/", self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "no_winning_location")
        self.assertFalse(CheckIn.objects.exists())


class CheckInReadTests(CheckInBaseTests):
    def setUp(self):
        super().setUp()
        self.mine = CheckIn.objects.create(
            event=self.event, user=self.member,
            latitude=NEARBY_LAT, longitude=CAFE_LNG, is_valid=True,
        )
        self.theirs = CheckIn.objects.create(
            event=self.event, user=self.other,
            latitude=FAR_LAT, longitude=CAFE_LNG, is_valid=False,
        )

    def test_listing_without_an_event_returns_only_my_check_ins(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/checkins/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in resp.data], [self.mine.id])

    def test_listing_by_event_returns_the_whole_roster(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/checkins/?event={self.event.id}")
        self.assertEqual(
            sorted(row["id"] for row in resp.data),
            sorted([self.mine.id, self.theirs.id]),
        )

    def test_the_roster_never_exposes_an_email(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/checkins/?event={self.event.id}")
        for row in resp.data:
            self.assertNotIn("email", row["user"])

    def test_a_non_member_sees_nothing(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/checkins/?event={self.event.id}")
        self.assertEqual(list(resp.data), [])

    def test_a_non_member_cannot_retrieve_a_check_in(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/checkins/{self.mine.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_member_can_retrieve_without_a_query_param(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/checkins/{self.theirs.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["user"]["username"], "m2")

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get("/checkins/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_numeric_check_in_id_is_404(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/checkins/abc/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_check_ins_are_not_deletable(self):
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/checkins/{self.mine.id}/")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

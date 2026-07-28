from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from events.models import Event
from groups.models import Group, GroupInvitaion, GroupInviteToken, GroupMember
from notifications.models import Notification

User = get_user_model()

# Create your tests here.


def _future(hours=0):
    return timezone.now() + timedelta(days=1, hours=hours)


class NotificationTriggerTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="pw12345678")
        self.member = User.objects.create_user(username="member", password="pw12345678")
        self.newcomer = User.objects.create_user(username="newcomer", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def test_sending_an_invite_notifies_the_invited_user(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post("/groups/invitations/send_invite/", {
            "group_id": self.group.id, "username_to_invite": "newcomer",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        notification = Notification.objects.get(user=self.newcomer)
        self.assertEqual(notification.notification_type, "group_invite")
        self.assertEqual(notification.payload["group_id"], self.group.id)
        self.assertEqual(notification.payload["invited_by_username"], "admin")
        self.assertFalse(notification.is_read)

    def test_accepting_an_invite_notifies_the_inviter(self):
        invitation = GroupInvitaion.objects.create(
            group=self.group, invited_user=self.newcomer,
            invited_by=self.admin, status="pending",
        )
        self.client.force_authenticate(self.newcomer)
        resp = self.client.post(f"/groups/invitations/{invitation.id}/invite_responce/", {"action": "accept"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        notification = Notification.objects.get(
            user=self.admin, notification_type="invite_accepted"
        )
        self.assertEqual(notification.payload["username"], "newcomer")

    def test_joining_by_token_notifies_existing_members_but_not_the_joiner(self):
        token = GroupInviteToken.objects.create(
            group=self.group, created_by=self.admin,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_authenticate(self.newcomer)
        resp = self.client.post("/groups/join/", {"token": str(token.token)})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        recipients = set(
            Notification.objects.filter(notification_type="new_member")
            .values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.admin.id, self.member.id})

    def test_creating_an_event_notifies_the_group_except_the_creator(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post("/events/", {
            "group_id": self.group.id,
            "title": "Meetup",
            "start_time": _future().isoformat(),
            "end_time": _future(hours=2).isoformat(),
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        recipients = set(
            Notification.objects.filter(notification_type="new_event")
            .values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.member.id})

        payload = Notification.objects.get(notification_type="new_event").payload
        self.assertEqual(payload["event_title"], "Meetup")
        self.assertEqual(payload["group_id"], self.group.id)

    def test_a_failed_invite_creates_no_notification(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post("/groups/invitations/send_invite/", {
            "group_id": self.group.id, "username_to_invite": "newcomer",
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Notification.objects.exists())


class NotificationReadTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u1", password="pw12345678")
        self.other = User.objects.create_user(username="u2", password="pw12345678")
        self.mine = Notification.objects.create(
            user=self.user, notification_type="new_event", payload={"event_id": 1},
        )
        self.also_mine = Notification.objects.create(
            user=self.user, notification_type="new_member", payload={"group_id": 1},
        )
        self.theirs = Notification.objects.create(
            user=self.other, notification_type="new_event", payload={"event_id": 2},
        )

    def test_listing_returns_only_my_notifications(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/notifications/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            sorted(row["id"] for row in resp.data),
            sorted([self.mine.id, self.also_mine.id]),
        )

    def test_unread_filter(self):
        Notification.objects.filter(pk=self.mine.pk).update(is_read=True)
        self.client.force_authenticate(self.user)
        resp = self.client.get("/notifications/?unread=true")
        self.assertEqual([row["id"] for row in resp.data], [self.also_mine.id])

    def test_unread_count(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/notifications/unread_count/")
        self.assertEqual(resp.data["unread"], 2)

    def test_marking_one_read(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(f"/notifications/{self.mine.id}/read/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_read"])
        self.mine.refresh_from_db()
        self.assertTrue(self.mine.is_read)
        self.also_mine.refresh_from_db()
        self.assertFalse(self.also_mine.is_read)

    def test_marking_all_read(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/notifications/read_all/")
        self.assertEqual(resp.data["marked_read"], 2)
        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(), 0
        )
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)

    def test_cannot_mark_another_users_notification_read(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(f"/notifications/{self.theirs.id}/read/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)

    def test_cannot_retrieve_another_users_notification(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get(f"/notifications/{self.theirs.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get("/notifications/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_notifications_are_not_deletable(self):
        self.client.force_authenticate(self.user)
        resp = self.client.delete(f"/notifications/{self.mine.id}/")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_non_numeric_id_is_404(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/notifications/abc/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

from groups.models import Group, GroupMember, GroupInvitaion

User = get_user_model()


class GroupCreateTests(APITestCase):
    """Locks in the perform_create fix: creating a group must succeed and make
    the creator an admin member."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin1", password="pw12345678")

    def test_create_group_makes_creator_an_admin_member(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post("/groups/", {"name": "Coffee Crew", "desc": "x"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        group = Group.objects.get(name="Coffee Crew")
        self.assertEqual(group.created_by, self.admin)
        self.assertTrue(
            GroupMember.objects.filter(group=group, user=self.admin, role="admin").exists()
        )


class GroupAdminPermissionTests(APITestCase):
    """Locks in the admin enforcement on the default update/destroy routes."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin2", password="pw12345678")
        self.outsider = User.objects.create_user(username="outsider", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")

    def test_non_admin_cannot_update_group(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.patch(f"/groups/{self.group.id}/", {"name": "Hacked"})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "G")

    def test_non_admin_cannot_delete_group(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.delete(f"/groups/{self.group.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())

    def test_admin_can_update_group(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(f"/groups/{self.group.id}/", {"name": "Renamed"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Renamed")

    def test_admin_can_delete_group(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f"/groups/{self.group.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Group.objects.filter(id=self.group.id).exists())


class GroupCustomActionTests(APITestCase):
    """Covers the custom @action routes: my_groups, list_group_members,
    update_group and delete_group."""

    def setUp(self):
        self.admin = User.objects.create_user(username="admin3", password="pw12345678")
        self.member = User.objects.create_user(username="member3", password="pw12345678")
        self.outsider = User.objects.create_user(username="outsider3", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def test_my_groups_lists_only_membership_groups(self):
        Group.objects.create(name="Other", created_by=self.outsider)
        self.client.force_authenticate(self.member)
        resp = self.client.get("/groups/my_groups/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [g["name"] for g in resp.data]
        self.assertEqual(names, ["G"])

    def test_list_group_members_for_member(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/groups/{self.group.id}/list_group_members/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["members"]), 2)

    def test_list_group_members_rejects_non_member(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/groups/{self.group.id}/list_group_members/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_group_action_admin_only(self):
        self.client.force_authenticate(self.member)
        denied = self.client.patch(f"/groups/{self.group.id}/update_group/", {"name": "X"})
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.admin)
        ok = self.client.patch(f"/groups/{self.group.id}/update_group/", {"name": "Renamed"})
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Renamed")

    def test_delete_group_action_admin_only(self):
        self.client.force_authenticate(self.member)
        denied = self.client.delete(f"/groups/{self.group.id}/delete_group/")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.admin)
        ok = self.client.delete(f"/groups/{self.group.id}/delete_group/")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertFalse(Group.objects.filter(id=self.group.id).exists())


class GroupLeaveTests(APITestCase):
    """Covers leave_group, including the owner-transfer gap fix."""

    def setUp(self):
        self.admin = User.objects.create_user(username="adminL", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        self.admin_membership = GroupMember.objects.create(
            group=self.group, user=self.admin, role="admin",
        )

    def test_regular_member_leaving_keeps_group(self):
        member = User.objects.create_user(username="memberL", password="pw12345678")
        GroupMember.objects.create(group=self.group, user=member, role="member")
        self.client.force_authenticate(member)
        resp = self.client.delete(f"/groups/{self.group.id}/leave_group/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())
        self.assertFalse(
            GroupMember.objects.filter(group=self.group, user=member).exists()
        )

    def test_last_member_leaving_deletes_group(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f"/groups/{self.group.id}/leave_group/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Group.objects.filter(id=self.group.id).exists())

    def test_last_admin_leaving_transfers_admin_to_latest_member(self):
        first = User.objects.create_user(username="firstL", password="pw12345678")
        latest = User.objects.create_user(username="latestL", password="pw12345678")
        GroupMember.objects.create(group=self.group, user=first, role="member")
        latest_membership = GroupMember.objects.create(
            group=self.group, user=latest, role="member",
        )

        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f"/groups/{self.group.id}/leave_group/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.assertTrue(Group.objects.filter(id=self.group.id).exists())
        self.assertFalse(
            GroupMember.objects.filter(group=self.group, user=self.admin).exists()
        )
        latest_membership.refresh_from_db()
        self.assertEqual(latest_membership.role, "admin")
        # exactly one admin remains
        self.assertEqual(
            GroupMember.objects.filter(group=self.group, role="admin").count(), 1
        )

    def test_leaving_a_group_you_are_not_in_is_rejected(self):
        stranger = User.objects.create_user(username="strangerL", password="pw12345678")
        self.client.force_authenticate(stranger)
        resp = self.client.delete(f"/groups/{self.group.id}/leave_group/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class GroupInvitationTests(APITestCase):
    """Covers the full invitation flow on GroupInvitationViewSet."""

    INVITES = "/groups/invitations"

    def setUp(self):
        self.admin = User.objects.create_user(username="adminI", password="pw12345678")
        self.invitee = User.objects.create_user(username="inviteeI", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")

    def _send_invite(self):
        self.client.force_authenticate(self.admin)
        return self.client.post(f"{self.INVITES}/send_invite/", {
            "group_id": self.group.id,
            "username_to_invite": self.invitee.username,
        })

    def test_admin_can_send_invite(self):
        resp = self._send_invite()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            GroupInvitaion.objects.filter(
                group=self.group, invited_user=self.invitee, status="pending"
            ).exists()
        )

    def test_non_admin_cannot_send_invite(self):
        member = User.objects.create_user(username="plainI", password="pw12345678")
        GroupMember.objects.create(group=self.group, user=member, role="member")
        self.client.force_authenticate(member)
        resp = self.client.post(f"{self.INVITES}/send_invite/", {
            "group_id": self.group.id,
            "username_to_invite": self.invitee.username,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invite_unknown_user_returns_404(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"{self.INVITES}/send_invite/", {
            "group_id": self.group.id,
            "username_to_invite": "does_not_exist",
        })
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_inviting_existing_member_returns_400(self):
        GroupMember.objects.create(group=self.group, user=self.invitee, role="member")
        resp = self._send_invite()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_pending_invite_returns_400(self):
        self._send_invite()
        resp = self._send_invite()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_show_all_invitations_lists_invitees_invites(self):
        self._send_invite()
        self.client.force_authenticate(self.invitee)
        resp = self.client.get(f"{self.INVITES}/show_all_invitations/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["invites"]), 1)

    def test_accept_invite_creates_membership_and_consumes_invite(self):
        self._send_invite()
        invite = GroupInvitaion.objects.get(invited_user=self.invitee)
        self.client.force_authenticate(self.invitee)
        resp = self.client.post(f"{self.INVITES}/{invite.id}/accept_invite/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(
            GroupMember.objects.filter(group=self.group, user=self.invitee).exists()
        )
        self.assertFalse(GroupInvitaion.objects.filter(id=invite.id).exists())

    def test_decline_invite_marks_rejected(self):
        self._send_invite()
        invite = GroupInvitaion.objects.get(invited_user=self.invitee)
        self.client.force_authenticate(self.invitee)
        resp = self.client.post(f"{self.INVITES}/{invite.id}/decline_invite/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        invite.refresh_from_db()
        self.assertEqual(invite.status, "rejected")

    def test_invite_responce_accept_dispatches(self):
        self._send_invite()
        invite = GroupInvitaion.objects.get(invited_user=self.invitee)
        self.client.force_authenticate(self.invitee)
        resp = self.client.post(
            f"{self.INVITES}/{invite.id}/invite_responce/", {"action": "accept"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(
            GroupMember.objects.filter(group=self.group, user=self.invitee).exists()
        )

    def test_invite_responce_rejects_invalid_action(self):
        self._send_invite()
        invite = GroupInvitaion.objects.get(invited_user=self.invitee)
        self.client.force_authenticate(self.invitee)
        resp = self.client.post(
            f"{self.INVITES}/{invite.id}/invite_responce/", {"action": "maybe"}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

from datetime import timedelta
from unittest.mock import patch

from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from groups.models import Group, GroupMember, GroupInvitaion, GroupInviteToken, Message

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
        self.member = User.objects.create_user(username="member2", password="pw12345678")
        self.outsider = User.objects.create_user(username="outsider", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def test_non_member_cannot_update_group(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.patch(f"/groups/{self.group.id}/", {"name": "Hacked"})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "G")

    def test_non_member_cannot_delete_group(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.delete(f"/groups/{self.group.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())

    def test_non_admin_member_cannot_update_group(self):
        self.client.force_authenticate(self.member)
        resp = self.client.patch(f"/groups/{self.group.id}/", {"name": "Hacked"})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "G")

    def test_non_admin_member_cannot_delete_group(self):
        self.client.force_authenticate(self.member)
        resp = self.client.delete(f"/groups/{self.group.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())

    def test_group_list_excludes_groups_the_user_is_not_in(self):
        Group.objects.create(name="Someone Else's", created_by=self.outsider)
        self.client.force_authenticate(self.member)
        resp = self.client.get("/groups/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual([g["name"] for g in resp.data], ["G"])

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
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

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
        self.assertEqual(ok.status_code, status.HTTP_204_NO_CONTENT)
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

    def test_forging_invitation_body_creates_no_invitation_row(self):
        """POST /groups/invitations/ with a forged, fully-populated body must
        never create a row, no matter what status code it gets back.

        This 405s because GroupInvitationViewSet is a ReadOnlyModelViewSet, so
        the router never wires up a create route at all. It used to 405 for a
        far weaker reason -- GroupsViewSet's ^(?P<pk>[^/.]+)/$ swallowed
        "invitations/" as a group pk -- which stopped being true once that
        lookup was restricted to digits. Asserting on DB state rather than the
        status code is the point: it stays meaningful whichever reason holds.
        """
        attacker = User.objects.create_user(username="attackerI", password="pw12345678")
        victim_group = Group.objects.create(name="Victim Group", created_by=self.admin)
        GroupMember.objects.create(group=victim_group, user=self.admin, role="admin")

        self.client.force_authenticate(attacker)
        self.client.post(f"{self.INVITES}/", {
            "group": victim_group.id,
            "invited_user": attacker.id,
            "invited_by": attacker.id,
            "status": "pending",
        })
        self.assertFalse(
            GroupInvitaion.objects.filter(group=victim_group, invited_user=attacker).exists()
        )

    def test_accept_invite_by_wrong_user_is_404_and_creates_no_membership(self):
        self._send_invite()
        invite = GroupInvitaion.objects.get(invited_user=self.invitee)
        stranger = User.objects.create_user(username="strangerI", password="pw12345678")
        self.client.force_authenticate(stranger)
        resp = self.client.post(f"{self.INVITES}/{invite.id}/accept_invite/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(
            GroupMember.objects.filter(group=self.group, user=stranger).exists()
        )


class PublicUserShapeTests(APITestCase):
    """No payload that shows one user to another may carry an email address."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="shapeadmin", email="shapeadmin@example.com", password="pw12345678"
        )
        self.member = User.objects.create_user(
            username="shapemember", email="shapemember@example.com", password="pw12345678"
        )
        self.group = Group.objects.create(name="Shape", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def test_roster_omits_member_emails(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/groups/{self.group.id}/list_group_members/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for row in resp.data["members"]:
            self.assertNotIn("email", row["user"])
        self.assertNotIn("shapeadmin@example.com", str(resp.data))

    def test_group_list_omits_the_creator_email(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/groups/")
        self.assertNotIn("email", resp.data[0]["created_by"])

    def test_roster_carries_display_name(self):
        self.admin.display_name = "Shape Admin"
        self.admin.save(update_fields=["display_name"])
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/groups/{self.group.id}/list_group_members/")
        names = [row["user"]["display_name"] for row in resp.data["members"]]
        self.assertIn("Shape Admin", names)


class InvitationPayloadTests(APITestCase):
    """The invite inbox has to be renderable from the payload alone: the
    invitee cannot read the group any other way."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="inviteradmin", email="ia@example.com", password="pw12345678"
        )
        self.admin.display_name = "Ahmed"
        self.admin.save(update_fields=["display_name"])
        self.invitee = User.objects.create_user(
            username="theinvitee", email="ti@example.com", password="pw12345678"
        )
        self.group = Group.objects.create(name="Coffee Crew", desc="beans", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        self.invite = GroupInvitaion.objects.create(
            group=self.group, invited_user=self.invitee, invited_by=self.admin
        )

    def test_invitation_nests_group_and_inviter(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/show_all_invitations/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payload = resp.data["invites"][0]
        self.assertEqual(payload["group"]["name"], "Coffee Crew")
        self.assertEqual(payload["group"]["desc"], "beans")
        self.assertEqual(payload["group"]["members_count"], 1)
        self.assertEqual(payload["invited_by"]["username"], "inviteradmin")
        self.assertEqual(payload["invited_by"]["display_name"], "Ahmed")

    def test_invitation_payload_leaks_no_email(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/show_all_invitations/")
        self.assertNotIn("ia@example.com", str(resp.data))

    def test_invitation_list_route_no_longer_errors(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_invitation_list_route_is_scoped_to_the_invitee(self):
        stranger = User.objects.create_user(username="strangerP", password="pw12345678")
        self.client.force_authenticate(stranger)
        resp = self.client.get("/groups/invitations/")
        self.assertEqual(resp.data, [])

    def test_non_numeric_invitation_id_is_not_a_500(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.post("/groups/invitations/abc/accept_invite/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_numeric_group_id_is_not_a_500(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get("/groups/abc/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class InvitationLifecycleTests(APITestCase):
    """show_all_invitations defaults to pending; declined invites are
    dismissable instead of accumulating forever."""

    def setUp(self):
        self.admin = User.objects.create_user(username="lifeadmin", password="pw12345678")
        self.invitee = User.objects.create_user(username="lifeinvitee", password="pw12345678")
        self.group = Group.objects.create(name="Life", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        self.invite = GroupInvitaion.objects.create(
            group=self.group, invited_user=self.invitee, invited_by=self.admin
        )

    def test_default_listing_hides_rejected_invites(self):
        self.invite.status = "rejected"
        self.invite.save(update_fields=["status"])
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/show_all_invitations/")
        self.assertEqual(resp.data["invites"], [])

    def test_status_all_shows_rejected_invites(self):
        self.invite.status = "rejected"
        self.invite.save(update_fields=["status"])
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/show_all_invitations/?status=all")
        self.assertEqual(len(resp.data["invites"]), 1)

    def test_unknown_status_filter_is_rejected(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/groups/invitations/show_all_invitations/?status=maybe")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dismiss_removes_a_rejected_invite(self):
        self.invite.status = "rejected"
        self.invite.save(update_fields=["status"])
        self.client.force_authenticate(self.invitee)
        resp = self.client.delete(f"/groups/invitations/{self.invite.id}/dismiss/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GroupInvitaion.objects.filter(id=self.invite.id).exists())

    def test_dismiss_refuses_a_pending_invite(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.delete(f"/groups/invitations/{self.invite.id}/dismiss/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invite_not_dismissable")

    def test_dismiss_by_another_user_is_404(self):
        self.invite.status = "rejected"
        self.invite.save(update_fields=["status"])
        stranger = User.objects.create_user(username="strangerD", password="pw12345678")
        self.client.force_authenticate(stranger)
        resp = self.client.delete(f"/groups/invitations/{self.invite.id}/dismiss/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(GroupInvitaion.objects.filter(id=self.invite.id).exists())

    def test_invite_responce_accepts_the_model_vocabulary(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.post(
            f"/groups/invitations/{self.invite.id}/invite_responce/",
            {"action": "rejected"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, "rejected")


class MembershipManagementTests(APITestCase):
    """Covers the admin-gated remove_member and change_role actions."""

    def setUp(self):
        self.admin = User.objects.create_user(username="mgmtadmin", password="pw12345678")
        self.member = User.objects.create_user(username="mgmtmember", password="pw12345678")
        self.outsider = User.objects.create_user(username="mgmtoutsider", password="pw12345678")
        self.group = Group.objects.create(name="Mgmt", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def _remove(self, user_id):
        return self.client.post(
            f"/groups/{self.group.id}/remove_member/", {"user_id": user_id}
        )

    def _change_role(self, user_id, role):
        return self.client.post(
            f"/groups/{self.group.id}/change_role/", {"user_id": user_id, "role": role}
        )

    def test_remove_member_requires_authentication(self):
        resp = self._remove(self.member.id)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_remove_a_member(self):
        self.client.force_authenticate(self.admin)
        resp = self._remove(self.member.id)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(
            GroupMember.objects.filter(group=self.group, user=self.member).exists()
        )

    def test_plain_member_cannot_remove_anyone(self):
        self.client.force_authenticate(self.member)
        resp = self._remove(self.admin.id)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            GroupMember.objects.filter(group=self.group, user=self.admin).exists()
        )

    def test_non_member_gets_404_not_403(self):
        self.client.force_authenticate(self.outsider)
        resp = self._remove(self.member.id)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_cannot_remove_themselves(self):
        self.client.force_authenticate(self.admin)
        resp = self._remove(self.admin.id)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "cannot_target_self")

    def test_removing_a_non_member_is_404(self):
        self.client.force_authenticate(self.admin)
        resp = self._remove(self.outsider.id)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "member_not_found")

    def test_non_numeric_user_id_is_a_400(self):
        self.client.force_authenticate(self.admin)
        resp = self._remove("abc")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_can_promote_a_member(self):
        self.client.force_authenticate(self.admin)
        resp = self._change_role(self.member.id, "admin")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["role"], "admin")

    def test_admin_can_demote_another_admin(self):
        GroupMember.objects.filter(group=self.group, user=self.member).update(role="admin")
        self.client.force_authenticate(self.admin)
        resp = self._change_role(self.member.id, "member")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["role"], "member")

    def test_the_last_admin_cannot_be_demoted(self):
        self.client.force_authenticate(self.admin)
        resp = self._change_role(self.admin.id, "member")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "last_admin")

    def test_unknown_role_is_rejected(self):
        self.client.force_authenticate(self.admin)
        resp = self._change_role(self.member.id, "superadmin")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invalid_role")

    def test_plain_member_cannot_promote_themselves(self):
        self.client.force_authenticate(self.member)
        resp = self._change_role(self.member.id, "admin")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            GroupMember.objects.get(group=self.group, user=self.member).role, "member"
        )


class InviteTokenTests(APITestCase):
    """Covers the invite-link join path: token creation, redemption and every
    way a token stops being usable."""

    def setUp(self):
        self.admin = User.objects.create_user(username="tokadmin", password="pw12345678")
        self.member = User.objects.create_user(username="tokmember", password="pw12345678")
        self.joiner = User.objects.create_user(username="tokjoiner", password="pw12345678")
        self.group = Group.objects.create(name="Tok", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def _create_token(self, **body):
        self.client.force_authenticate(self.admin)
        return self.client.post(f"/groups/{self.group.id}/invite_tokens/", body)

    def _join_with(self, token, as_user=None):
        self.client.force_authenticate(as_user or self.joiner)
        return self.client.post("/groups/join/", {"token": token})

    def test_admin_can_create_an_invite_token(self):
        resp = self._create_token()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["token"])
        self.assertEqual(resp.data["group"]["name"], "Tok")

    def test_plain_member_cannot_create_an_invite_token(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/groups/{self.group.id}/invite_tokens/", {})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_cannot_create_an_invite_token(self):
        self.client.force_authenticate(self.joiner)
        resp = self.client.post(f"/groups/{self.group.id}/invite_tokens/", {})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_join_requires_authentication(self):
        token = self._create_token().data["token"]
        self.client.force_authenticate(None)
        resp = self.client.post("/groups/join/", {"token": token})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_a_non_member_can_join_with_a_token(self):
        token = self._create_token().data["token"]
        resp = self._join_with(token)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            GroupMember.objects.filter(
                group=self.group, user=self.joiner, role="member"
            ).exists()
        )
        self.assertEqual(resp.data["group"]["name"], "Tok")

    def test_joining_twice_is_rejected(self):
        token = self._create_token().data["token"]
        self._join_with(token)
        resp = self._join_with(token)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "already_member")

    def test_join_consumes_a_use(self):
        created = self._create_token(max_uses=1)
        self._join_with(created.data["token"])
        token_row = GroupInviteToken.objects.get(id=created.data["id"])
        self.assertEqual(token_row.uses, 1)

    def test_an_exhausted_token_is_rejected(self):
        created = self._create_token(max_uses=1)
        self._join_with(created.data["token"])
        second = User.objects.create_user(username="tokjoiner2", password="pw12345678")
        resp = self._join_with(created.data["token"], as_user=second)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invite_token_exhausted")

    def test_an_expired_token_is_rejected(self):
        created = self._create_token()
        GroupInviteToken.objects.filter(id=created.data["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        resp = self._join_with(created.data["token"])
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invite_token_expired")

    def test_a_revoked_token_is_rejected(self):
        created = self._create_token()
        self.client.force_authenticate(self.admin)
        revoke = self.client.post(
            f"/groups/{self.group.id}/revoke_invite_token/",
            {"token_id": created.data["id"]},
        )
        self.assertEqual(revoke.status_code, status.HTTP_200_OK)
        resp = self._join_with(created.data["token"])
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invite_token_revoked")

    def test_an_unknown_token_is_404(self):
        resp = self._join_with("not-a-real-token")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["code"], "invite_token_not_found")

    def test_plain_member_cannot_revoke_a_token(self):
        created = self._create_token()
        self.client.force_authenticate(self.member)
        resp = self.client.post(
            f"/groups/{self.group.id}/revoke_invite_token/",
            {"token_id": created.data["id"]},
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_token_from_another_group_cannot_be_revoked(self):
        other_group = Group.objects.create(name="Other", created_by=self.admin)
        GroupMember.objects.create(group=other_group, user=self.admin, role="admin")
        created = self._create_token()
        resp = self.client.post(
            f"/groups/{other_group.id}/revoke_invite_token/",
            {"token_id": created.data["id"]},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_listing_tokens_hides_revoked_ones(self):
        created = self._create_token()
        self.client.post(
            f"/groups/{self.group.id}/revoke_invite_token/",
            {"token_id": created.data["id"]},
        )
        resp = self.client.get(f"/groups/{self.group.id}/invite_tokens/")
        self.assertEqual(resp.data["invite_tokens"], [])

    def test_joining_clears_a_pending_invitation_for_the_same_group(self):
        GroupInvitaion.objects.create(
            group=self.group, invited_user=self.joiner, invited_by=self.admin
        )
        token = self._create_token().data["token"]
        self._join_with(token)
        self.assertFalse(
            GroupInvitaion.objects.filter(
                group=self.group, invited_user=self.joiner
            ).exists()
        )

    def test_an_absurd_expiry_is_rejected(self):
        resp = self._create_token(expires_in_hours=100000)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class GroupImageTests(APITestCase):
    """Mirrors the avatar flow: signing and URL building run for real, only the
    destroy call — which touches the network — is patched."""

    def setUp(self):
        self.admin = User.objects.create_user(username="gadmin", password="pw12345678")
        self.member = User.objects.create_user(username="gmember", password="pw12345678")
        self.outsider = User.objects.create_user(username="gout", password="pw12345678")
        self.group = Group.objects.create(name="Crew", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")
        GroupMember.objects.create(group=self.group, user=self.member, role="member")

    def test_signature_pins_the_public_id_to_the_group(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"/groups/{self.group.id}/image_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["params"]["public_id"], f"groups/{self.group.id}")

    def test_a_plain_member_cannot_get_a_signature(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/groups/{self.group.id}/image_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_non_member_gets_404(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.post(f"/groups/{self.group.id}/image_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_is_refused(self):
        resp = self.client.post(f"/groups/{self.group.id}/image_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_signature_is_503_when_cloudinary_is_unconfigured(self):
        self.client.force_authenticate(self.admin)
        with override_settings(CLOUDINARY_URL=""):
            resp = self.client.post(f"/groups/{self.group.id}/image_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.data["code"], "avatar_storage_unconfigured")

    def test_confirming_a_version_publishes_an_image_url(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"/groups/{self.group.id}/image/", {"version": 1712345678})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data["image_url"])
        self.assertIn(f"groups/{self.group.id}", resp.data["image_url"])
        self.group.refresh_from_db()
        self.assertEqual(self.group.image_version, 1712345678)

    def test_a_plain_member_cannot_set_the_image(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/groups/{self.group.id}/image/", {"version": 1712345678})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.group.refresh_from_db()
        self.assertIsNone(self.group.image_version)

    def test_a_missing_version_is_rejected(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"/groups/{self.group.id}/image/", {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "missing_field")

    def test_deleting_the_image_clears_it(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f"/groups/{self.group.id}/image/", {"version": 1712345678})

        with patch("core.storage.destroy_image") as destroyed:
            resp = self.client.delete(f"/groups/{self.group.id}/image/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["image_url"])
        destroyed.assert_called_once_with("groups", self.group.id)
        self.group.refresh_from_db()
        self.assertIsNone(self.group.image_version)

    def test_a_group_with_no_image_serializes_null(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(f"/groups/{self.group.id}/")
        self.assertIsNone(resp.data["image_url"])

    def test_the_image_reaches_the_nested_group_on_an_invitation(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f"/groups/{self.group.id}/image/", {"version": 1712345678})
        GroupInvitaion.objects.create(
            group=self.group, invited_user=self.outsider,
            invited_by=self.admin, status="pending",
        )
        self.client.force_authenticate(self.outsider)
        resp = self.client.get("/groups/invitations/")
        self.assertIsNotNone(resp.data[0]["group"]["image_url"])


class GroupMembersCountTests(APITestCase):
    """members_count used to be 1 for every group: filtering on members__user
    and counting the same join counts only the requester's own membership."""

    def setUp(self):
        self.me = User.objects.create_user(username="counter", password="pw12345678")
        self.group = Group.objects.create(name="Crew", created_by=self.me)
        GroupMember.objects.create(group=self.group, user=self.me, role="admin")
        for index in range(3):
            GroupMember.objects.create(
                group=self.group,
                user=User.objects.create_user(
                    username=f"mate{index}", password="pw12345678"
                ),
                role="member",
            )

    def test_members_count_is_the_whole_group_not_just_me(self):
        self.client.force_authenticate(self.me)
        resp = self.client.get("/groups/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data[0]["members_count"], 4)

    def test_members_count_on_a_solo_group_is_one(self):
        solo = Group.objects.create(name="Solo", created_by=self.me)
        GroupMember.objects.create(group=solo, user=self.me, role="admin")
        self.client.force_authenticate(self.me)
        resp = self.client.get("/groups/")
        counts = {row["name"]: row["members_count"] for row in resp.data}
        self.assertEqual(counts, {"Crew": 4, "Solo": 1})

    def test_a_group_you_are_not_in_is_still_invisible(self):
        outsider = User.objects.create_user(username="nosy", password="pw12345678")
        self.client.force_authenticate(outsider)
        resp = self.client.get("/groups/")
        self.assertEqual(list(resp.data), [])


class RoomMessageTests(APITestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="talker", password="pw12345678")
        self.mate = User.objects.create_user(username="mate", password="pw12345678")
        self.outsider = User.objects.create_user(username="lurker", password="pw12345678")
        self.group = Group.objects.create(name="Room", created_by=self.me)
        GroupMember.objects.create(group=self.group, user=self.me, role="admin")
        GroupMember.objects.create(group=self.group, user=self.mate, role="member")

    def test_a_member_can_post(self):
        self.client.force_authenticate(self.me)
        resp = self.client.post(f"/groups/{self.group.id}/messages/", {"body": "yalla 7"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["kind"], "user")
        self.assertEqual(resp.data["body"], "yalla 7")
        self.assertEqual(resp.data["sender"]["username"], "talker")

    def test_a_blank_body_is_rejected(self):
        self.client.force_authenticate(self.me)
        for body in ("", "   ", "\n"):
            resp = self.client.post(f"/groups/{self.group.id}/messages/", {"body": body})
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(resp.data["code"], "missing_field")
        self.assertFalse(Message.objects.exists())

    def test_a_client_cannot_forge_a_system_message(self):
        self.client.force_authenticate(self.me)
        resp = self.client.post(
            f"/groups/{self.group.id}/messages/", {"body": "fake", "kind": "system"}
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["kind"], "user")
        self.assertIsNotNone(Message.objects.get().sender_id)

    def test_a_non_member_cannot_post_or_read(self):
        self.client.force_authenticate(self.outsider)
        posted = self.client.post(f"/groups/{self.group.id}/messages/", {"body": "hi"})
        self.assertEqual(posted.status_code, status.HTTP_404_NOT_FOUND)
        read = self.client.get(f"/groups/{self.group.id}/messages/")
        self.assertEqual(read.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_is_refused(self):
        resp = self.client.get(f"/groups/{self.group.id}/messages/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_messages_come_back_newest_first(self):
        for body in ("one", "two", "three"):
            Message.objects.create(group=self.group, sender=self.me, body=body)
        self.client.force_authenticate(self.me)
        resp = self.client.get(f"/groups/{self.group.id}/messages/")
        self.assertEqual(
            [row["body"] for row in resp.data["messages"]], ["three", "two", "one"]
        )
        self.assertIsNone(resp.data["next_before"])

    def test_another_groups_messages_never_leak(self):
        other = Group.objects.create(name="Other", created_by=self.outsider)
        GroupMember.objects.create(group=other, user=self.outsider, role="admin")
        Message.objects.create(group=other, sender=self.outsider, body="secret")
        Message.objects.create(group=self.group, sender=self.me, body="ours")

        self.client.force_authenticate(self.me)
        resp = self.client.get(f"/groups/{self.group.id}/messages/")
        self.assertEqual([row["body"] for row in resp.data["messages"]], ["ours"])

    def test_paging_backwards_walks_the_whole_stream_without_repeats(self):
        for index in range(12):
            Message.objects.create(group=self.group, sender=self.me, body=f"m{index}")

        self.client.force_authenticate(self.me)
        seen = []
        cursor = None
        for _ in range(5):
            url = f"/groups/{self.group.id}/messages/?limit=5"
            if cursor:
                url += f"&before={cursor}"
            resp = self.client.get(url)
            seen.extend(row["id"] for row in resp.data["messages"])
            cursor = resp.data["next_before"]
            if cursor is None:
                break

        self.assertIsNone(cursor)
        self.assertEqual(len(seen), 12)
        self.assertEqual(len(set(seen)), 12)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_next_before_is_null_on_the_last_page(self):
        for index in range(3):
            Message.objects.create(group=self.group, sender=self.me, body=f"m{index}")
        self.client.force_authenticate(self.me)
        resp = self.client.get(f"/groups/{self.group.id}/messages/?limit=5")
        self.assertEqual(len(resp.data["messages"]), 3)
        self.assertIsNone(resp.data["next_before"])

    def test_a_cursor_this_endpoint_did_not_issue_is_rejected(self):
        self.client.force_authenticate(self.me)
        resp = self.client.get(f"/groups/{self.group.id}/messages/?before=not-a-cursor")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "invalid_cursor")

    def test_the_page_limit_is_capped(self):
        for index in range(5):
            Message.objects.create(group=self.group, sender=self.me, body=f"m{index}")
        self.client.force_authenticate(self.me)
        resp = self.client.get(f"/groups/{self.group.id}/messages/?limit=99999")
        self.assertEqual(len(resp.data["messages"]), 5)

    def test_messages_sharing_a_timestamp_still_page_cleanly(self):
        stamp = timezone.now()
        made = [
            Message.objects.create(group=self.group, sender=self.me, body=f"m{index}")
            for index in range(4)
        ]
        Message.objects.filter(pk__in=[m.pk for m in made]).update(created_at=stamp)

        self.client.force_authenticate(self.me)
        first = self.client.get(f"/groups/{self.group.id}/messages/?limit=2")
        cursor = first.data["next_before"]
        self.assertIsNotNone(cursor)
        second = self.client.get(f"/groups/{self.group.id}/messages/?limit=2&before={cursor}")

        ids = [row["id"] for row in first.data["messages"]] + [
            row["id"] for row in second.data["messages"]
        ]
        self.assertEqual(len(set(ids)), 4)


class RoomSystemMessageTests(APITestCase):
    """Every system row is written where the action happens, with a structured
    payload the bilingual client renders from instead of parsing body."""

    def setUp(self):
        self.admin = User.objects.create_user(username="sysadmin", password="pw12345678")
        self.member = User.objects.create_user(username="sysmember", password="pw12345678")
        self.group = Group.objects.create(name="G", created_by=self.admin)
        GroupMember.objects.create(group=self.group, user=self.admin, role="admin")

    def _events(self):
        return {
            m.payload["event"]: m
            for m in Message.objects.filter(group=self.group, kind="system")
        }

    def test_joining_by_token_writes_member_joined(self):
        token = GroupInviteToken.objects.create(
            group=self.group, created_by=self.admin,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_authenticate(self.member)
        self.client.post("/groups/join/", {"token": str(token.token)})

        message = self._events()["member_joined"]
        self.assertEqual(message.kind, "system")
        self.assertIsNone(message.sender_id)
        self.assertEqual(message.payload["actor_id"], self.member.id)
        self.assertIn("sysmember", message.body)

    def test_accepting_an_invite_writes_member_joined(self):
        invitation = GroupInvitaion.objects.create(
            group=self.group, invited_user=self.member,
            invited_by=self.admin, status="pending",
        )
        self.client.force_authenticate(self.member)
        self.client.post(f"/groups/invitations/{invitation.id}/invite_responce/",
                         {"action": "accept"})
        self.assertIn("member_joined", self._events())

    def test_leaving_writes_member_left(self):
        GroupMember.objects.create(group=self.group, user=self.member, role="member")
        self.client.force_authenticate(self.member)
        self.client.delete(f"/groups/{self.group.id}/leave_group/")

        message = self._events()["member_left"]
        self.assertEqual(message.payload["actor_id"], self.member.id)

    def test_a_refused_action_writes_nothing(self):
        outsider = User.objects.create_user(username="nope", password="pw12345678")
        self.client.force_authenticate(outsider)
        self.client.post(f"/groups/{self.group.id}/messages/", {"body": "hi"})
        self.assertFalse(Message.objects.filter(kind="system").exists())

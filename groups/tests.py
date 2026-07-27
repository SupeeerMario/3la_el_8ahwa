from datetime import timedelta

from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone

from groups.models import Group, GroupMember, GroupInvitaion, GroupInviteToken

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

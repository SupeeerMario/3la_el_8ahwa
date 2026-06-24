from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

from groups.models import Group, GroupMember

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

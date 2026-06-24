from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


class UserAuthTests(APITestCase):
    """Covers the JWT migration: registration, login token pair, the refresh
    endpoint, and that protected routes require authentication."""

    def test_register_creates_user_without_echoing_password(self):
        resp = self.client.post("/users/register/", {
            "username": "alice",
            "email": "alice@example.com",
            "password": "s3cretpass123",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username="alice").exists())
        self.assertNotIn("password", resp.data["user"])

    def test_login_returns_jwt_access_and_refresh(self):
        User.objects.create_user(username="bob", email="b@x.com", password="pw12345678")
        resp = self.client.post("/users/login/", {"username": "bob", "password": "pw12345678"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_with_bad_credentials_is_rejected(self):
        resp = self.client.post("/users/login/", {"username": "ghost", "password": "nope"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_access_token_authorizes_a_protected_request(self):
        User.objects.create_user(username="carol", email="c@x.com", password="pw12345678")
        login = self.client.post("/users/login/", {"username": "carol", "password": "pw12345678"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        resp = self.client.get("/users/get_profile/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["username"], "carol")

    def test_refresh_endpoint_issues_a_new_access_token(self):
        User.objects.create_user(username="dave", email="d@x.com", password="pw12345678")
        login = self.client.post("/users/login/", {"username": "dave", "password": "pw12345678"})
        resp = self.client.post("/users/token/refresh/", {"refresh": login.data["refresh"]})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_protected_route_requires_authentication(self):
        resp = self.client.get("/users/get_profile/")
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class UserProfileTests(APITestCase):
    """Covers the profile actions: get/update/delete."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="eve", email="eve@example.com", password="pw12345678",
        )
        self.client.force_authenticate(self.user)

    def test_get_profile_returns_current_user(self):
        resp = self.client.get("/users/get_profile/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["username"], "eve")
        self.assertEqual(resp.data["email"], "eve@example.com")

    def test_update_profile_changes_email(self):
        resp = self.client.put("/users/update_profile/", {"email": "new@example.com"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_delete_profile_removes_account(self):
        resp = self.client.delete("/users/delete_profile/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(username="eve").exists())

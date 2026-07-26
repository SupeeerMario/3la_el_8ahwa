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
        original_refresh = login.data["refresh"]
        resp = self.client.post("/users/token/refresh/", {"refresh": original_refresh})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertNotEqual(resp.data["refresh"], original_refresh)
        reuse = self.client.post("/users/token/refresh/", {"refresh": original_refresh})
        self.assertEqual(reuse.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_route_requires_authentication(self):
        resp = self.client.get("/users/get_profile/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


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


class UserTokenLifecycleTests(APITestCase):
    """Covers the delete_profile / token_blacklist interaction with SimpleJWT.

    Uses a real login-issued token pair (not force_authenticate) because both
    tests exercise the refresh/blacklist endpoints directly against
    OutstandingToken/BlacklistedToken rows that only exist for tokens actually
    minted by RefreshToken.for_user().
    """

    def test_refresh_after_delete_profile_is_401_not_500(self):
        User.objects.create_user(
            username="deleteme", email="dm@example.com", password="pw12345678",
        )
        login = self.client.post(
            "/users/login/", {"username": "deleteme", "password": "pw12345678"}
        )
        refresh_token = login.data["refresh"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        del_resp = self.client.delete("/users/delete_profile/")
        self.assertEqual(del_resp.status_code, status.HTTP_200_OK)
        self.client.credentials()

        resp = self.client.post("/users/token/refresh/", {"refresh": refresh_token})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_blacklist_endpoint_revokes_refresh_token(self):
        User.objects.create_user(
            username="frank", email="f@x.com", password="pw12345678",
        )
        login = self.client.post(
            "/users/login/", {"username": "frank", "password": "pw12345678"}
        )
        refresh_token = login.data["refresh"]

        resp = self.client.post("/users/token/blacklist/", {"refresh": refresh_token})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        reuse = self.client.post("/users/token/refresh/", {"refresh": refresh_token})
        self.assertEqual(reuse.status_code, status.HTTP_401_UNAUTHORIZED)


class UserPasswordPolicyTests(APITestCase):
    """AUTH_PASSWORD_VALIDATORS is configured but DRF never invoked it, so any
    password was accepted at registration. One case per configured validator."""

    def _register(self, password, username="newuser", email="new@example.com"):
        return self.client.post("/users/register/", {
            "username": username,
            "email": email,
            "password": password,
        })

    def assertRejected(self, resp):
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", resp.data)
        self.assertFalse(User.objects.exists())

    def test_register_rejects_short_password(self):
        self.assertRejected(self._register("Ab3!x"))

    def test_register_rejects_entirely_numeric_password(self):
        self.assertRejected(self._register("29481067"))

    def test_register_rejects_common_password(self):
        self.assertRejected(self._register("password"))

    def test_register_rejects_password_similar_to_username(self):
        self.assertRejected(self._register("chessplayer", username="chessplayer"))

    def test_register_rejects_single_character_password(self):
        self.assertRejected(self._register("1"))

    def test_register_accepts_a_strong_password(self):
        resp = self._register("tr0mbone-Vault-91")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_rejected_registration_returns_a_usable_message(self):
        resp = self._register("1")
        self.assertTrue(
            any("too short" in str(m).lower() for m in resp.data["password"]),
            resp.data,
        )

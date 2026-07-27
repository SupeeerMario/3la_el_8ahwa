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


class LoginIdentifierTests(APITestCase):
    """Login accepts an email or a username in the same field."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="zaid", email="Zaid@Example.com", password="tr0mbone-Vault-91"
        )

    def test_login_by_username_still_works(self):
        resp = self.client.post("/users/login/", {
            "username": "zaid", "password": "tr0mbone-Vault-91"
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_login_by_identifier_field_with_username(self):
        resp = self.client.post("/users/login/", {
            "identifier": "zaid", "password": "tr0mbone-Vault-91"
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_login_by_email_case_insensitively(self):
        resp = self.client.post("/users/login/", {
            "identifier": "zaid@example.com", "password": "tr0mbone-Vault-91"
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["user"]["username"], "zaid")

    def test_login_with_unknown_email_is_rejected(self):
        resp = self.client.post("/users/login/", {
            "identifier": "nobody@example.com", "password": "tr0mbone-Vault-91"
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_without_any_identifier_is_rejected(self):
        resp = self.client.post("/users/login/", {"password": "tr0mbone-Vault-91"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_failed_login_carries_the_error_code(self):
        resp = self.client.post("/users/login/", {
            "identifier": "zaid", "password": "wrong-password-here"
        })
        self.assertEqual(resp.data["code"], "invalid_credentials")


class DuplicateEmailTests(APITestCase):
    """Email login is ambiguous if two accounts share an address, so the
    address is claimed at registration and on profile update."""

    def setUp(self):
        self.existing = User.objects.create_user(
            username="first", email="taken@example.com", password="tr0mbone-Vault-91"
        )

    def test_register_rejects_a_taken_email(self):
        resp = self.client.post("/users/register/", {
            "username": "second",
            "email": "TAKEN@example.com",
            "password": "tr0mbone-Vault-91",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", resp.data)

    def test_update_profile_rejects_a_taken_email(self):
        other = User.objects.create_user(
            username="second", email="free@example.com", password="tr0mbone-Vault-91"
        )
        self.client.force_authenticate(other)
        resp = self.client.put("/users/update_profile/", {"email": "taken@example.com"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_profile_accepts_the_users_own_email(self):
        self.client.force_authenticate(self.existing)
        resp = self.client.put("/users/update_profile/", {
            "email": "taken@example.com", "display_name": "First"
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["display_name"], "First")


class ChangePasswordTests(APITestCase):
    """Covers /users/change_password/ and the token revocation it performs."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pwuser", email="pw@example.com", password="tr0mbone-Vault-91"
        )

    def _login(self):
        return self.client.post("/users/login/", {
            "identifier": "pwuser", "password": "tr0mbone-Vault-91"
        })

    def test_change_password_requires_authentication(self):
        resp = self.client.post("/users/change_password/", {
            "current_password": "tr0mbone-Vault-91",
            "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password_sets_the_new_password(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/change_password/", {
            "current_password": "tr0mbone-Vault-91",
            "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("b4ssoon-Harbor-77"))

    def test_change_password_rejects_a_wrong_current_password(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/change_password/", {
            "current_password": "not-my-password",
            "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("current_password", resp.data)

    def test_change_password_enforces_the_password_policy(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/change_password/", {
            "current_password": "tr0mbone-Vault-91",
            "new_password": "1",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", resp.data)

    def test_change_password_revokes_outstanding_refresh_tokens(self):
        old_refresh = self._login().data["refresh"]
        self.client.force_authenticate(self.user)
        changed = self.client.post("/users/change_password/", {
            "current_password": "tr0mbone-Vault-91",
            "new_password": "b4ssoon-Harbor-77",
        })
        self.client.force_authenticate(None)
        resp = self.client.post("/users/token/refresh/", {"refresh": old_refresh})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        fresh = self.client.post("/users/token/refresh/", {
            "refresh": changed.data["refresh"]
        })
        self.assertEqual(fresh.status_code, status.HTTP_200_OK)


class PasswordResetTests(APITestCase):
    """Covers the request/confirm reset pair, including that the request step
    does not disclose whether an address has an account."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="resetme", email="reset@example.com", password="tr0mbone-Vault-91"
        )

    def _request_reset(self, email="reset@example.com"):
        return self.client.post("/users/password_reset/", {"email": email})

    def _tokens_for_user(self):
        from users.serializers import PasswordResetRequestSerializer

        return (
            PasswordResetRequestSerializer.uid_for(self.user),
            PasswordResetRequestSerializer.token_for(self.user),
        )

    def test_reset_request_sends_a_mail_for_a_known_address(self):
        from django.core import mail

        resp = self._request_reset()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("uid=", mail.outbox[0].body)

    def test_reset_request_for_an_unknown_address_looks_identical(self):
        from django.core import mail

        known = self._request_reset()
        mail.outbox.clear()
        unknown = self._request_reset("nobody@example.com")
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_confirm_sets_the_new_password(self):
        uid, token = self._tokens_for_user()
        resp = self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": token, "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("b4ssoon-Harbor-77"))

    def test_reset_token_cannot_be_replayed(self):
        uid, token = self._tokens_for_user()
        self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": token, "new_password": "b4ssoon-Harbor-77",
        })
        replay = self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": token, "new_password": "cl4rinet-Meadow-22",
        })
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_rejects_a_forged_token(self):
        uid, _ = self._tokens_for_user()
        resp = self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": "not-a-real-token", "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_rejects_a_forged_uid(self):
        _, token = self._tokens_for_user()
        resp = self.client.post("/users/password_reset_confirm/", {
            "uid": "!!!", "token": token, "new_password": "b4ssoon-Harbor-77",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_enforces_the_password_policy(self):
        uid, token = self._tokens_for_user()
        resp = self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": token, "new_password": "1",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", resp.data)

    def test_reset_revokes_outstanding_refresh_tokens(self):
        login = self.client.post("/users/login/", {
            "identifier": "resetme", "password": "tr0mbone-Vault-91"
        })
        uid, token = self._tokens_for_user()
        self.client.post("/users/password_reset_confirm/", {
            "uid": uid, "token": token, "new_password": "b4ssoon-Harbor-77",
        })
        resp = self.client.post("/users/token/refresh/", {"refresh": login.data["refresh"]})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class ProfileShapeTests(APITestCase):
    """get_profile is the only place the requester's own email is exposed."""

    def test_profile_carries_email_and_display_name(self):
        user = User.objects.create_user(
            username="shape", email="shape@example.com", password="tr0mbone-Vault-91"
        )
        user.display_name = "Shape"
        user.save(update_fields=["display_name"])
        self.client.force_authenticate(user)
        resp = self.client.get("/users/get_profile/")
        self.assertEqual(resp.data["email"], "shape@example.com")
        self.assertEqual(resp.data["display_name"], "Shape")

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

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


class EmailUniquenessTests(APITestCase):
    """The database, not just the serializer, now enforces one account per
    email address -- case-insensitively, and only for addresses that exist."""

    def test_the_database_rejects_a_case_variant_duplicate(self):
        from django.db import IntegrityError, transaction

        User.objects.create_user(
            username="cione", email="Dup@Example.com", password="tr0mbone-Vault-91"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="citwo", email="dup@example.com", password="tr0mbone-Vault-91"
                )

    def test_several_accounts_may_have_no_email(self):
        first = User.objects.create_user(username="noemail1", password="tr0mbone-Vault-91")
        second = User.objects.create_user(username="noemail2", password="tr0mbone-Vault-91")
        self.assertIsNone(first.email)
        self.assertIsNone(second.email)

    def test_a_blank_email_is_stored_as_null(self):
        user = User.objects.create_user(
            username="blank", email="", password="tr0mbone-Vault-91"
        )
        user.refresh_from_db()
        self.assertIsNone(user.email)

    def test_registration_now_requires_an_email(self):
        resp = self.client.post("/users/register/", {
            "username": "noaddress", "password": "tr0mbone-Vault-91",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", resp.data)

    def test_registration_rejects_a_case_variant_of_a_taken_email(self):
        User.objects.create_user(
            username="holder", email="holder@example.com", password="tr0mbone-Vault-91"
        )
        resp = self.client.post("/users/register/", {
            "username": "usurper",
            "email": "HOLDER@Example.com",
            "password": "tr0mbone-Vault-91",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clearing_your_email_frees_it_for_someone_else(self):
        holder = User.objects.create_user(
            username="releaser", email="freed@example.com", password="tr0mbone-Vault-91"
        )
        taker = User.objects.create_user(
            username="taker", password="tr0mbone-Vault-91"
        )

        self.client.force_authenticate(holder)
        self.client.put("/users/update_profile/", {"email": ""})

        self.client.force_authenticate(taker)
        resp = self.client.put("/users/update_profile/", {"email": "freed@example.com"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        taker.refresh_from_db()
        self.assertEqual(taker.email, "freed@example.com")

    def test_an_account_without_an_email_cannot_be_reset(self):
        from django.core import mail

        User.objects.create_user(username="unreachable", password="tr0mbone-Vault-91")
        resp = self.client.post("/users/password_reset/", {"email": "unreachable@example.com"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)


class AvatarTests(APITestCase):
    """Covers the Cloudinary signed-upload flow. Signing and URL building are
    exercised for real (neither touches the network); only the destroy call,
    which does, is patched."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="avataruser", email="av@example.com", password="tr0mbone-Vault-91"
        )
        self.other = User.objects.create_user(
            username="avatarother", email="av2@example.com", password="tr0mbone-Vault-91"
        )

    def test_signature_requires_authentication(self):
        resp = self.client.post("/users/avatar_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_signature_is_503_when_cloudinary_is_unconfigured(self):
        from django.test import override_settings

        self.client.force_authenticate(self.user)
        with override_settings(CLOUDINARY_URL=""):
            resp = self.client.post("/users/avatar_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.data["code"], "avatar_storage_unconfigured")

    def test_signature_pins_the_public_id_to_the_requesting_user(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/avatar_upload_signature/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["params"]["public_id"], f"avatars/{self.user.id}")

    def test_two_users_get_different_public_ids(self):
        self.client.force_authenticate(self.user)
        mine = self.client.post("/users/avatar_upload_signature/").data
        self.client.force_authenticate(self.other)
        theirs = self.client.post("/users/avatar_upload_signature/").data
        self.assertNotEqual(mine["params"]["public_id"], theirs["params"]["public_id"])
        self.assertNotEqual(mine["signature"], theirs["signature"])

    def test_the_signature_covers_the_public_id(self):
        from cloudinary.utils import api_sign_request
        from django.conf import settings
        import cloudinary

        self.client.force_authenticate(self.user)
        issued = self.client.post("/users/avatar_upload_signature/").data

        cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL, secure=True)
        secret = cloudinary.config().api_secret

        tampered = dict(issued["params"])
        tampered["public_id"] = f"avatars/{self.other.id}"
        self.assertNotEqual(
            api_sign_request(tampered, secret), issued["signature"]
        )

    def test_avatar_url_is_null_before_any_upload(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/users/get_profile/")
        self.assertIsNone(resp.data["avatar_url"])

    def test_confirming_a_version_produces_a_resized_url(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/avatar/", {"version": 1785171939})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        url = resp.data["avatar_url"]
        self.assertIn(f"avatars/{self.user.id}", url)
        self.assertIn("v1785171939", url)
        self.assertIn("w_256", url)
        self.assertIn("h_256", url)

    def test_a_new_version_busts_the_old_url(self):
        self.client.force_authenticate(self.user)
        first = self.client.post("/users/avatar/", {"version": 111}).data["avatar_url"]
        second = self.client.post("/users/avatar/", {"version": 222}).data["avatar_url"]
        self.assertNotEqual(first, second)

    def test_confirm_rejects_a_missing_version(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/avatar/", {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "missing_field")

    def test_confirm_rejects_a_non_numeric_version(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/users/avatar/", {"version": "latest"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_requires_authentication(self):
        resp = self.client.post("/users/avatar/", {"version": 111})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deleting_an_avatar_clears_it(self):
        from unittest.mock import patch

        self.client.force_authenticate(self.user)
        self.client.post("/users/avatar/", {"version": 111})

        with patch("core.storage.destroy_avatar") as destroyed:
            resp = self.client.delete("/users/avatar/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["avatar_url"])
        destroyed.assert_called_once_with(self.user.id)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.avatar_version)

    def test_deleting_when_there_is_no_avatar_calls_nothing(self):
        from unittest.mock import patch

        self.client.force_authenticate(self.user)
        with patch("core.storage.destroy_avatar") as destroyed:
            resp = self.client.delete("/users/avatar/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        destroyed.assert_not_called()

    def test_update_profile_cannot_write_the_avatar_version(self):
        self.client.force_authenticate(self.user)
        self.client.put("/users/update_profile/", {"avatar_version": 999})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.avatar_version)

    def test_a_members_avatar_appears_on_the_group_roster(self):
        from groups.models import Group, GroupMember

        group = Group.objects.create(name="Av", created_by=self.user)
        GroupMember.objects.create(group=group, user=self.user, role="admin")
        GroupMember.objects.create(group=group, user=self.other, role="member")

        self.client.force_authenticate(self.user)
        self.client.post("/users/avatar/", {"version": 333})

        resp = self.client.get(f"/groups/{group.id}/list_group_members/")
        urls = {row["user"]["id"]: row["user"]["avatar_url"] for row in resp.data["members"]}
        self.assertIn("v333", urls[self.user.id])
        self.assertIsNone(urls[self.other.id])


class ThrottleTests(APITestCase):
    """Rate limits on the two unauthenticated auth endpoints. Rates are
    overridden per test; the cache is shared state and must be cleared."""

    RATES = {
        "login_ip": "3/min",
        "login_account": "3/hour",
        "password_reset_email": "2/hour",
        "password_reset_ip": "5/hour",
    }

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user(
            username="throttled", email="throttled@example.com",
            password="tr0mbone-Vault-91",
        )

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    @contextmanager
    def _rates(self, **overrides):
        """DRF binds THROTTLE_RATES onto the class at import time, so
        override_settings(REST_FRAMEWORK=...) does not reach it."""
        from core.throttling import (
            LoginAccountThrottle,
            LoginIPThrottle,
            PasswordResetEmailThrottle,
            PasswordResetIPThrottle,
        )

        rates = {**self.RATES, **overrides}
        classes = (
            LoginIPThrottle,
            LoginAccountThrottle,
            PasswordResetEmailThrottle,
            PasswordResetIPThrottle,
        )
        with ExitStack() as stack:
            for throttle_class in classes:
                stack.enter_context(
                    patch.object(throttle_class, "THROTTLE_RATES", rates)
                )
            yield

    def _login(self, password="wrong-password-entirely", identifier="throttled", **extra):
        return self.client.post(
            "/users/login/", {"identifier": identifier, "password": password}, **extra
        )

    def test_repeated_failed_logins_are_throttled(self):
        with self._rates():
            for _ in range(3):
                self.assertEqual(self._login().status_code, status.HTTP_400_BAD_REQUEST)
            blocked = self._login()
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(blocked.data["code"], "throttled")

    def test_a_throttled_response_carries_retry_after(self):
        with self._rates():
            for _ in range(3):
                self._login()
            blocked = self._login()
        self.assertIn("Retry-After", blocked)

    def test_successful_logins_are_not_throttled(self):
        with self._rates():
            for _ in range(6):
                resp = self._login(password="tr0mbone-Vault-91")
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_a_correct_password_still_works_below_the_limit(self):
        with self._rates():
            self._login()
            self._login()
            resp = self._login(password="tr0mbone-Vault-91")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_failures_against_one_account_do_not_block_another(self):
        User.objects.create_user(
            username="bystander", email="bystander@example.com",
            password="tr0mbone-Vault-91",
        )
        with self._rates(login_ip="100/min"):
            for _ in range(3):
                self._login()
            other = self.client.post("/users/login/", {
                "identifier": "bystander", "password": "tr0mbone-Vault-91",
            })
        self.assertEqual(other.status_code, status.HTTP_200_OK)

    def test_the_account_limit_survives_a_change_of_ip(self):
        with self._rates(login_ip="100/min"):
            for i in range(3):
                self._login(REMOTE_ADDR=f"10.0.0.{i}")
            blocked = self._login(REMOTE_ADDR="10.0.0.99")
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_the_ip_limit_survives_a_change_of_account(self):
        with self._rates(login_account="100/hour"):
            for i in range(3):
                self._login(identifier=f"ghost{i}")
            blocked = self._login(identifier="another-ghost")
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_the_account_limit_is_case_insensitive(self):
        with self._rates(login_ip="100/min"):
            for _ in range(3):
                self._login(identifier="THROTTLED")
            blocked = self._login(identifier="throttled")
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_password_reset_is_throttled_per_address(self):
        with self._rates():
            for _ in range(2):
                resp = self.client.post(
                    "/users/password_reset/", {"email": "throttled@example.com"}
                )
                self.assertEqual(resp.status_code, status.HTTP_200_OK)
            blocked = self.client.post(
                "/users/password_reset/", {"email": "throttled@example.com"}
            )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(blocked.data["code"], "throttled")

    def test_throttling_one_address_does_not_block_another(self):
        with self._rates():
            for _ in range(2):
                self.client.post(
                    "/users/password_reset/", {"email": "throttled@example.com"}
                )
            other = self.client.post(
                "/users/password_reset/", {"email": "someone-else@example.com"}
            )
        self.assertEqual(other.status_code, status.HTTP_200_OK)

    def test_an_unknown_address_is_throttled_the_same_way(self):
        """Otherwise the throttle itself becomes a user-enumeration oracle."""
        with self._rates():
            for _ in range(2):
                self.client.post(
                    "/users/password_reset/", {"email": "nobody@example.com"}
                )
            blocked = self.client.post(
                "/users/password_reset/", {"email": "nobody@example.com"}
            )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_the_reset_ip_limit_catches_a_spread_of_addresses(self):
        with self._rates(password_reset_email="100/hour"):
            for i in range(5):
                self.client.post("/users/password_reset/", {"email": f"t{i}@example.com"})
            blocked = self.client.post(
                "/users/password_reset/", {"email": "final@example.com"}
            )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_registration_is_not_throttled_by_login_failures(self):
        with self._rates():
            for _ in range(4):
                self._login()
            resp = self.client.post("/users/register/", {
                "username": "brandnew", "email": "brandnew@example.com",
                "password": "tr0mbone-Vault-91",
            })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

from rest_framework.response import Response


NOT_AUTHENTICATED = "not_authenticated"
INVALID_CREDENTIALS = "invalid_credentials"
VALIDATION_ERROR = "validation_error"

GROUP_NOT_FOUND = "group_not_found"
NOT_A_MEMBER = "not_a_member"
NOT_ADMIN = "not_admin"
ALREADY_MEMBER = "already_member"
MEMBER_NOT_FOUND = "member_not_found"
CANNOT_TARGET_SELF = "cannot_target_self"
LAST_ADMIN = "last_admin"
INVALID_ROLE = "invalid_role"

EVENT_NOT_FOUND = "event_not_found"
VOTING_CLOSED = "voting_closed"

USER_NOT_FOUND = "user_not_found"
INVITE_PENDING = "invite_pending"
INVITE_NOT_FOUND = "invite_not_found"
INVITE_NOT_DISMISSABLE = "invite_not_dismissable"
INVALID_INVITE_ACTION = "invalid_invite_action"

INVITE_TOKEN_NOT_FOUND = "invite_token_not_found"
INVITE_TOKEN_EXPIRED = "invite_token_expired"
INVITE_TOKEN_EXHAUSTED = "invite_token_exhausted"
INVITE_TOKEN_REVOKED = "invite_token_revoked"

INVALID_RESET_TOKEN = "invalid_reset_token"
INCORRECT_PASSWORD = "incorrect_password"
EMAIL_TAKEN = "email_taken"

AVATAR_STORAGE_UNCONFIGURED = "avatar_storage_unconfigured"

MISSING_FIELD = "missing_field"


def error_response(code, message, status):
    return Response({"code": code, "error": message}, status=status)

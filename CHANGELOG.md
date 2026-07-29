# Changelog

Notable API changes, newest first. Entries marked **BREAKING** change the shape
or status code of an existing response and require a client change.

Dates are the day the change landed on `main`.

## Unreleased — Phase 5, security & correctness

- **BREAKING — `POST /groups/invitations/send_invite/` answers `404
  group_not_found` to a non-member**, was `403 not_admin`. It now resolves the
  group through the caller's membership, matching the project convention: `404`
  when the object does not resolve for you, `403` only when you are a member
  failing a role check. A member who is not an admin still gets `403`.
- **BREAKING — three more routes answer `404` instead of `403 not_a_member`**,
  for the same reason. Each resolved its target with an unscoped lookup and
  then checked membership separately, so a `404` and a `403` told an outsider
  whether the id existed:
  - `POST /event-locations/` — now `404 event_not_found`
  - `POST /checkins/` — now `404 event_not_found`
  - `GET /leaderboard/?group=<id>` — now `404 group_not_found`

  A member who fails a *role* check still gets `403`; only "you cannot see this
  at all" became `404`.
- **`POST /groups/invitations/send_invite/` is throttled**, 20/hour per user by
  default (`THROTTLE_SEND_INVITE`). Over the limit is `429 {"code":
  "throttled"}` with a `Retry-After` header. Every invite is an unsolicited
  notification for somebody else, so this counts requests, not failures.
- **`POST /events/` returns the new event's `id`.** `EventSerializer` omitted
  it, so a `201` could not be addressed by the client that had just created it.
  Additive; nothing else in the payload moved.
- **`Group.created_by` survives its creator.** The FK was `CASCADE`, so
  deleting an account deleted every group that account had created, along with
  the other members' events and messages. It is now `SET_NULL`, and
  `leave_group` / `remove_member` reassign it to the oldest remaining admin
  (falling back to the oldest remaining member). `created_by` may now be
  `null` in a group payload — a group whose creator deleted their account and
  left nobody behind.
- **A failed password-reset email is logged.** `send_mail` ran with
  `fail_silently=True`, so an SMTP refusal was invisible. The response is
  unchanged and still does not disclose whether an address has an account.
- Missing required environment variables now raise `ImproperlyConfigured`
  naming the variable, instead of `AttributeError: 'NoneType' object has no
  attribute 'split'`.
- `SECURE_SSL_ENABLED` (default `False`) gates `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and HSTS. Deliberately not
  keyed off `DEBUG`, because the prod stack currently serves plain HTTP and
  would redirect-loop.

## 2026-07-28 — Phase 4.5, group room and images

- **BREAKING — `Notification.notification_type` is now `kind`.**
- **BREAKING — `Notification.is_read` (boolean) is now `read_at`**, a nullable
  timestamp where `null` means unread. Requested by the client so it can answer
  "new since you last looked".
- Added `GET`/`POST /groups/<id>/messages/` (the group room, cursor paginated),
  group images and check-in photos.

## 2026-07-28 — Phases 2 to 4, the core loop

- Added voting: `POST`/`DELETE /event-locations/<id>/vote/` and
  `GET /events/<id>/tally/`. One vote per event is a database constraint.
- Added check-ins at `/checkins/`, notifications at `/notifications/` and three
  leaderboards at `/leaderboard/`.
- `DELETE /events/<id>/` refuses with `event_starting_soon` once `start_time`
  is within `EVENT_DELETE_LOCK_MINUTES` (default 60).

## 2026-07-27 — Phase 1.5, auth and groups

- **BREAKING — `DELETE /groups/<id>/delete_group/` returns `204` empty**, was
  `200` with `{"message": ...}`.
- **BREAKING — `PATCH /groups/<id>/update_group/` returns the serialized
  group**, was `200` with `{"message": "Group has been updated"}`.
- **BREAKING — a non-member calling `list_group_members` gets `404`**, was
  `400`.
- **BREAKING — `show_all_invitations` defaults to pending**, was everything.
  Pass `?status=all` for the old behaviour.
- **Every error response now carries a machine-readable `code`.** The client is
  bilingual and localizes from the code, never from the prose message.
- `POST /users/login/` accepts an `identifier` that may be a username **or** an
  email address.
- Added password reset and change, invite tokens, admin membership management
  and Cloudinary avatars.
- `my_groups` now delegates to `GET /groups/` and returns identical rows. Use
  `GET /groups/`; `my_groups` is kept only so older clients keep working.

## Earlier — undated, shipped before this file existed

- **BREAKING — `POST /users/login/` returns `access` and `refresh`**, was a
  single `token` key.
- **BREAKING — `DELETE /events/<id>/` returns `204` empty**, was `200` with a
  message body.

# ala_el_8ahwa

*3la el 8ahwa* — "on the coffee". A Django 6 + Django REST Framework JSON API.

Users form **groups**, create **events** for a group, propose and vote on
candidate **locations**, and **check in** when they arrive. A Celery beat task
freezes each event's winning location at its start time; check-ins are
validated against that location's coordinates. There are notifications and
three leaderboards on top.

The client is a separate React Native (Expo) app.

## Running it

Everything runs in Docker — the database host is a Compose service name, so
`manage.py` on the host cannot reach it. **Both `-f` flags are always
required**; the base file alone has no project name, no env file and no
published ports.

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

nginx serves on `:8001`, Django's dev server on `:8000`. The production
override is `docker-compose.prod.yml`, which serves on `:8002` through
gunicorn.

### Configuration

`settings.py` reads `.env.{DJANGO_ENV}` (default `.env.local`). These files are
gitignored; **`.env.example` is the tracked template listing every key** —
copy it and fill in real values. A missing required variable now fails at
startup with `ImproperlyConfigured` naming the variable.

### Tests

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm django-app python manage.py test
# one app, or one test:
docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm django-app python manage.py test events
docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm django-app python manage.py test events.tests.EventCreateTests
```

There is no pytest, no coverage tooling and no CI.

## The apps

| App | What it owns |
|---|---|
| `users` | Custom user model, JWT auth, registration, password reset/change, avatars |
| `groups` | Groups, membership and roles, invitations, invite tokens, the group room |
| `events` | Events, candidate locations, voting, the winner freeze |
| `checkins` | Check-ins, validated by distance from the winning location |
| `notifications` | Typed notifications, written server-side only |
| `leaderboard` | Three live-aggregated boards; no models |
| `core` | Shared helpers: error codes, permissions, geo, Cloudinary storage, throttling |

## API conventions

- **Auth is JWT.** `POST /users/login/` takes an `identifier` (username *or*
  email) and returns `access` + `refresh`. Refresh at
  `/users/token/refresh/`, log out at `/users/token/blacklist/`.
- **Every error response carries a `code`.** The client is bilingual and
  localizes from that code, never from the English `message`. `core/errors.py`
  is the vocabulary.
- **Querysets are scoped to the requesting user.** A non-member gets `404` on a
  detail route because the object never resolves for them; `403` means they are
  a member failing a role or ownership check.
- **Server-owned fields are never client-writable** — `created_by`,
  `proposed_by`, `winning_location`, `is_valid` and `role` among them.

`CHANGELOG.md` records the breaking changes; read it before upgrading a client.

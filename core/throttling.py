import hashlib

from rest_framework.throttling import SimpleRateThrottle


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FailureRateThrottle(SimpleRateThrottle):
    """Rate limit that counts only the failures the view reports back.

    SimpleRateThrottle records every request that reaches it. These endpoints
    charge the caller only when the attempt was wrong, so the view calls
    record_failure() itself.
    """

    def allow_request(self, request, view):
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.now = self.timer()

        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()

        if len(self.history) >= self.num_requests:
            return self.throttle_failure()

        return True

    def record_failure(self, request, view=None):
        key = self.get_cache_key(request, view)
        if key is None:
            return

        history = self.cache.get(key, [])
        now = self.timer()

        while history and history[-1] <= now - self.duration:
            history.pop()

        history.insert(0, now)
        self.cache.set(key, history, self.duration)


def _login_identifier(request):
    data = getattr(request, "data", None) or {}
    identifier = data.get("identifier") or data.get("username") or ""
    return identifier.strip().lower()


class LoginIPThrottle(FailureRateThrottle):
    """Failed logins per client IP."""

    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class LoginAccountThrottle(FailureRateThrottle):
    """Failed logins per targeted account, so rotating IPs does not help."""

    scope = "login_account"

    def get_cache_key(self, request, view):
        identifier = _login_identifier(request)
        if not identifier:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": _digest(identifier),
        }


class PasswordResetEmailThrottle(SimpleRateThrottle):
    """Reset requests per target address. Counts every request, not just
    failures: each one is an email somebody else has to receive."""

    scope = "password_reset_email"

    def get_cache_key(self, request, view):
        data = getattr(request, "data", None) or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": _digest(email),
        }


class PasswordResetIPThrottle(SimpleRateThrottle):
    """Reset requests per client IP."""

    scope = "password_reset_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class GroupMessagesThrottle(SimpleRateThrottle):
    """Backstop on room polling, per user. Set well above what a correct client
    produces — it exists to catch a runaway loop, not to shape the client."""

    scope = "group_messages"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": request.user.pk,
        }

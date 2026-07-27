from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

from core import errors


_EXCEPTION_CODES = (
    (exceptions.ValidationError, errors.VALIDATION_ERROR),
    (exceptions.NotAuthenticated, errors.NOT_AUTHENTICATED),
    (exceptions.AuthenticationFailed, errors.NOT_AUTHENTICATED),
    (exceptions.PermissionDenied, "permission_denied"),
    (exceptions.NotFound, "not_found"),
    (exceptions.MethodNotAllowed, "method_not_allowed"),
    (exceptions.Throttled, "throttled"),
)


def _code_for(exc):
    for exception_class, code in _EXCEPTION_CODES:
        if isinstance(exc, exception_class):
            return code
    return getattr(exc, "default_code", None) or "error"


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    code = _code_for(exc)

    if isinstance(response.data, dict):
        if "code" not in response.data:
            response.data = {"code": code, **response.data}
    else:
        response.data = {"code": code, "detail": response.data}

    return response

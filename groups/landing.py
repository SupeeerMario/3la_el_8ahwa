from django.conf import settings
from django.shortcuts import render

from core import errors
from . import invites


REASON_TEXT = {
    errors.INVITE_TOKEN_REVOKED: "This invite link has been revoked.",
    errors.INVITE_TOKEN_EXPIRED: "This invite link has expired.",
    errors.INVITE_TOKEN_EXHAUSTED: "This invite link has already been used the maximum number of times.",
}


def invite_landing(request, value):
    invite_token = invites.token_for(value)
    reason = invites.unusable_reason(invite_token) if invite_token else None

    context = {
        "found": invite_token is not None,
        "valid": invite_token is not None and reason is None,
        "reason_text": REASON_TEXT.get(reason),
        "group": invite_token.group if invite_token else None,
        "invited_by": invite_token.created_by if invite_token else None,
        "code": invite_token.code if invite_token else None,
        "deep_link": (
            f"{settings.INVITE_DEEP_LINK}?code={invite_token.code}"
            if invite_token else None
        ),
        "app_store_url": settings.APP_STORE_URL,
        "play_store_url": settings.PLAY_STORE_URL,
    }

    return render(
        request,
        "groups/invite.html",
        context,
        status=200 if invite_token else 404,
    )

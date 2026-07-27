import time

from django.conf import settings


UPLOAD_ENDPOINT = "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"


def is_configured():
    return bool(settings.CLOUDINARY_URL)


def _configure():
    import cloudinary

    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL, secure=True)
    return cloudinary


def public_id_for(user_id):
    return f"avatars/{user_id}"


def upload_signature(user_id):
    cloudinary = _configure()
    from cloudinary.utils import api_sign_request

    params = {
        "public_id": public_id_for(user_id),
        "timestamp": int(time.time()),
        "overwrite": "true",
        "invalidate": "true",
    }
    config = cloudinary.config()

    return {
        "upload_url": UPLOAD_ENDPOINT.format(cloud_name=config.cloud_name),
        "api_key": config.api_key,
        "params": params,
        "signature": api_sign_request(params, config.api_secret),
        "expires_in": settings.AVATAR_SIGNATURE_TTL,
    }


def destroy_avatar(user_id):
    _configure()
    from cloudinary.uploader import destroy

    try:
        destroy(public_id_for(user_id), invalidate=True)
    except Exception:
        return False
    return True


def avatar_url(user):
    if not user.avatar_version or not is_configured():
        return None

    _configure()
    from cloudinary.utils import cloudinary_url as build_url

    size = settings.AVATAR_RENDER_SIZE
    url, _ = build_url(
        public_id_for(user.id),
        version=user.avatar_version,
        width=size,
        height=size,
        crop="fill",
        gravity="auto",
        fetch_format="auto",
        quality="auto",
        secure=True,
    )
    return url

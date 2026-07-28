import time

from django.conf import settings


UPLOAD_ENDPOINT = "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"

AVATARS = "avatars"
GROUPS = "groups"
CHECKINS = "checkins"


def is_configured():
    return bool(settings.CLOUDINARY_URL)


def _configure():
    import cloudinary

    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL, secure=True)
    return cloudinary


def public_id_for(folder, object_id):
    return f"{folder}/{object_id}"


def upload_signature(folder, object_id):
    cloudinary = _configure()
    from cloudinary.utils import api_sign_request

    params = {
        "public_id": public_id_for(folder, object_id),
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


def destroy_image(folder, object_id):
    _configure()
    from cloudinary.uploader import destroy

    try:
        destroy(public_id_for(folder, object_id), invalidate=True)
    except Exception:
        return False
    return True


def image_url(folder, object_id, version, width, height=None, crop="fill"):
    if not version or not is_configured():
        return None

    _configure()
    from cloudinary.utils import cloudinary_url as build_url

    options = {
        "version": version,
        "width": width,
        "crop": crop,
        "fetch_format": "auto",
        "quality": "auto",
        "secure": True,
    }
    if height is not None:
        options["height"] = height
        options["gravity"] = "auto"

    url, _ = build_url(public_id_for(folder, object_id), **options)
    return url


def avatar_url(user):
    size = settings.AVATAR_RENDER_SIZE
    return image_url(AVATARS, user.id, user.avatar_version, size, size)


def group_image_url(group):
    size = settings.GROUP_IMAGE_RENDER_SIZE
    return image_url(GROUPS, group.id, group.image_version, size, size)


def checkin_image_url(checkin):
    return image_url(
        CHECKINS,
        checkin.id,
        checkin.image_version,
        settings.CHECKIN_PHOTO_RENDER_SIZE,
        crop="limit",
    )

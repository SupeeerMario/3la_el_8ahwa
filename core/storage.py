import uuid
from datetime import timedelta

from django.conf import settings


AVATAR_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def is_configured():
    return bool(settings.FIREBASE_STORAGE_BUCKET and settings.FIREBASE_CREDENTIALS_FILE)


def _bucket():
    from google.cloud import storage

    client = storage.Client.from_service_account_json(settings.FIREBASE_CREDENTIALS_FILE)
    return client.bucket(settings.FIREBASE_STORAGE_BUCKET)


def avatar_path_for(user_id, content_type):
    extension = AVATAR_CONTENT_TYPES[content_type]
    return f"avatars/{user_id}/{uuid.uuid4().hex}.{extension}"


def signed_upload_url(path, content_type, content_length):
    blob = _bucket().blob(path)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=settings.AVATAR_UPLOAD_URL_TTL),
        method="PUT",
        content_type=content_type,
        headers={"Content-Length": str(content_length)},
    )


def delete_object(path):
    try:
        _bucket().blob(path).delete()
    except Exception:
        return False
    return True


def public_url(path):
    if not path or not settings.FIREBASE_STORAGE_BUCKET:
        return None
    return f"https://storage.googleapis.com/{settings.FIREBASE_STORAGE_BUCKET}/{path}"

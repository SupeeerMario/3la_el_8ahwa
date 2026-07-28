import base64
import binascii
from datetime import datetime


def encode(message):
    raw = f"{message.created_at.isoformat()}|{message.id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode(cursor):
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        stamp, _, message_id = raw.rpartition("|")
        return datetime.fromisoformat(stamp), int(message_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None

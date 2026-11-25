"""Passwort-Auth: statelesses HMAC-Cookie, kein Server-Session-State.

Das Cookie ist HMAC_SHA256(Passwort, "whispirvm-auth-v1") – also
deterministisch und ohne Server-State pruefbar. Passwortwechsel
invalidiert alle Cookies automatisch. Passwort kommt aus
/opt/whispirvm/.env (WHISPIRVM_PASSWORD), nie aus committeten Dateien.
"""

import hashlib
import hmac
import os

COOKIE_NAME = "whispirvm_session"
_TOKEN_MSG = b"whispirvm-auth-v1"
MAX_AGE = 30 * 24 * 3600          # 30 Tage

_password = os.environ.get("WHISPIRVM_PASSWORD", "")


def _token() -> str:
    return hmac.new(_password.encode(), _TOKEN_MSG,
                    hashlib.sha256).hexdigest()


def check_password(candidate: str) -> bool:
    return bool(_password) and hmac.compare_digest(candidate, _password)


def valid_cookie(value: str | None) -> bool:
    return (bool(_password) and bool(value)
            and hmac.compare_digest(value, _token()))


def make_cookie() -> str:
    return _token()

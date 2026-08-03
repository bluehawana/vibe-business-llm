"""Staff login for the screens that aren't for guests.

One shared password per installation, not per-user accounts: the people who need
in are the two of you plus whoever is on shift, and a kitchen iPad has to stay
logged in for months without anyone remembering a username.

Fail closed. With no password set the staff screens refuse to serve at all,
rather than quietly staying open — the whole point is that this survives being
put behind a public URL.
"""

import hashlib
import hmac
import os
import secrets

STAFF_PASSWORD = os.environ.get("VIBE_STAFF_PASSWORD", "")

COOKIE = "vibe_staff"
# An iPad bolted to a wall should not be logged out mid-service. Changing the
# password is what revokes access, not the clock.
COOKIE_MAX_AGE = 180 * 24 * 3600


def configured() -> bool:
    return bool(STAFF_PASSWORD)


def _derive(purpose: str) -> str:
    """Purpose-bound derivative of the password. Neither the session cookie nor
    the printer key reveals the password, and rotating it invalidates both."""
    return hmac.new(STAFF_PASSWORD.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def session_token() -> str:
    return _derive("staff-session")


def printer_key() -> str:
    """A thermal printer can't fill in a login form — it polls a fixed URL. It
    gets its own key so the password never sits in a printer's config."""
    return _derive("printer")[:20]


def check_password(supplied: str) -> bool:
    return configured() and secrets.compare_digest(supplied or "", STAFF_PASSWORD)


def valid_session(token: str | None) -> bool:
    return configured() and secrets.compare_digest(token or "", session_token())


def valid_printer_key(key: str | None) -> bool:
    return configured() and secrets.compare_digest(key or "", printer_key())

"""Secret storage backed by the macOS Keychain.

Same pattern as unblock_tracker/secrets.py: nothing sensitive is ever written
to a file this project tracks, so there is nothing for git or the Google
Drive backup to pick up. API tokens are keyed by platform name so several
platform credentials can coexist.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICE = "bug_spray"


def _key(platform: str) -> str:
    return f"{platform}_api_token"


def get(platform: str) -> str:
    """Return the stored token for `platform`, or "" if absent or locked."""
    try:
        return keyring.get_password(SERVICE, _key(platform)) or ""
    except KeyringError:
        return ""


def set(platform: str, value: str) -> None:  # noqa: A001
    """Store a token, or remove it when `value` is blank."""
    if value:
        keyring.set_password(SERVICE, _key(platform), value)
    else:
        delete(platform)


def delete(platform: str) -> None:
    try:
        keyring.delete_password(SERVICE, _key(platform))
    except KeyringError:
        pass


def backend_name() -> str:
    try:
        return type(keyring.get_keyring()).__module__
    except KeyringError:
        return "unavailable"

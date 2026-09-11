"""Password and recovery-code rules for local accounts (PRD A-2, A-3, A-6).

* At least 10 characters, and not one of the 100,000 most common breached
  passwords (data/common-passwords.txt). No composition rules: forced
  symbols and digits make passwords harder to remember and no harder to
  guess (NIST SP 800-63B §5.1.1.2).
* Hashed with Argon2id at OWASP's current minimum (m = 19 MiB, t = 2,
  p = 1). Never stored, logged or echoed in a recoverable form.
* A recovery code is 25 characters from Crockford's base32 — about 125 bits
  — so it is safe to store as a password-style hash and type in by hand.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
# Bounds the hashing work one request can demand.
MAX_LENGTH = 256

COMMON_PASSWORDS = Path(__file__).with_name("data") / "common-passwords.txt"

_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


class PasswordRejected(ValueError):
    """The message is shown to the owner as-is: plain words, a next step."""


@lru_cache(maxsize=1)
def _common() -> frozenset[str]:
    text = COMMON_PASSWORDS.read_text(encoding="utf-8", errors="ignore")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


def check_new_password(password: str, *, username: str = "", email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordRejected(
            f"Use at least {MIN_LENGTH} characters. A few ordinary words strung together "
            "works well and is easy to remember."
        )
    if len(password) > MAX_LENGTH:
        raise PasswordRejected(f"Use {MAX_LENGTH} characters or fewer.")
    lowered = password.lower()
    if lowered in _common():
        raise PasswordRejected(
            "That password is on lists of passwords stolen from other websites, so it's "
            "one of the first an attacker would try. Choose a different one."
        )
    personal = {username.lower(), email.lower(), email.split("@")[0].lower()} - {""}
    if lowered in personal:
        raise PasswordRejected("Don't use your name or email address as your password.")


def hash_secret(secret: str) -> str:
    return _HASHER.hash(secret)


def verify_secret(stored_hash: str | None, secret: str) -> bool:
    """Constant work whether or not an account exists: with no stored hash we
    still verify against a throwaway one, so timing can't reveal which
    usernames are real."""
    try:
        return _HASHER.verify(stored_hash or _dummy_hash(), secret) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _HASHER.check_needs_rehash(stored_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash(secrets.token_urlsafe(16))


# Crockford base32: no I, L, O or U, so nothing reads as another character.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_recovery_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(25))
    return "-".join(raw[i:i + 5] for i in range(0, 25, 5))


def normalise_recovery_code(typed: str) -> str:
    """What the owner types → the canonical form that was hashed. Spaces,
    dashes and case don't matter; O/I/L are read as the digits they look like."""
    cleaned = "".join(ch for ch in typed.upper() if ch.isalnum())
    cleaned = cleaned.replace("O", "0").replace("I", "1").replace("L", "1")
    return "-".join(cleaned[i:i + 5] for i in range(0, len(cleaned), 5))


def new_setup_code() -> str:
    """A one-time code the owner hands to a new person so they can set their
    own password (there is no mail server to send a link). Eight characters,
    short enough to read aloud, valid once and for a day (see accounts.py)."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"

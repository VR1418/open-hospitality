"""Password rules, hashing and recovery codes (PRD A-2, A-3, A-6) — no database."""

import hashlib
import time

import pytest

from usali.auth import AuthError
from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.passwords import (
    COMMON_PASSWORDS,
    PasswordRejected,
    check_new_password,
    hash_secret,
    new_recovery_code,
    normalise_recovery_code,
    verify_secret,
)

# Pinned when the list was fetched (2026-09-11) from SecLists'
# Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt (MIT).
# A changed file must be a deliberate, reviewed change.
COMMON_PASSWORDS_SHA256 = "c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0"


def test_the_bundled_list_is_the_one_we_pinned() -> None:
    digest = hashlib.sha256(COMMON_PASSWORDS.read_bytes()).hexdigest()
    assert digest == COMMON_PASSWORDS_SHA256


@pytest.mark.parametrize("password", ["password123", "qwertyuiop", "1234567890", "iloveyou12"])
def test_common_breached_passwords_are_refused(password: str) -> None:
    with pytest.raises(PasswordRejected, match="stolen"):
        check_new_password(password)


def test_short_passwords_are_refused_with_a_next_step() -> None:
    with pytest.raises(PasswordRejected, match="at least 10"):
        check_new_password("Tr0ub4dor")


def test_no_composition_rules_a_long_plain_phrase_is_fine() -> None:
    check_new_password("correct horse battery staple")


def test_your_own_email_is_not_a_password() -> None:
    with pytest.raises(PasswordRejected, match="email"):
        check_new_password("owner.hotel@example.com", email="owner.hotel@example.com")


def test_hashes_are_argon2id_and_verify() -> None:
    h = hash_secret("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert "m=19456,t=2,p=1" in h
    assert verify_secret(h, "correct horse battery staple")
    assert not verify_secret(h, "correct horse battery stapler")


def test_no_account_still_costs_a_full_hash_and_never_passes() -> None:
    start = time.perf_counter()
    assert verify_secret(None, "anything at all here") is False
    assert time.perf_counter() - start > 0.005  # a real Argon2 verify ran


def test_recovery_codes_are_long_and_forgiving_to_type() -> None:
    code = new_recovery_code()
    assert len(code.replace("-", "")) == 25
    typed = code.lower().replace("-", " ").replace("0", "o").replace("1", "l")
    assert normalise_recovery_code(typed) == code


def test_a_token_whose_session_ended_is_refused() -> None:
    issuer = LocalIssuer.from_pem(LocalIssuer.generate_pem())
    user = DesktopUser(subject="s1", username="owner", roles=("org_admin",), org_alias="g")
    live = {"sid-live"}
    verifier = issuer.verifier(session_is_live=lambda sid, sub: sid in live and sub == "s1")
    assert verifier.verify(issuer.mint(user, session_id="sid-live")).subject == "s1"
    with pytest.raises(AuthError):
        verifier.verify(issuer.mint(user, session_id="sid-revoked"))
    with pytest.raises(AuthError):
        verifier.verify(issuer.mint(user))  # no session at all

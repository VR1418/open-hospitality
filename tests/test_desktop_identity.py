"""The desktop issuer mints what upstream's TokenVerifier accepts — and only that."""

import time

import pytest

from usali.auth import AuthError
from usali.desktop.identity import DesktopUser, LocalIssuer

OWNER = DesktopUser(
    subject="desktop-owner", username="owner", roles=("org_admin",), org_alias="pilot-hotel-group"
)


@pytest.fixture(scope="module")
def issuer() -> LocalIssuer:
    return LocalIssuer.from_pem(LocalIssuer.generate_pem())


def test_minted_token_verifies_through_the_upstream_verifier(issuer: LocalIssuer) -> None:
    principal = issuer.verifier().verify(issuer.mint(OWNER))
    assert principal.subject == "desktop-owner"
    assert principal.username == "owner"
    assert principal.roles == frozenset({"org_admin"})
    # An ALIAS, never an id: require_active_org resolves it through the DB.
    assert principal.org_aliases == frozenset({"pilot-hotel-group"})


def test_a_token_from_another_install_is_refused(issuer: LocalIssuer) -> None:
    stranger = LocalIssuer.from_pem(LocalIssuer.generate_pem())
    with pytest.raises(AuthError):
        issuer.verifier().verify(stranger.mint(OWNER))


def test_an_expired_token_is_refused(issuer: LocalIssuer) -> None:
    # Beyond the verifier's 60s clock-skew leeway.
    stale = issuer.mint(OWNER, now=int(time.time()) - issuer.ttl_seconds - 120)
    with pytest.raises(AuthError):
        issuer.verifier().verify(stale)


def test_the_key_id_is_stable_across_reloads() -> None:
    pem = LocalIssuer.generate_pem()
    assert LocalIssuer.from_pem(pem).kid == LocalIssuer.from_pem(pem).kid

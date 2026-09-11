"""Desktop sign-in: one-time launch codes, loopback-only hosts."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.session_api import LaunchCodes, install

OWNER = DesktopUser(
    subject="desktop-owner", username="owner", roles=("org_admin",), org_alias="pilot-hotel-group"
)
LOCAL = "http://127.0.0.1:47100"


@pytest.fixture(scope="module")
def issuer() -> LocalIssuer:
    return LocalIssuer.from_pem(LocalIssuer.generate_pem())


def _app(issuer: LocalIssuer, codes: LaunchCodes) -> FastAPI:
    app = FastAPI()
    install(app, issuer=issuer, user=OWNER, codes=codes)
    return app


def test_a_launch_code_buys_exactly_one_session(issuer: LocalIssuer) -> None:
    codes = LaunchCodes()
    client = TestClient(_app(issuer, codes), base_url=LOCAL)
    code = codes.issue()

    first = client.post("/api/desktop/session", json={"code": code})
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["expires_in"] == issuer.ttl_seconds
    assert issuer.verifier().verify(body["access_token"]).subject == "desktop-owner"

    again = client.post("/api/desktop/session", json={"code": code})
    assert again.status_code == 401
    # Principle 5: the refusal names the next step.
    assert "icon" in again.json()["detail"]


def test_an_unknown_code_is_refused(issuer: LocalIssuer) -> None:
    client = TestClient(_app(issuer, LaunchCodes()), base_url=LOCAL)
    assert client.post("/api/desktop/session", json={"code": "guess"}).status_code == 401


def test_a_code_expires() -> None:
    now = [1000.0]
    codes = LaunchCodes(ttl_seconds=120, clock=lambda: now[0])
    code = codes.issue()
    now[0] += 121
    assert codes.redeem(code) is False


def test_a_non_loopback_host_is_refused(issuer: LocalIssuer) -> None:
    # DNS rebinding: a page on a hostname that resolves to 127.0.0.1 still
    # sends ITS hostname in Host — which is what gives it away.
    codes = LaunchCodes()
    client = TestClient(_app(issuer, codes), base_url="http://rebind.attacker.example:47100")
    response = client.post("/api/desktop/session", json={"code": codes.issue()})
    assert response.status_code == 400


def test_no_cors_headers_are_ever_sent(issuer: LocalIssuer) -> None:
    codes = LaunchCodes()
    client = TestClient(_app(issuer, codes), base_url=LOCAL)
    response = client.post(
        "/api/desktop/session",
        json={"code": codes.issue()},
        headers={"Origin": "https://attacker.example"},
    )
    assert "access-control-allow-origin" not in response.headers

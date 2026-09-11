"""Launch codes and the loopback lock (session_api) — no database."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from usali.desktop.session_api import LaunchCodes, install

LOCAL = "http://127.0.0.1:47100"


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    install(app, codes=LaunchCodes())
    return app


def test_a_launch_code_works_exactly_once() -> None:
    codes = LaunchCodes()
    code = codes.issue()
    assert codes.redeem(code) is True
    assert codes.redeem(code) is False
    assert codes.redeem("guess") is False


def test_a_launch_code_expires() -> None:
    now = [1000.0]
    codes = LaunchCodes(ttl_seconds=120, clock=lambda: now[0])
    code = codes.issue()
    now[0] += 121
    assert codes.redeem(code) is False


def test_a_non_loopback_host_is_refused() -> None:
    # DNS rebinding: a page on a hostname that resolves to 127.0.0.1 still
    # sends ITS hostname in Host — which is what gives it away.
    assert TestClient(_app(), base_url=LOCAL).get("/api/ping").status_code == 200
    rebound = TestClient(_app(), base_url="http://rebind.attacker.example:47100")
    assert rebound.get("/api/ping").status_code == 400


def test_no_cors_headers_are_ever_sent() -> None:
    response = TestClient(_app(), base_url=LOCAL).get(
        "/api/ping", headers={"Origin": "https://attacker.example"}
    )
    assert "access-control-allow-origin" not in response.headers

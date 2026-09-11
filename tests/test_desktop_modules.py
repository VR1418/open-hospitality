"""ModuleRegistry and the create_app mount seam (ADR-D3) — no database needed:
route tables are built at construction, and engines connect lazily."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from usali.desktop.identity import LocalIssuer
from usali.desktop.modules import (
    ALWAYS_MOUNTED,
    HOSTED_ONLY,
    MODULES,
    mount_predicate,
    resolve,
)
from usali.keycloak_admin import InMemoryKeycloakAdmin
from usali.photo_store import InMemoryPhotoStore
from usali.server import create_app


@pytest.fixture(scope="module")
def issuer() -> LocalIssuer:
    return LocalIssuer.from_pem(LocalIssuer.generate_pem())


def _app(tmp_path: Path, issuer: LocalIssuer, mount: object = None) -> FastAPI:
    return create_app(
        inbox_dir=tmp_path / "inbox",
        processed_dir=tmp_path / "read",
        failed_dir=tmp_path / "unreadable",
        dist_dir=tmp_path / "no-portal",
        token_verifier=issuer.verifier(),
        keycloak_admin=InMemoryKeycloakAdmin(),
        photo_store=InMemoryPhotoStore(),
        mount=mount,  # type: ignore[arg-type]
    )


def _mounted(client: TestClient, method: str, path: str) -> bool:
    """Asked anonymously, a MOUNTED route refuses (401 at the operator gate,
    415/422 on the public ones) before anything touches a database; an
    UNMOUNTED one is a 404 — nothing is listening. That difference is the
    whole promise of ADR-D3, so it is what these tests read, rather than
    FastAPI's (private, version-dependent) route-table internals."""
    return client.request(method, path).status_code != 404


def test_the_registry_accounts_for_every_surface_create_app_mounts(
    tmp_path: Path, issuer: LocalIssuer,
) -> None:
    asked: list[str] = []

    def record(surface: str) -> bool:
        asked.append(surface)
        return True

    _app(tmp_path, issuer, record)
    owned = [s for m in MODULES for s in m.surfaces]
    assert len(owned) == len(set(owned)), "a surface belongs to two modules"
    # A router added upstream fails here until someone decides which module
    # it belongs to — it can never ride in unowned, with no limitations text.
    assert set(asked) == set(owned) | HOSTED_ONLY | ALWAYS_MOUNTED


def test_every_module_publishes_what_it_cannot_do() -> None:
    # PRD L-4: a module without a limitations entry does not ship.
    for module in MODULES:
        assert module.limitations, module.id
        assert all(lim.text.strip() for lim in module.limitations), module.id


def test_resolve_keeps_the_core_on_and_the_unbuilt_off() -> None:
    assert resolve(None) == frozenset({"accounting"})
    assert resolve([]) == frozenset({"accounting"})  # the core cannot be turned off
    assert resolve(["payroll"]) == frozenset({"accounting", "payroll"})
    assert resolve(["utilities", "made-up"]) == frozenset({"accounting"})


PAYROLL_ROUTES = (
    ("GET", "/api/timecards"),
    ("GET", "/api/schedule/templates"),
    ("GET", "/api/payroll/runs"),
    ("GET", "/api/kiosk-devices"),
)
HOSTED_ROUTES = (("POST", "/api/signup/request"), ("POST", "/api/preview"))
CORE_ROUTES = (("GET", "/api/sos"), ("GET", "/api/me"), ("POST", "/ingest"))


def test_payroll_off_means_its_routes_are_not_mounted_at_all(
    tmp_path: Path, issuer: LocalIssuer,
) -> None:
    client = TestClient(_app(tmp_path, issuer, mount_predicate({"accounting"})))
    for method, path in PAYROLL_ROUTES + HOSTED_ROUTES:
        assert not _mounted(client, method, path), path
    # The core, and the identity call the portal cannot live without.
    for method, path in CORE_ROUTES:
        assert _mounted(client, method, path), path


def test_payroll_on_mounts_its_routes_and_still_never_the_hosted_ones(
    tmp_path: Path, issuer: LocalIssuer,
) -> None:
    client = TestClient(_app(tmp_path, issuer, mount_predicate({"accounting", "payroll"})))
    for method, path in PAYROLL_ROUTES + CORE_ROUTES:
        assert _mounted(client, method, path), path
    for method, path in HOSTED_ROUTES:
        assert not _mounted(client, method, path), path


def test_with_the_portal_mounted_an_unmounted_route_is_still_a_404(
    tmp_path: Path, issuer: LocalIssuer,
) -> None:
    """The desktop serves the portal from the same app, and the portal's
    history fallback must not paper over an absent route. On Windows it used
    to: StaticFiles hands over `api\\nope`, the "/"-based API check missed,
    and an unmounted payroll route answered 200 with the portal page."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>portal</html>")
    app = create_app(
        inbox_dir=tmp_path / "inbox", processed_dir=tmp_path / "read",
        failed_dir=tmp_path / "unreadable", dist_dir=dist,
        token_verifier=issuer.verifier(), keycloak_admin=InMemoryKeycloakAdmin(),
        photo_store=InMemoryPhotoStore(), mount=mount_predicate({"accounting"}),
    )
    client = TestClient(app)
    assert client.get("/api/timecards").status_code == 404
    assert client.post("/api/signup/request").status_code == 404
    assert client.post("/api/definitely-not-a-route").status_code == 404
    assert client.get("/.git/HEAD").status_code == 404
    deep_link = client.get("/coverage")
    assert deep_link.status_code == 200 and "portal" in deep_link.text
    assert client.get("/api/me").status_code == 401  # mounted: the gate answers


def test_upstreams_default_still_mounts_everything(tmp_path: Path, issuer: LocalIssuer) -> None:
    client = TestClient(_app(tmp_path, issuer))
    for method, path in PAYROLL_ROUTES + HOSTED_ROUTES + CORE_ROUTES:
        assert _mounted(client, method, path), path

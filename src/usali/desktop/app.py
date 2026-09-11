"""The desktop launcher: one double-click to a running, signed-in portal.

    oh-desktop                      # what the app bundle runs
    oh-desktop --sample-data        # developers: load the pilot's sample reports
    oh-desktop --no-tray            # a console window instead of a tray icon

Start: find or create the owner's folders → start the bundled Postgres →
bring the database up to date → serve the API and the built portal on
127.0.0.1 → watch "Drop reports here" → open the browser, signed in.
Quit (tray menu, or Ctrl+C): stop the watcher, the server, then Postgres.

Everything the engine reads from `Settings` is set in env before the engine
is imported and configured, so the engine runs exactly as upstream wrote it
— the launcher never patches it.
"""

import argparse
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from usali.desktop import session_api
from usali.desktop.bootstrap import (
    DesktopKeys,
    KeysMissing,
    NeedsUpgradeConsent,
    app_url,
    load_sample_data,
    owner_url,
    prepare_database,
)
from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.intake import ReportIntake
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import (
    PgCluster,
    PostgresFailed,
    PostgresNotFound,
    find_bin_dir,
    free_port,
)

_LOG = logging.getLogger("usali.desktop")

API_PREFERRED_PORT = 47100
PG_PREFERRED_PORT = 47101
SIGNIN_PATH = "/desktop-signin"

# The one person this install belongs to, until M2 brings accounts. The
# alias is the founding org's (property_registry.DEFAULT_ORG_ALIAS) — the
# key `require_active_org` resolves through the organization table. The
# role is upstream's org_admin, unchanged (PRD A-8).
OWNER = DesktopUser(
    subject="desktop-owner",
    username="owner",
    roles=("org_admin",),
    org_alias="pilot-hotel-group",
)


def resource_root() -> Path:
    """Where migrations/, mapping/, the portal build and the Postgres
    binaries are: inside the PyInstaller bundle, or the repo checkout."""
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else Path(__file__).resolve().parents[3]


def _configure_logging(log_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "open-hospitality.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(file_handler)
    if sys.stderr is not None:  # a windowed build has no console at all
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
    logging.getLogger("usali").setLevel(logging.INFO)


def _configure_engine_env(paths: DesktopPaths, keys: DesktopKeys, *, url: str, api_port: int) -> None:
    os.environ.update(
        {
            # Not "prod": prod demands an HSM-backed opener this edition has no
            # HSM for. The dev-default secrets prod exists to refuse are never
            # used here — every key below is generated per install.
            "USALI_ENV": "local",
            "USALI_DB_URL": url,
            "USALI_INBOX_DIR": str(paths.uploads),
            "USALI_PROCESSED_DIR": str(paths.read_folder),
            "USALI_FAILED_DIR": str(paths.unreadable_folder),
            "USALI_PHOTO_STORE_DIR": str(paths.punch_photos),
            "USALI_PHOTO_STORE_GCS_BUCKET": "",
            "USALI_FIELD_ENCRYPTION_KEY": keys.field_encryption_key,
            "USALI_PII_HPKE_PRIVATE_KEY": keys.pii_hpke_private_key,
            "USALI_PII_HPKE_KEY_ID": "desktop-1",
            "USALI_PROVISIONER_DB_PASSWORD": keys.db_provisioner_password,
            "USALI_PUBLIC_BASE_URL": f"http://127.0.0.1:{api_port}",
            "USALI_NOTIFIER": "console",
            "USALI_CRM_PROVIDER": "",
            "USALI_BIOMETRIC_MATCHING_ENABLED": "false",
        }
    )


def build_app(
    paths: DesktopPaths, issuer: LocalIssuer, codes: session_api.LaunchCodes, dist: Path
) -> FastAPI:
    # Upstream's own SPA static handler, reused rather than copied.
    from usali.server import _SpaStaticFiles, create_app

    app = create_app(
        inbox_dir=paths.uploads,
        processed_dir=paths.read_folder,
        failed_dir=paths.unreadable_folder,
        token_verifier=issuer.verifier(),
        # A directory that never exists, so create_app mounts no SPA: its
        # catch-all mount must come AFTER desktop sign-in is routed, below.
        dist_dir=paths.system_root / "no-portal-here",
    )
    session_api.install(app, issuer=issuer, user=OWNER, codes=codes)
    if dist.is_dir():
        app.mount("/", _SpaStaticFiles(directory=dist, html=True), name="spa")
    else:
        _LOG.warning("no portal build at %s; serving the API only", dist)
    return app


class _ApiServer:
    def __init__(self, app: FastAPI, port: int) -> None:
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_config=None, access_log=False
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="api", daemon=True)

    def start(self, timeout: float = 30) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the local server did not start; see the log")
            time.sleep(0.05)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def _reveal(folder: Path) -> None:
    if sys.platform == "win32":
        getattr(os, "startfile")(str(folder))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)


def _icon_image() -> Any:
    from PIL import Image, ImageDraw, ImageFont

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=(24, 54, 92, 255))
    try:
        font: Any = ImageFont.load_default(size=28)
    except TypeError:  # Pillow without sized default fonts
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), "OH", font=font, fill="white", anchor="mm")
    return image


def _run_tray(open_books: Callable[[], None], show_reports: Callable[[], None]) -> bool:
    """Blocks until Quit. False when no tray library is installed."""
    try:
        import pystray  # type: ignore[import-untyped]  # LGPL-3.0; see NOTICE
    except ImportError:
        return False
    menu = pystray.Menu(
        pystray.MenuItem("Open my books", lambda: open_books(), default=True),
        pystray.MenuItem("Show my reports folder", lambda: show_reports()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Open Hospitality", lambda icon: icon.stop()),
    )
    pystray.Icon("open-hospitality", _icon_image(), "Open Hospitality", menu).run()
    return True


def _run_console(base_url: str) -> None:
    print(f"Open Hospitality is running at {base_url}")
    print("Press Ctrl+C to stop it.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def run(args: argparse.Namespace) -> int:
    paths = DesktopPaths.default()
    paths.ensure()
    _configure_logging(paths.logs)
    resources = resource_root()
    # Upstream resolves some mapping paths against the working directory
    # (scripts/e2e_backend.py does the same chdir, for the same reason).
    os.chdir(resources)

    cluster = PgCluster(
        bin_dir=find_bin_dir(resources),
        data_dir=paths.database,
        log_file=paths.logs / "database.log",
    )
    keys = DesktopKeys.load_or_create(paths.keys_file, database_exists=cluster.exists())
    if not cluster.exists():
        _LOG.info("first run: creating the database in %s", paths.database)
        cluster.init(keys.db_owner_password)
    pg_port = free_port(PG_PREFERRED_PORT)
    cluster.start(pg_port)
    try:
        api_port = free_port(API_PREFERRED_PORT)
        serving_url = app_url(pg_port, keys)
        _configure_engine_env(paths, keys, url=serving_url, api_port=api_port)
        outcome = prepare_database(
            port=pg_port, keys=keys, resources=resources, state_file=paths.state_file,
            user=OWNER, allow_upgrade=args.upgrade_database,
        )
        _LOG.info("database %s", outcome)
        if args.sample_data:
            n = load_sample_data(owner_url(pg_port, keys), resources, paths.drop_folder)
            _LOG.info("sample data: %d reports copied to %s", n, paths.drop_folder)

        issuer = LocalIssuer.from_pem(keys.issuer_private_key_pem)
        codes = session_api.LaunchCodes()
        app = build_app(paths, issuer, codes, resources / "frontend" / "dist-desktop")
        server = _ApiServer(app, api_port)
        server.start()

        from usali.db import make_engine, make_session_factory
        from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

        # The intake writes as the serving role, bound to the founding org —
        # the same walls as every request (L2), never the owner's session.
        intake = ReportIntake(
            OrgBoundSessionFactory(make_session_factory(make_engine(serving_url)), FOUNDING_ORG_ID),
            drop_folder=paths.drop_folder,
            read_folder=paths.read_folder,
            unreadable_folder=paths.unreadable_folder,
        )
        intake.start()

        base_url = f"http://127.0.0.1:{api_port}"

        def open_books() -> None:
            webbrowser.open(f"{base_url}{SIGNIN_PATH}#code={codes.issue()}")

        _LOG.info("ready at %s; reports folder %s", base_url, paths.drop_folder)
        if args.no_browser:
            # Printed, never logged: the code is a one-time secret, and the
            # console belongs to whoever started the app; the log file may be
            # sent to us as diagnostics.
            print(f"Sign in (one use, two minutes): {base_url}{SIGNIN_PATH}#code={codes.issue()}",
                  flush=True)
        else:
            open_books()
        try:
            if args.no_tray or not _run_tray(open_books, lambda: _reveal(paths.owner_root)):
                _run_console(base_url)
        finally:
            intake.stop()
            server.stop()
    finally:
        cluster.stop()
        _LOG.info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oh-desktop", description="Open Hospitality desktop")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--no-tray", action="store_true", help="console window, no tray icon")
    parser.add_argument(
        "--sample-data", action="store_true",
        help="developers: load the pilot's sample properties and reports",
    )
    parser.add_argument(
        "--upgrade-database", action="store_true",
        help="allow this version to update an existing database (make a copy first)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (PostgresNotFound, PostgresFailed, KeysMissing, NeedsUpgradeConsent) as exc:
        # Expected refusals: the message already names the next step.
        _LOG.error("%s", exc)
        print(f"\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

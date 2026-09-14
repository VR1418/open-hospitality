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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from usali.desktop import (
    accounts_api,
    ai_api,
    backup_api,
    codes_api,
    folders_api,
    mail_api,
    modules_api,
    portfolio_api,
    rota_api,
    session_api,
    statements_api,
    update_api,
    welcome_api,
)
from usali.desktop import backup
from usali.desktop.mail import MailIntake
from usali.desktop.accounts import LocalAccountAdmin, SessionFactory
from usali.desktop.keystore import KeychainUnavailable, KeyStore, MemoryKeyStore, OsKeyStore, open_keys
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
from usali.desktop.modules import mount_predicate, resolve
from usali.desktop.paths import DesktopPaths
from usali.desktop.memory_notes import MemoryNotes
from usali.desktop.saved_reports import SavedReports
from usali.desktop import uninstall
from usali.desktop.window import SingleInstance, ensure_shortcuts, open_window
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
    paths: DesktopPaths,
    issuer: LocalIssuer,
    codes: session_api.LaunchCodes,
    dist: Path,
    *,
    enabled: frozenset[str],
    reload: Callable[[], None],
    sessions: SessionFactory,
    checker: accounts_api.SessionChecker,
    # The keychain the accounts API arms backups through (ADR-D4). Tests that
    # are not about backups leave it out and get one that forgets.
    store: KeyStore | None = None,
    # Reports by email (usali.desktop.mail). None in tests that are not about it.
    mail_intake: MailIntake | None = None,
) -> FastAPI:
    # Upstream's own SPA static handler, reused rather than copied.
    from usali.server import _SpaStaticFiles, create_app

    app = create_app(
        inbox_dir=paths.uploads,
        processed_dir=paths.read_folder,
        failed_dir=paths.unreadable_folder,
        # Given explicitly, not left to the environment: this is the factory
        # carrying the install's per-hotel code decisions, and without it the
        # REQUEST path — /ingest, the night-audit upload, the codes page —
        # would build its own from USALI_DB_URL and never see them.
        session_factory=sessions,
        # Upstream's verifier over the local key, plus "is this sign-in still live?"
        token_verifier=issuer.verifier(session_is_live=checker),
        # Upstream's onboarding creates and disables LOCAL logins through its
        # own Keycloak seam (ADR-D1).
        keycloak_admin=LocalAccountAdmin(sessions, org_alias=OWNER.org_alias),
        # A directory that never exists, so create_app mounts no SPA: its
        # catch-all mount must come AFTER desktop sign-in is routed, below.
        dist_dir=paths.system_root / "no-portal-here",
        # ADR-D3: a module that is off is not mounted at all.
        mount=mount_predicate(enabled),
    )
    session_api.install(app, codes=codes)
    accounts_api.install(
        app, issuer=issuer, codes=codes, sessions=sessions,
        org_alias=OWNER.org_alias, checker=checker,
        paths=paths, store=store or MemoryKeyStore(),
    )
    modules_api.install(app, enabled=enabled, reload=reload)
    welcome_api.install(app, paths=paths)
    portfolio_api.install(app)
    codes_api.install(app)
    # ADR-D3 again: with the AI module off, these routes do not exist at all,
    # which is what makes PRD AI-8 ("with AI disabled, every feature still
    # works") true by construction rather than by a flag somewhere.
    if "payroll" in enabled:
        rota_api.install(app)
    if "ai" in enabled:
        ai_api.install(app, paths=paths, store=store or MemoryKeyStore())
    update_api.install(app)
    folders_api.install(app, paths=paths)
    statements_api.install(app)
    mail_api.install(app, paths=paths, store=store or MemoryKeyStore(), intake=mail_intake)
    backup_api.install(app, paths=paths, store=store or MemoryKeyStore(), sessions=sessions)
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


class _Portal:
    """The local server, rebuildable in place. A module change builds a new
    app (with the new set mounted) and swaps it in on the SAME port, so the
    owner's browser tab and session carry straight on (PRD 5.1: modules
    change "without reinstalling" — and without restarting, either)."""

    def __init__(self, build: Callable[[], FastAPI], port: int) -> None:
        self._build = build
        self._port = port
        self._lock = threading.Lock()
        self._server: _ApiServer | None = None

    def _serve(self) -> _ApiServer:
        app = self._build()
        failure: Exception | None = None
        # The port was released a moment ago; give the OS a beat to agree.
        for _ in range(20):
            server = _ApiServer(app, self._port)
            try:
                server.start()
                return server
            except RuntimeError as exc:
                failure = exc
                time.sleep(0.25)
        raise RuntimeError("the local server did not come back") from failure

    def start(self) -> None:
        with self._lock:
            self._server = self._serve()

    def reload(self) -> None:
        # Called from inside a request's background task, which runs on the
        # very server being replaced — so the swap happens on its own thread.
        threading.Thread(target=self._reload, name="api-reload", daemon=True).start()

    def _reload(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.stop()
            self._server = self._serve()
        _LOG.info("modules changed; the local server was rebuilt")

    def stop(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.stop()
                self._server = None


def _reveal(folder: Path) -> None:
    if sys.platform == "win32":
        getattr(os, "startfile")(str(folder))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)


def _icon_image() -> Any:
    """The tray icon: the kit's app-icon — six equal dots on a dark rounded
    square, in the kit's ON-DARK palette, because a tray sits on whatever the
    desktop's own chrome is and the light reds go muddy there.

    Drawn rather than loaded so the packaged app carries no image file to lose,
    and supersampled 8x then reduced: Pillow's ellipse and rounded_rectangle
    have no anti-aliasing, and a 64px circle drawn directly has visibly ragged
    edges.
    """
    from PIL import Image, ImageDraw

    # docs/brand/logo/app-icon.svg, on a 132-unit box.
    BACKGROUND = (22, 24, 29, 255)
    RADIUS, DOT = 32, 11
    dots = (
        (66, 28, (255, 103, 93, 255)),    # red
        (97, 47, (255, 164, 86, 255)),    # orange
        (97, 85, (39, 198, 192, 255)),    # teal
        (66, 104, (103, 215, 210, 255)),  # teal soft
        (35, 85, (255, 110, 167, 255)),   # pink
        (35, 47, (255, 177, 207, 255)),   # pink soft
    )

    size, scale = 64, 8
    big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    unit = size * scale / 132
    draw.rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1),
        radius=RADIUS * unit,
        fill=BACKGROUND,
    )
    for cx, cy, colour in dots:
        draw.ellipse(
            ((cx - DOT) * unit, (cy - DOT) * unit, (cx + DOT) * unit, (cy + DOT) * unit),
            fill=colour,
        )
    # Pillow moved the filters under `Image.Resampling` in 9.1.
    return big.resize((size, size), Image.Resampling.LANCZOS)


#: The tray icon while it runs, so a quit request from another thread can stop it.
_TRAY: list[Any] = []


def _integrate_with_windows(paths: DesktopPaths) -> None:
    """Desktop and Start menu icons, and the entry under Settings > Apps."""
    from usali import __version__

    if os.environ.get("OH_DATA_DIR"):
        return  # a developer's or a test's separate books: not an installed copy

    ensure_shortcuts(paths.system_root)
    uninstall.register(Path(sys.executable), __version__)


def _start_uninstall() -> None:
    """The tray's Uninstall: a separate copy asks the questions, and asks
    this one to quit when the owner confirms."""
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable, "--uninstall"], close_fds=True)  # noqa: S603
    else:
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "usali.desktop.app", "--uninstall"], close_fds=True
        )


def _run_tray(
    open_books: Callable[[], None], show_reports: Callable[[], None],
    show_saved: Callable[[], None], start_uninstall: Callable[[], None],
) -> bool:
    """Blocks until Quit. False when no tray library is installed."""
    try:
        import pystray  # type: ignore[import-untyped]  # LGPL-3.0; see NOTICE
    except ImportError:
        return False
    menu = pystray.Menu(
        pystray.MenuItem("Open my books", lambda: open_books(), default=True),
        pystray.MenuItem("Show my reports folder", lambda: show_reports()),
        pystray.MenuItem("Show my saved reports", lambda: show_saved()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Uninstall Open Hospitality…", lambda: start_uninstall()),
        pystray.MenuItem("Quit Open Hospitality", lambda icon: icon.stop()),
    )
    # Only once the tray is certainly there: it is then how the app is reached.
    _hide_console()
    icon = pystray.Icon("open-hospitality", _icon_image(), "Open Hospitality", menu)
    _TRAY[:] = [icon]
    try:
        icon.run()
    finally:
        _TRAY.clear()
    return True


def _hide_console() -> None:
    """Put away the console window a packaged copy starts with, once the app
    is up and the tray icon is how it is reached. It stays for the start —
    where a refusal is printed — and for `--no-tray` runs, which live in it."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import ctypes

    console = ctypes.windll.kernel32.GetConsoleWindow()
    if console:
        ctypes.windll.user32.ShowWindow(console, 0)  # SW_HIDE


def _run_console(base_url: str, stopping: threading.Event) -> None:
    print(f"Open Hospitality is running at {base_url}")
    print("Press Ctrl+C to stop it.")
    try:
        while not stopping.wait(1):
            pass
    except KeyboardInterrupt:
        pass


def _restore(paths: DesktopPaths, archive: Path, recovery_code: str | None,
             store: KeyStore) -> int:
    """`--restore`: the books from a backup file, on a computer that has none.
    The recovery code is the key (ADR-D4); it is asked for rather than passed
    on a command line unless the caller chose to."""
    code = recovery_code or input("Your recovery code: ").strip()
    manifest = backup.restore(paths, archive, recovery_code=code, store=store)
    print(
        f"\nRestored your books from {archive.name} "
        f"(backed up {manifest.get('created_at', 'at an unknown time')}).\n"
        "Start Open Hospitality again to open them.\n",
        flush=True,
    )
    return 0


def run(args: argparse.Namespace) -> int:
    paths = DesktopPaths.default()
    paths.ensure()
    _configure_logging(paths.logs)
    store = OsKeyStore()
    if args.restore is not None:
        return _restore(paths, Path(args.restore), args.recovery_code, store)
    # Before anything touches the database: a second copy on the same folder
    # would try to start a second server on it. It asks the running copy to
    # open a window instead (usali.desktop.window).
    instance = SingleInstance(paths.system_root)
    if not instance.acquire():
        _LOG.info("already running; asked it to open a window")
        return 0
    try:
        return _serve(args, paths, store, instance)
    finally:
        instance.release()


def _serve(
    args: argparse.Namespace, paths: DesktopPaths, store: KeyStore, instance: SingleInstance,
) -> int:
    resources = resource_root()
    # Upstream resolves some mapping paths against the working directory
    # (scripts/e2e_backend.py does the same chdir, for the same reason).
    os.chdir(resources)

    cluster = PgCluster(
        bin_dir=find_bin_dir(resources),
        data_dir=paths.database,
        log_file=paths.logs / "database.log",
    )
    keys = open_keys(
        sealed=paths.sealed_keys_file, legacy=paths.keys_file, store=store,
        database_exists=cluster.exists(),
    )
    if not cluster.exists():
        _LOG.info("first run: creating the database in %s", paths.database)
        cluster.init(keys.db_owner_password)
    # The one moment the cluster is quiescent by construction (ADR-D4).
    backup.maybe_backup(paths, store=store, force=args.backup_now)
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

        from usali.db import make_engine, make_session_factory
        from usali.desktop.mapping_decisions import DecidingSessionFactory
        from usali.desktop.settings import read_modules
        from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

        serving_engine = make_engine(serving_url)
        # Wrapped ONCE, here, so every session downstream carries this
        # install's per-hotel code decisions: the request path, the folder
        # watch, the /ingest route and the night-audit upload all draw from
        # this factory, and `transform` reads the resolver off the session.
        serving_sessions = DecidingSessionFactory(make_session_factory(serving_engine))
        issuer = LocalIssuer.from_pem(keys.issuer_private_key_pem)
        codes = session_api.LaunchCodes()
        checker = accounts_api.SessionChecker(serving_sessions)
        dist = resources / "frontend" / "dist-desktop"

        # Reports by email land in the drop folder the intake below watches.
        mail_intake = MailIntake(
            OrgBoundSessionFactory(serving_sessions, FOUNDING_ORG_ID), paths.drop_folder,
            store=store, sealed=paths.sealed_keys_file,
        )

        def build() -> FastAPI:
            # Read on every (re)build: the stored choice is what gets mounted.
            with serving_sessions() as session:
                enabled = resolve(read_modules(session))
            _LOG.info("modules on: %s", ", ".join(sorted(enabled)))
            return build_app(
                paths, issuer, codes, dist, enabled=enabled, reload=portal.reload,
                sessions=serving_sessions, checker=checker, store=store,
                mail_intake=mail_intake,
            )

        portal = _Portal(build, api_port)
        portal.start()

        # The intake writes as the serving role, bound to the founding org —
        # the same walls as every request (L2), never the owner's session.
        intake = ReportIntake(
            OrgBoundSessionFactory(serving_sessions, FOUNDING_ORG_ID),
            drop_folder=paths.drop_folder,
            read_folder=paths.read_folder,
            unreadable_folder=paths.unreadable_folder,
        )
        intake.start()
        mail_intake.start()
        # Every night read becomes a daily summary PDF and the month's
        # accountant pack, whichever way the report arrived.
        saved = SavedReports(
            OrgBoundSessionFactory(serving_sessions, FOUNDING_ORG_ID), paths.saved_reports_folder
        )
        saved.start()
        # The AI helper's memory, mirrored as notes the owner can open in Obsidian.
        memory = MemoryNotes(
            OrgBoundSessionFactory(serving_sessions, FOUNDING_ORG_ID), paths.memory_folder
        )
        memory.start()

        base_url = f"http://127.0.0.1:{api_port}"

        def open_books() -> None:
            # Its own window, not a browser tab (usali.desktop.window).
            open_window(
                f"{base_url}{SIGNIN_PATH}#code={codes.issue()}", paths.system_root / "window"
            )

        _LOG.info("ready at %s; reports folder %s", base_url, paths.drop_folder)
        if args.no_browser:
            # Printed, never logged: the code is a one-time secret, and the
            # console belongs to whoever started the app; the log file may be
            # sent to us as diagnostics.
            print(f"Sign in (one use, two minutes): {base_url}{SIGNIN_PATH}#code={codes.issue()}",
                  flush=True)
        else:
            open_books()
        stopping = threading.Event()

        def quit_app() -> None:
            # From the uninstaller: stop the tray (or the console loop), which
            # unwinds through the `finally` blocks that stop the database.
            stopping.set()
            if _TRAY:
                _TRAY[0].stop()

        instance.serve(open_books, on_quit=quit_app)
        threading.Thread(
            target=_integrate_with_windows, args=(paths,), name="shortcuts", daemon=True
        ).start()
        try:
            if stopping.is_set():
                pass
            elif args.no_tray or not _run_tray(
                open_books, lambda: _reveal(paths.owner_root),
                lambda: _reveal(paths.saved_reports_folder), _start_uninstall,
            ):
                _run_console(base_url, stopping)
        finally:
            mail_intake.stop()
            memory.stop()
            saved.stop()
            intake.stop()
            portal.stop()
            serving_engine.dispose()
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
    parser.add_argument(
        "--backup-now", action="store_true",
        help="back up before opening, whenever the last backup was taken",
    )
    parser.add_argument(
        "--restore", metavar="FILE",
        help="restore your books from a backup file (this computer must have none)",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="remove Open Hospitality from this computer (asks before deleting any books)",
    )
    parser.add_argument(
        "--recovery-code", metavar="CODE",
        help="the recovery code that opens the backup, if you'd rather not be asked",
    )
    args = parser.parse_args(argv)
    if args.uninstall:
        paths = DesktopPaths.default()
        _configure_logging(paths.logs)
        return uninstall.run(paths, OsKeyStore(), Path(sys.executable))
    refusals = (PostgresNotFound, PostgresFailed, KeysMissing, KeychainUnavailable,
                backup.BackupError)
    try:
        try:
            return run(args)
        except NeedsUpgradeConsent as needs:
            # A newer version meeting older books. Reported from a tester's
            # machine: the console said so and closed before anyone could
            # read it, so the app "didn't open". Now it asks, and goes ahead
            # on a Yes — the backup runs first, as on every start.
            if args.upgrade_database or not _ask(
                "Update your books?",
                f"{needs}\n\nUpdate them now? A backup is taken first when backups are set up.",
                args,
            ):
                raise
            args.upgrade_database = True
            return run(args)
    except (*refusals, NeedsUpgradeConsent) as exc:
        # Expected refusals: the message already names the next step.
        _LOG.error("%s", exc)
        print(f"\n{exc}\n", file=sys.stderr)
        _tell("Open Hospitality couldn't start", str(exc), args)
        return 1


def _dialogs(args: argparse.Namespace) -> bool:
    """A packaged copy started from an icon has no console anyone reads;
    a --no-tray run (developers, the end-to-end walk) does."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False)) and not args.no_tray


def _ask(title: str, text: str, args: argparse.Namespace) -> bool:
    return uninstall.ask(title, text) if _dialogs(args) else False


def _tell(title: str, text: str, args: argparse.Namespace) -> None:
    if _dialogs(args):
        uninstall.tell(title, text)


if __name__ == "__main__":
    raise SystemExit(main())

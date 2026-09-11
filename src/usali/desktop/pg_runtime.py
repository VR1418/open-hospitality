"""The bundled PostgreSQL cluster: find the binaries, create, start, stop.

Real Postgres, not an embedded substitute. Row-level security is one of the
two tenancy walls (ADR-002), and the serving role must meet FORCE ROW LEVEL
SECURITY on the desktop exactly as it does in the cloud — a SQLite build
would quietly delete a wall.

The cluster listens on 127.0.0.1 only, with scram-sha-256 password auth and
no Unix socket. Its superuser (``usali``) mirrors the dev compose owner: it
migrates and seeds, and nothing that serves a request ever connects as it.
"""

import os
import platform
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

_EXE = ".exe" if sys.platform == "win32" else ""
# No console window flashing up behind the tray icon on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

SUPERUSER = "usali"
DATABASE = "usali"


class PostgresNotFound(RuntimeError):
    """The binaries are not where this build expects them."""


class PostgresFailed(RuntimeError):
    """initdb / pg_ctl refused; the message carries the tail of its output."""


def platform_tag() -> str:
    """`<os>-<arch>` naming the vendored binary directory. The fetch script
    imports this so the two can never disagree on a directory name."""
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine
    )
    os_name = {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")
    return f"{os_name}-{arch}"


def find_bin_dir(resource_root: Path) -> Path:
    candidates: list[Path] = []
    override = os.environ.get("OH_PG_BIN")
    if override:
        candidates.append(Path(override))
    candidates.append(resource_root / "vendor" / "postgres" / platform_tag() / "bin")
    for candidate in candidates:
        if (candidate / f"pg_ctl{_EXE}").is_file():
            return candidate
    raise PostgresNotFound(
        "The database engine is missing from this copy of Open Hospitality. "
        "If you are a developer, run `uv run python scripts/desktop/fetch_postgres.py` "
        "or set OH_PG_BIN to a PostgreSQL 16 bin/ folder. Looked in: "
        + ", ".join(str(c) for c in candidates)
    )


def free_port(preferred: int) -> int:
    """`preferred` if nothing holds it, else any free loopback port.

    A stable port is a convenience, not a contract: the browser's saved
    state is per-origin, so keeping the port keeps the owner's theme and
    table settings across launches when it can."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            bound: int = s.getsockname()[1]
            return bound
    raise PostgresFailed("no free local port")  # pragma: no cover — port 0 always binds


def _tail(path: Path, lines: int = 20) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log written)"


@dataclass
class PgCluster:
    bin_dir: Path
    data_dir: Path
    log_file: Path

    def _tool(self, name: str) -> str:
        return str(self.bin_dir / f"{name}{_EXE}")

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # An ambient PGDATA/PGPORT/PGPASSWORD from a developer's shell must
        # not steer the bundled cluster.
        for var in ("PGDATA", "PGPORT", "PGHOST", "PGUSER", "PGPASSWORD"):
            env.pop(var, None)
        return env

    def _run(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._env(),
            creationflags=_NO_WINDOW,
        )

    def exists(self) -> bool:
        return (self.data_dir / "PG_VERSION").is_file()

    def init(self, password: str) -> None:
        """Create the cluster. initdb removes its own half-made directory on
        failure, so nothing here ever deletes a data directory."""
        if self.exists():
            return
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        fd, pwfile = tempfile.mkstemp(prefix="oh-init-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(password)
            result = self._run(
                self._tool("initdb"),
                "-D", str(self.data_dir),
                "-U", SUPERUSER,
                "--pwfile", pwfile,
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
                timeout=300,
            )
        finally:
            os.unlink(pwfile)
        if result.returncode != 0:
            raise PostgresFailed(
                "Could not create the database.\n" + (result.stderr or result.stdout)[-2000:]
            )

    def is_running(self) -> bool:
        if not self.exists():
            return False
        return self._run(self._tool("pg_ctl"), "status", "-D", str(self.data_dir)).returncode == 0

    def start(self, port: int) -> None:
        # A launcher that crashed can leave its cluster running on a port we
        # no longer know; stop it and start clean on ours.
        if self.is_running():
            self.stop()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        options = f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories="
        # NOT capture_output: pg_ctl's detached postmaster can inherit our
        # pipe handles (on Windows especially) and hold them open for its whole
        # life, so waiting for EOF would hang the launcher. Output goes to the
        # server log instead, which is what we quote on failure.
        result = subprocess.run(
            [
                self._tool("pg_ctl"), "start",
                "-D", str(self.data_dir),
                "-l", str(self.log_file),
                "-w", "-t", "60",
                "-o", options,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            env=self._env(),
            creationflags=_NO_WINDOW | _NEW_GROUP,
            # Ctrl-C in a developer's terminal must reach the launcher, which
            # stops the cluster cleanly — not the postmaster directly.
            start_new_session=sys.platform != "win32",
        )
        if result.returncode != 0:
            raise PostgresFailed(
                "The database did not start. The end of its log:\n" + _tail(self.log_file)
            )

    def stop(self) -> None:
        if not self.exists():
            return
        self._run(
            self._tool("pg_ctl"), "stop", "-D", str(self.data_dir), "-m", "fast", "-w", "-t", "60",
            timeout=90,
        )


def db_url(*, port: int, user: str, password: str, database: str = DATABASE) -> str:
    return (
        f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@127.0.0.1:{port}/{database}"
    )

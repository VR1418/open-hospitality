"""Run everything CI would, here, in one command.

    uv run python scripts/desktop/check.py          # everything
    uv run python scripts/desktop/check.py --quick  # skip the slow engine suite
    uv run python scripts/desktop/check.py --list   # what it would run, and why

This exists because CI is not dispatching for this repository (see
docs/desktop/NEXT-STEPS.md). The checks are written; nothing runs them but a
person, so a person needs one command rather than six remembered ones.

**A check that did not run is not a check that passed.** Each one names what it
needs — Docker, the bundled PostgreSQL, npm — and a missing prerequisite is
reported as SKIPPED and fails the run. That is deliberate, and it is the rule
`usali gl-parity` already follows when it refuses to exit 0 over zero
properties checked: the desktop tests skip THEMSELVES when the cluster is
absent, so a silent gap would otherwise read as a clean pass. Use
`--allow-skips` when you mean it.
"""

import argparse
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def _have_docker() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker is not on PATH"
    done = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, check=False
    )
    return (done.returncode == 0), "docker is installed but not running"


def _have_cluster() -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from usali.desktop.pg_runtime import PostgresNotFound, find_bin_dir

        find_bin_dir(ROOT)
    except PostgresNotFound:
        return False, "run scripts/desktop/fetch_postgres.py"
    except Exception as exc:  # a broken checkout, not a missing cluster
        return False, str(exc)[:80]
    return True, ""


def _have_face() -> tuple[bool, str]:
    """Strict mypy resolves imports it will never run. `face_match.py` guards
    numpy and onnxruntime behind TYPE_CHECKING, but --strict still needs them
    installed, which is why CI syncs the face extra to type-check at all."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False, "uv sync --extra dev --extra desktop --extra face"
    return True, ""


def _have_npm() -> tuple[bool, str]:
    return (shutil.which("npm") is not None), "npm is not on PATH (Node 22+)"


def _desktop_tests() -> list[str]:
    """Globbed here rather than in the shell: PowerShell does not expand a
    glob for an external command, and CI runs this list under bash."""
    return sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_desktop_*.py"))


@dataclass
class Check:
    name: str
    argv: list[str]
    #: Where it runs. The portal's checks only work from frontend/.
    cwd: Path = ROOT
    #: What it needs, and what to do when that is missing.
    needs: Callable[[], tuple[bool, str]] | None = None
    #: Slow enough to be worth skipping while iterating.
    slow: bool = False
    #: Output that means "this passed without checking anything".
    hollow: str = ""
    # -- filled in by the run --
    status: str = "pending"
    seconds: float = 0.0
    note: str = ""
    output: str = field(default="", repr=False)


def checks() -> list[Check]:
    return [
        Check("lint (ruff)", ["uv", "run", "ruff", "check"]),
        Check(
            "types (mypy strict)",
            ["uv", "run", "mypy", "--strict", "src"],
            needs=_have_face,
        ),
        # The two suites PARTITION the tests: upstream's run on a container,
        # the desktop's on the real bundled cluster. Without the exclusion the
        # desktop ones would run twice, once here and once below.
        Check(
            "engine tests (Docker)",
            ["uv", "run", "pytest", "-q", "--ignore-glob=tests/test_desktop_*.py"],
            needs=_have_docker,
            slow=True,
        ),
        Check(
            "desktop tests (real bundled cluster)",
            ["uv", "run", "pytest", "-q", "-rs", *_desktop_tests()],
            needs=_have_cluster,
            slow=True,
            hollow="bundled Postgres not fetched",
        ),
        Check("portal types", ["npx", "tsc", "--noEmit"], cwd=FRONTEND, needs=_have_npm),
        Check("portal lint", ["npx", "oxlint"], cwd=FRONTEND, needs=_have_npm),
        Check("portal tests", ["npm", "test"], cwd=FRONTEND, needs=_have_npm, slow=True),
        # Not the same as `tsc --noEmit` above: the build's project references
        # pull in test files and fixtures that --noEmit skips, and a release
        # has already failed here with errors the type check passed.
        Check(
            "portal build", ["npm", "run", "build:desktop"], cwd=FRONTEND, needs=_have_npm
        ),
        # The owner's and the staff's month, through the real app on its own
        # books (scripts/desktop/e2e.py). The one check that runs the whole
        # thing end to end rather than a layer of it.
        Check(
            "end-to-end walk (this checkout)",
            ["uv", "run", "--extra", "desktop", "python", "scripts/desktop/e2e.py"],
            needs=_have_cluster,
            slow=True,
        ),
    ]


def run(check: Check) -> None:
    if check.needs is not None:
        ready, why = check.needs()
        if not ready:
            check.status, check.note = "skipped", why
            return
    started = time.monotonic()
    done = subprocess.run(
        check.argv, cwd=check.cwd, capture_output=True, text=True, check=False,
        shell=sys.platform == "win32",  # npx/npm are .cmd shims on Windows
    )
    check.seconds = time.monotonic() - started
    check.output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        check.status = "failed"
    elif check.hollow and check.hollow in check.output:
        check.status, check.note = "hollow", "passed without running the tests that matter"
    else:
        check.status = "passed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the slow suites")
    parser.add_argument(
        "--allow-skips", action="store_true",
        help="do not fail when something could not run",
    )
    parser.add_argument("--list", action="store_true", help="show the checks and exit")
    args = parser.parse_args()

    wanted = [c for c in checks() if not (args.quick and c.slow)]
    if args.list:
        for c in wanted:
            ready, why = c.needs() if c.needs else (True, "")
            print(f"  {c.name:38} {'ready' if ready else 'NOT READY - ' + why}")
        return 0

    for c in wanted:
        print(f"-> {c.name}", flush=True)
        run(c)
        mark = {"passed": "ok", "failed": "FAILED", "skipped": "skipped",
                "hollow": "HOLLOW"}[c.status]
        detail = f" - {c.note}" if c.note else ""
        print(f"  {mark} ({c.seconds:.0f}s){detail}", flush=True)
        if c.status in {"failed", "hollow"}:
            print(c.output[-4000:], file=sys.stderr)

    print()
    print("=" * 60)
    for c in wanted:
        print(f"  {c.status:8} {c.name}{(' - ' + c.note) if c.note else ''}")
    print("=" * 60)

    failed = [c for c in wanted if c.status in {"failed", "hollow"}]
    skipped = [c for c in wanted if c.status == "skipped"]
    if failed:
        print(f"\n{len(failed)} check(s) did not pass.")
        return 1
    if skipped and not args.allow_skips:
        print(
            f"\n{len(skipped)} check(s) could not run, so this is not a pass. "
            "Install what they need, or say --allow-skips if you meant it."
        )
        return 1
    print("\nEverything that ran, passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the desktop app folder: Postgres binaries → portal → PyInstaller.

    uv run --extra desktop --group build python scripts/desktop/build.py

Output: dist/Open Hospitality/ — on Windows, run "Open Hospitality.exe"
inside it. Unsigned (M1); signing and notarisation are M3.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def _version() -> str:
    text = (ROOT / "src" / "usali" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return found.group(1) if found else "dev"


def main() -> int:
    _run([sys.executable, str(ROOT / "scripts" / "desktop" / "fetch_postgres.py")])
    npm = shutil.which("npm")
    if npm is None:
        print("npm is required to build the portal (Node 20+)", file=sys.stderr)
        return 1
    # The sidebar's build stamp reads this; "build v0.1.0" tells a tester
    # which copy they have, where "build dev" told them nothing.
    _run([npm, "run", "build:desktop"], cwd=ROOT / "frontend",
         env={**os.environ, "VITE_BUILD_SHA": f"v{_version()}"})
    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        str(ROOT / "packaging" / "desktop" / "open-hospitality.spec"),
    ])
    print(f"built: {ROOT / 'dist' / 'Open Hospitality'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

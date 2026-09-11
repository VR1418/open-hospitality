"""Build the desktop app folder: Postgres binaries → portal → PyInstaller.

    uv run --extra desktop --group build python scripts/desktop/build.py

Output: dist/Open Hospitality/ — on Windows, run "Open Hospitality.exe"
inside it. Unsigned (M1); signing and notarisation are M3.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    _run([sys.executable, str(ROOT / "scripts" / "desktop" / "fetch_postgres.py")])
    npm = shutil.which("npm")
    if npm is None:
        print("npm is required to build the portal (Node 20+)", file=sys.stderr)
        return 1
    _run([npm, "run", "build:desktop"], cwd=ROOT / "frontend")
    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        str(ROOT / "packaging" / "desktop" / "open-hospitality.spec"),
    ])
    print(f"built: {ROOT / 'dist' / 'Open Hospitality'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

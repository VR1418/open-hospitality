"""Fetch the PostgreSQL binaries the desktop edition bundles.

Source: the zonky embedded-postgres binaries on Maven Central — stripped
PostgreSQL builds (bin/, lib/, share/; no pgAdmin, no installer) published
per platform. PostgreSQL itself is under the PostgreSQL License.

    uv run python scripts/desktop/fetch_postgres.py              # this machine
    uv run python scripts/desktop/fetch_postgres.py --platform darwin-arm64

Unpacks to vendor/postgres/<platform-tag>/ (gitignored), where
`usali.desktop.pg_runtime.find_bin_dir` and the PyInstaller spec look.

Integrity: every jar is checked against Maven Central's published SHA-1,
AND against the SHA-256 pinned below. A platform with no pin yet refuses
unless --allow-unpinned is given, and prints the value to pin — so a jar
that changes under the same version is caught, not trusted.
"""

import argparse
import hashlib
import io
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from usali.desktop.pg_runtime import platform_tag  # noqa: E402

VERSION = "16.15.0"
MAVEN = "https://repo1.maven.org/maven2/io/zonky/test/postgres"

# platform tag -> (Maven artifact id, pinned SHA-256 of the jar | None)
ARTIFACTS: dict[str, tuple[str, str | None]] = {
    # Pinned 2026-09-11 (first fetch; SHA-1 matched Maven Central).
    "windows-x86_64": (
        "embedded-postgres-binaries-windows-amd64",
        "51c7812dc1af47c9a2ccb64fe74efb88c515cff2da347ce72aab92b4cc8e1191",
    ),
    "darwin-arm64": ("embedded-postgres-binaries-darwin-arm64v8", None),
    "darwin-x86_64": ("embedded-postgres-binaries-darwin-amd64", None),
    "linux-x86_64": ("embedded-postgres-binaries-linux-amd64", None),
}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — fixed https host
        data: bytes = resp.read()
        return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", default=platform_tag(), choices=sorted(ARTIFACTS))
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument(
        "--allow-unpinned", action="store_true",
        help="accept a jar with no pinned SHA-256 (prints the value to pin)",
    )
    args = parser.parse_args()

    artifact, pinned = ARTIFACTS[args.platform]
    dest = REPO_ROOT / "vendor" / "postgres" / args.platform
    exe = ".exe" if args.platform.startswith("windows") else ""
    if (dest / "bin" / f"pg_ctl{exe}").is_file() and not args.force:
        print(f"already present: {dest}")
        return 0

    url = f"{MAVEN}/{artifact}/{VERSION}/{artifact}-{VERSION}.jar"
    print(f"downloading {url}")
    jar = _get(url)

    expected_sha1 = _get(url + ".sha1").decode().split()[0].strip().lower()
    if hashlib.sha1(jar).hexdigest() != expected_sha1:  # noqa: S324 — Maven's own checksum
        print("REFUSED: the jar does not match Maven Central's published SHA-1", file=sys.stderr)
        return 1
    sha256 = hashlib.sha256(jar).hexdigest()
    if pinned is None:
        print(f"no SHA-256 pinned for {args.platform}; this jar is {sha256}")
        if not args.allow_unpinned:
            print("REFUSED: pin it in ARTIFACTS, or re-run with --allow-unpinned", file=sys.stderr)
            return 1
    elif sha256 != pinned:
        print(f"REFUSED: SHA-256 {sha256} != pinned {pinned}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(io.BytesIO(jar)) as zf:
        txz_names = [n for n in zf.namelist() if n.endswith(".txz")]
        if len(txz_names) != 1:
            print(f"REFUSED: expected one .txz in the jar, found {txz_names}", file=sys.stderr)
            return 1
        txz = zf.read(txz_names[0])

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
        with tarfile.open(fileobj=io.BytesIO(txz), mode="r:xz") as tf:
            tf.extractall(tmp, filter="data")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, dest)
    (dest / "SOURCE.txt").write_text(f"{url}\nsha256 {sha256}\n")
    print(f"unpacked PostgreSQL {VERSION} to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

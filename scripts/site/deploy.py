"""Put ophosp.com on AWS from this checkout, in one command.

    uv run python scripts/site/deploy.py            # page, favicon, screens, the build zip
    uv run python scripts/site/deploy.py --no-zip   # everything but the zip

What it does, in order — the same steps site/DEPLOY.md walks through by hand:
  1. copies site/index.html, site/favicon.svg and site/screens/* to the bucket;
  2. copies the newest build zip from dist/ as download/Open-Hospitality-Windows.zip,
     after checking the SHA-256 on the page matches it;
  3. tells CloudFront to drop its cached copies, so the change shows within minutes.

It needs the AWS CLI signed in on this computer (`aws sts get-caller-identity`
works). Nothing here reads or stores a key: the CLI holds the sign-in, this
script only calls it. The CloudFront distribution id is read from the
environment (OPHOSP_DISTRIBUTION_ID) or from site/.deploy.local.json — a file
git ignores, so the id stays off the public record.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
BUCKET = "ophosp-site"
ZIP_NAME = "Open-Hospitality-Windows.zip"


def _aws() -> str:
    found = shutil.which("aws")
    if found is None:
        sys.exit("The AWS CLI isn't installed. Install it, sign in (aws configure sso, or "
                 "aws configure), then run this again.")
    return found


def _run(*args: str) -> str:
    print("+ aws", " ".join(args), flush=True)
    done = subprocess.run([_aws(), *args], capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(done.stderr.strip() or f"aws {args[0]} failed")
    return done.stdout


def _distribution() -> str | None:
    if os.environ.get("OPHOSP_DISTRIBUTION_ID"):
        return os.environ["OPHOSP_DISTRIBUTION_ID"]
    local = SITE / ".deploy.local.json"
    if local.is_file():
        value = json.loads(local.read_text(encoding="utf-8")).get("distribution_id")
        return str(value) if value else None
    return None


def _newest_zip() -> Path:
    zips = sorted(ROOT.glob("dist/Open Hospitality *.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        sys.exit("No build zip in dist/. Build one first (scripts/desktop/build.py), walk it, zip it.")
    return zips[-1]


def _page_sha() -> str:
    found = re.search(r'<code id="sha">([0-9a-f]{64})</code>', (SITE / "index.html").read_text(encoding="utf-8"))
    return found.group(1) if found else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-zip", action="store_true", help="skip the build zip")
    args = parser.parse_args()

    _run("sts", "get-caller-identity")
    _run("s3", "cp", str(SITE / "index.html"), f"s3://{BUCKET}/index.html",
         "--content-type", "text/html; charset=utf-8", "--cache-control", "max-age=300")
    _run("s3", "cp", str(SITE / "favicon.svg"), f"s3://{BUCKET}/favicon.svg",
         "--content-type", "image/svg+xml", "--cache-control", "max-age=86400")
    if (SITE / "screens").is_dir():
        _run("s3", "sync", str(SITE / "screens"), f"s3://{BUCKET}/screens", "--delete",
             "--content-type", "image/png", "--cache-control", "max-age=86400")

    # Documents linked from the page, kept with the docs they come from.
    for local, key in ((ROOT / "docs" / "desktop" / "AI-helper.pdf", "docs/ai-helper.pdf"),):
        if local.is_file():
            _run("s3", "cp", str(local), f"s3://{BUCKET}/{key}",
                 "--content-type", "application/pdf", "--cache-control", "max-age=300")

    if not args.no_zip:
        zip_path = _newest_zip()
        sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if sha != _page_sha():
            sys.exit(f"The page's SHA-256 doesn't match {zip_path.name} ({sha[:12]}…). "
                     "Update site/index.html first, so the download and the checksum agree.")
        _run("s3", "cp", str(zip_path), f"s3://{BUCKET}/download/{ZIP_NAME}",
             "--content-type", "application/zip", "--cache-control", "max-age=86400")

    dist = _distribution()
    if dist is None:
        print("Uploaded. No CloudFront distribution id known (OPHOSP_DISTRIBUTION_ID or "
              "site/.deploy.local.json), so invalidate it in the console: Invalidations › /*")
        return 0
    _run("cloudfront", "create-invalidation", "--distribution-id", dist, "--paths", "/*")
    print("Uploaded and invalidated. Give CloudFront a few minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

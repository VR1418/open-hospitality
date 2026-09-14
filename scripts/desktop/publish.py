"""Push this checkout's branches to the public repo, under the public identity.

    uv run python scripts/desktop/publish.py            # desktop/m1, desktop/prd, main
    uv run python scripts/desktop/publish.py --dry-run  # rewrite and verify, push nothing

The public repository (VR1418/ophosp-desktop) carries the same commits as the
private one, with one difference: every commit of ours is authored and
committed as "VR1418 <VR1418@users.noreply.github.com>", never a personal name
or address. Upstream's commits (csharp36/open-hospitality) are left exactly as
they are, hashes included — the fork is on their `main`, not a copy of it.

How: a fresh clone in a temporary folder, `git filter-branch` over only the
commits past upstream's main, a scan of the whole rewritten history for the
private names, and a push. The rewrite is deterministic — same inputs, same
hashes — so a second run changes nothing already published and the push is a
fast-forward. New commits made in this checkout already carry the public
identity (`git config user.name/email` here), so they pass through unchanged.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = "https://github.com/VR1418/ophosp-desktop.git"
UPSTREAM_MAIN = "bba21e7220fd51f2fd9d1e8b66efb9dad44054a9"
BRANCHES = ("desktop/m1", "desktop/prd")
NAME, EMAIL = "VR1418", "VR1418@users.noreply.github.com"
PUBLIC_REPO = "VR1418/ophosp-desktop"
#: Words that must not appear anywhere in the published history — personal
#: names, addresses, the private repository's name — and the private
#: repository's name to replace in site/index.html. They live in an ignored
#: local file, never here: this script is itself published.
#:   scripts/desktop/.publish.local.json
#:   {"private_words": ["…"], "private_repo": "OWNER/NAME"}
LOCAL = ROOT / "scripts" / "desktop" / ".publish.local.json"


def _git(*args: str, cwd: Path, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not LOCAL.is_file():
        sys.exit(f"{LOCAL.name} is missing (see the note at the top of this script).")
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    private_words = [str(w).lower() for w in local.get("private_words", [])]
    private_repo = str(local.get("private_repo", ""))
    if not private_words or not private_repo:
        sys.exit(f"{LOCAL.name} needs private_words and private_repo.")

    work = Path(tempfile.mkdtemp(prefix="ophosp-public-"))
    try:
        clone = work / "repo"
        _git("clone", "-q", str(ROOT), str(clone), cwd=work)
        for branch in BRANCHES + ("main",):
            if branch != "desktop/m1":
                _git("branch", "-q", branch, f"origin/{branch}", cwd=clone)
        _git("remote", "remove", "origin", cwd=clone)

        env_filter = (
            f'if [ "$GIT_AUTHOR_EMAIL" != "{EMAIL}" ] && [ "$GIT_AUTHOR_NAME" != "csharp36" ] '
            f'&& [ "$GIT_AUTHOR_NAME" != "Michael Bowie" ] && [ "$GIT_AUTHOR_NAME" != "suyash-adsgency" ] '
            f'&& [ "$GIT_AUTHOR_NAME" != "dependabot[bot]" ]; then '
            f'export GIT_AUTHOR_NAME="{NAME}"; export GIT_AUTHOR_EMAIL="{EMAIL}"; fi; '
            f'if [ "$GIT_COMMITTER_EMAIL" != "{EMAIL}" ] && [ "$GIT_COMMITTER_NAME" != "csharp36" ] '
            f'&& [ "$GIT_COMMITTER_NAME" != "GitHub" ]; then '
            f'export GIT_COMMITTER_NAME="{NAME}"; export GIT_COMMITTER_EMAIL="{EMAIL}"; fi'
        )
        index_filter = (
            "b=$(git ls-files -s site/index.html | awk '{print $2}'); "
            'if [ -n "$b" ]; then n=$(git cat-file -p "$b" | '
            f'sed "s#{private_repo}#{PUBLIC_REPO}#g" | git hash-object -w --stdin); '
            'git update-index --cacheinfo 100644,"$n",site/index.html; fi'
        )
        ranges = [f"{UPSTREAM_MAIN}..{b}" for b in BRANCHES]
        env = {**os.environ, "FILTER_BRANCH_SQUELCH_WARNING": "1"}
        for filt, expr in (("--env-filter", env_filter), ("--index-filter", index_filter)):
            done = subprocess.run(["git", "filter-branch", "-f", filt, expr, "--", *ranges],
                                  cwd=clone, capture_output=True, text=True, env=env)
            if done.returncode != 0:
                sys.exit(f"filter-branch {filt} failed:\n{done.stderr.strip()[-2000:]}")
        shutil.rmtree(clone / ".git" / "refs" / "original", ignore_errors=True)

        # The checks that matter, before anything leaves this computer.
        ours = _git("log", "--format=%an|%ae|%cn|%ce", *ranges, cwd=clone).split()
        strange = sorted({line for line in ours if line != f"{NAME}|{EMAIL}|{NAME}|{EMAIL}"})
        if strange:
            sys.exit("Commits past upstream still carry another identity:\n  " + "\n  ".join(strange))
        if _git("rev-parse", "main", cwd=clone).strip() != UPSTREAM_MAIN:
            sys.exit("main is not upstream's main any more; the rewrite touched it.")
        history = _git("log", "--all", "-p", cwd=clone).lower()
        for word in private_words:
            if word in history:
                sys.exit("A private word is still in the history. Stopping.")
        print(f"verified: {len(ours)} commits past upstream, all {NAME}; nothing private in the history")

        if args.dry_run:
            print("dry run: nothing pushed")
            return 0
        _git("remote", "add", "public", PUBLIC, cwd=clone)
        _git("push", "-q", "public", "main", *BRANCHES, cwd=clone)
        print(f"pushed main, {', '.join(BRANCHES)} to {PUBLIC}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

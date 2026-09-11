# Handoff: continuing on another computer

*Written 11 September 2026. Everything below lives in this folder.*

## What this folder is

The desktop edition of Open Hospitality, built on `csharp36/open-hospitality`
to the plan in `docs/desktop/PRD-desktop-edition.md` (the same file as
`PRD-open-hospitality-desktop.md` in this folder).

| Branch | What it is |
|---|---|
| `main` | Upstream, exactly at `bba21e7` (8 Sep 2026). Remote `upstream`. |
| `desktop/prd` | The PRD, README fork banner and NOTICE (from `desktop-prd-branch.bundle`). |
| **`desktop/m1`** | **All the work: check this out.** M1 done, M2 in progress. |

Nothing has been pushed anywhere. There is no fork on GitHub yet (see
`fork-setup-steps.md`).

## Moving it to your laptop

**The easy way:** copy `open-hospitality-desktop.bundle` from this folder to
the laptop. It is one file holding every branch and commit. Then:

```bash
git clone open-hospitality-desktop.bundle "Open Hospitality"
cd "Open Hospitality"
git checkout desktop/m1
git remote add upstream https://github.com/csharp36/open-hospitality.git
```

Also copy `PRD-open-hospitality-desktop.md`, `fork-setup-steps.md` and this
file if you want them. They are notes, not code.

**Or copy the whole folder**, but skip these, which are rebuilt per machine
and some of which only work on this one: `.venv/`, `frontend/node_modules/`,
`vendor/`, `dist/`, `build/`, `.dev/`, `frontend/dist-desktop/`.

## Setting up on the laptop

Needs: [uv](https://docs.astral.sh/uv/), Node 20+, and Docker only for
upstream's own test suite.

```bash
uv sync --extra dev --extra desktop --group build
uv run python scripts/desktop/fetch_postgres.py          # Windows: pinned
cd frontend && npm ci && npm run build:desktop && cd ..
uv run pytest tests/test_desktop_*.py                    # no Docker needed
uv run oh-desktop --sample-data --no-tray --no-browser   # prints a sign-in link
```

- **Mac:** the Postgres download for macOS has no pinned checksum yet. Run
  `fetch_postgres.py --allow-unpinned` once, then paste the SHA-256 it prints
  into `ARTIFACTS` in that script and commit it.
- **Windows:** if `uv` fails with *"Failed to update Windows PE resources"*,
  point TEMP somewhere inside the project first:
  `$env:TEMP="$PWD\.dev\tmp"; $env:TMP=$env:TEMP`.
- `OH_DATA_DIR=<some folder>` keeps a test install away from a real one.

## Where the work stands

**M1: runs without Docker.** Done. See `docs/desktop/M1.md`.

**M2: the front door.** In progress, in slices:

| Slice | State |
|---|---|
| Desktop settings chain (own schema, own migration history) | Done |
| Modules: registry, `create_app(mount=…)`, Modules page, live reload (ADR-D3) | Done |
| Windows fix to upstream's portal fallback (unknown API paths answered 200) | Done, listed in `docs/desktop/UPSTREAM.md` |
| Local accounts, backend: Argon2id, breached-password list, recovery code, per-device sessions, setup codes, Keycloak seam | Done (44 desktop tests) |
| Local accounts, frontend: `/desktop-signin` (first-run owner, sign-in, set-up code, recovery, recovery-code screen) and `/account` "Sign-in & security" (your sign-ins, change password, owner hands out set-up codes) | Done. Verified end to end on Windows against a fresh install. Set-up codes live on `/account`, not upstream's Employees page, so no upstream page changed |
| First-run wizard `/welcome`: hotel group → first hotel (name, name as its reports print it, PMS, rooms) → fiscal year → modules. Backend `src/usali/desktop/welcome_api.py` writes the property **with its detection alias** (upstream's `create_first_property` writes none, so its hotels could never match a report), rooms and fiscal calendar in one transaction. Layout sends the owner there until it's finished | Done. Verified end to end on Windows: fresh install → wizard → the sample choiceADVANTAGE pack dropped in the folder resolved to the new hotel and its statement built from the posted journal |
| Keys into the OS keychain (PRD A-4, ADR-D5): the six install secrets are sealed (AES-256-GCM) in `keys.sealed.json` under a master key held only in Credential Manager / Keychain (`src/usali/desktop/keystore.py`). M1 installs move over on first launch; the plain `keys.json` is deleted only after the sealed copy reads back identical | Done. **Consequence:** copying the folder alone no longer moves or backs up an install — M3's backup must carry the master key (ADR-D5 proposes wrapping it with the recovery code) |

**M2 is complete.** Next is M3 (signing, auto-update, backup and restore).

**After M2, from owner feedback: the menu and an all-hotels dashboard.**

| Slice | State |
|---|---|
| Nav in an owner's words, in three tabs: **Accounting** (first: Overview, Hotel dashboard, Profit and loss, Occupancy and rates, Close the day, Add reports, Books, For your accountant, Send to QuickBooks), **People** (the Payroll & People module) and **Ops** (modules still to come); **Settings** always at the bottom. Page titles renamed to match (listed in `NOTICE`) | Done |
| `/overview` — every hotel for the last closed day, totals pooled from parts (never averaged percentages), and when Payroll & People is on: on the clock now (counted where they clocked in), staff, timecards to approve (ended periods only), labour vs revenue. Backend `src/usali/desktop/portfolio_api.py`, scoped by upstream's `resolve_scope` | Done |
| "Add a hotel" after setup: `/welcome?add=hotel` reopens the wizard's hotel steps | Done |
| **Known, not fixed here:** upstream's `gl_api.py` read routes don't check per-hotel access (any operator in the group can read any hotel's ledger). Offered as its own task, intended as an upstream PR | Open |

## Decisions already made (don't re-open without reason)

- **The engine is never forked.** New code lives in `src/usali/desktop/`, and
  every upstream file changed is listed in `NOTICE`.
- **The live database is in OS app-data, not Documents.** Cloud-sync clients
  corrupt live Postgres folders. The Documents folder holds reports and, from
  M3, backups.
- **The desktop has its own migration chain** (schema `desktop`), so rebasing
  on upstream never produces two heads.
- **Upstream's GL is required.** The statement reads the posted journal, so
  every property needs a fiscal calendar before its first report.
- **The tray icon is pystray (LGPL), shipped only as a one-folder build.**
- **The breached-password list is SecLists/NCSC top 100k (MIT), SHA-pinned.**

## If you're picking this up with Claude on the laptop

It won't have this conversation. Point it at this file, `docs/desktop/M1.md`,
the ADRs in `docs/desktop/adr/`, and `git log desktop/m1`.

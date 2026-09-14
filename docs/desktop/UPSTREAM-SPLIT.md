# Everything goes upstream — no separate product

*Decided 14 September 2026, after the upstream author's reply. There will be no separate product under the Open Hospitality name, nor under any other. The website is taken down. This work is offered back to csharp36/open-hospitality as pull requests from a fork under the contributor's account, and the desktop edition waits for upstream's own direction. The PII holdback the author asked about was hardened first: [PII-holdback.md](PII-holdback.md).*

## What goes upstream, in the order it is easiest to take

Each is a pull request against upstream `main`, small enough to review, with its tests. The CLA is signed first.

| # | What | Where it is today | Why upstream wants it |
|---|---|---|---|
| 1 | **The Windows path fix and `create_app(mount=…)`** — already written and tested here, listed in [UPSTREAM.md](UPSTREAM.md) | `src/usali/server.py`, portal history fallback | Upstream's own tests fail on Windows without them |
| 2 | **Reader fixes found by real packs**: pack detection by section title (#78), the SkyTouch Hotel Statistics prior-year columns, `is_pack`/`process_upload`, the property-code registry match for choiceADVANTAGE | `src/usali/ingestion.py`, `adaptors/skytouch_hotel_statistics.py`, `stats_promote.py`, `detect.py` | Parser improvements, the part Chris most wants not to fragment |
| 3 | **Codes to confirm — per-hotel mapping decisions and restatement**: a decision table beside the shipped dictionary, facts re-classified in place (the journal FK forbids deleting posted facts), the ledger reposting the day, closed months refused by name | `src/usali/desktop/mapping_decisions.py`, `codes_api.py`, the `d0002` migration, `transform.py` resolver seam | The USALI mapping and the recalc logic — engine, not shell |
| 4 | **The AI fallback**: the allow-list-by-construction question, the outbound scan that refuses, page-level filtering for reports with no reader, reading guides as skills, recipes learned from confirmed readings and replayed with no model call, the spend cap, the provider port with two adapters and an offline mock | `src/usali/desktop/ai/`, `mapping/reading-guides/`, `report_recipes.py` | Reads unknown formats for any deployment; the PII holdback ([PII-holdback.md](PII-holdback.md)) is worth having reviewed by more than one pair of eyes |
| 5 | **Ledger behaviour the walk found**: `AmbiguousFactsError`, the stale-entry direction in `CloseGaps`, ledger read confinement, projection turning an unknown jurisdiction into a 409 | `gl_posting.py`, `gl_api.py`, `reporting.py`, `schedule_api.py` | Month-lock and recalc correctness |
| 6 | **Onboarding on the property's business date** | `onboarding.py` | A night auditor adding staff before 4 AM — hosted or desktop |

What stays here: `src/usali/desktop/` (accounts, the wizard, backups, the tray and window, intake from a folder and a mailbox, the portfolio Overview, saved reports, the memory notes, uninstall), `packaging/`, `scripts/desktop/`, `site/`, and the desktop pages of the portal.

## What is left here, and how it relates to upstream

This repository is upstream's, with our commits on top; it is a fork on GitHub, and the branches here are the PRs' source. Nothing is published from it as a product. If upstream wants a desktop edition, the pieces below are how it would build on the library rather than carry it:

1. **Python.** `pyproject.toml` here declares a dependency on upstream's package (`usali`, from its Git tag), and `src/usali/desktop/` moves to its own package, `ophosp`, that imports `usali`. `build_app` composes upstream's `create_app(mount=…)` with the desktop routers. PyInstaller bundles both. Fixes flow by bumping the tag.
2. **The portal.** The desktop pages live in upstream's React app today (`frontend/src/pages/*Page.tsx` for the desktop's own pages, plus `Layout.tsx`, `router.tsx` and a handful of shared changes). The clean split needs one thing from upstream: a way to **mount extra routes and nav entries** — a small extension point (`createAppRouter({ extraRoutes, extraNav })`, or a plugin directory the build picks up). With that, OpHosp keeps its pages in its own `frontend/` that depends on upstream's as a package; without it, the portal stays a fork a while longer while the Python side splits first. Proposed to upstream as PR 7.
3. **Data.** The desktop's own tables stay in the `desktop.*` schema with their own Alembic branch (`d0001…`), on top of upstream's migrations — already the case, so nothing moves.
4. **Naming and distribution** are upstream's call.

## Order of work

1. Sign the CLA; take the commit rights.
2. PRs 1–2 (small, mechanical, unblock Windows CI upstream).
3. PR 3, then 4 — the two with design in them; each with its docs.
4. PRs 5–6.
5. The Python split (`ophosp` package depending on `usali`), then the packaged walk on the result.
6. The portal extension point, then the portal split.

Until upstream says otherwise, nothing is shipped from here; `scripts/desktop/publish.py` keeps the fork in step with this checkout under the contributor's public identity.

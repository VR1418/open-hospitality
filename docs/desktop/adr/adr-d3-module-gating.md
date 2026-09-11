# ADR-D3: Module gating at router mount

- **Status:** Proposed
- **Date:** 2026-09-11
- **Deciders:** desktop-edition owner *(to be named)*; drafted with Claude

## Context

The engine carries three products' worth of surface: accounting, a workforce
and payroll system, and hosted-service onboarding. An owner who wants an
operating statement should not have to walk past a payroll system to get one
(PRD 5.1). The PRD asks that owners choose modules at install and can change
them later; that a disabled module is *not mounted*, not merely hidden; and that
one registry holds each module's routers, navigation and published limitations
(5.4, L-1 to L-5).

`create_app` includes each router with an explicit `app.include_router`
call, and registers `/ingest` and `/api/preview` inline.

## Decision

- **`create_app` gains one optional argument, `mount: Callable[[str], bool]`.**
  Every router and both inline routes are registered through a named surface
  (`"portal"`, `"timecard"`, `"preview"`, …) and only if the predicate allows
  it. The default mounts everything, so every existing deployment, including
  upstream's hosted one, is unchanged. The change is small and generic, and we
  will offer it upstream.
- **`usali.desktop.modules` is the single source of truth.** Each `Module`
  names its surfaces, its navigation paths and its limitations (text plus an
  optional workaround). A test fails if `create_app` asks about a surface the
  registry doesn't own, so a router added upstream can't ride in unowned. A
  second test fails if any module has no limitations text (L-4).
- **Accounting & Reporting is required.** Payroll & People is optional and off
  by default. Hotel Management Utilities is listed as coming soon and can't be
  selected.
- **`signup` and `preview` are hosted-only.** They are never mounted on the
  desktop, whatever the owner chooses.
- **The owner's choice lives in `desktop.setting`.** That schema has its own
  migration chain and version table (`desktop.alembic_version_desktop`), so
  the fork never adds revisions to upstream's chain.
- **`GET /api/me/modules`** reports what is *mounted in this process*.
  **`PUT /api/desktop/modules`** is owner-only (an `org_admin` grant): it saves
  the choice, then rebuilds the local server in place on the same port, so the
  browser tab and session carry on.
- **The portal builds its navigation from `/api/me/modules`.** Client-side
  hiding is a convenience; the absent routes are the enforcement.

## Consequences

- **A disabled module's API is gone:** requests 404 because nothing listens.
  The attack surface shrinks with the choice.
- **Enabling a module later needs no migration and loses no data.** The schema
  always migrates in full.
- **Known gap: `workforce` stays mounted.** It carries `GET /api/me`, the
  portal's identity call, alongside employee records. Turning Payroll & People
  off hides the Employees pages, but the employee endpoints remain reachable to
  an authorised operator. The fix is an upstream split of `/me` into its own
  router, which we'll offer upstream.
- **Upstream `server.py` now differs from upstream by the seam.** A weekly
  rebase must carry it until upstream takes it or rejects it.

## Alternatives considered

- **Hide pages in the frontend only.** This fails the PRD's "not merely
  hidden" requirement and the fail-closed posture (ADR-010).
- **Strip routes from the built app afterwards.** This needs zero upstream
  diff, but it matches routes by path and silently misses anything renamed or
  added. That's precisely the drift the registry test exists to catch.
- **Restart the whole app on a module change.** This is simpler, but the owner
  loses their place, and it contradicts "changeable later" feeling like a
  setting rather than a reinstall.

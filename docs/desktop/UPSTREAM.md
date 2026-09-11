# Changes to offer upstream

The fork changes as little of the engine as it can (PRD §8), and sends back
anything that improves the shared engine (PRD §10). This page lists what is
waiting to go back to `csharp36/open-hospitality`, as pull requests, each
standalone and each useful without the desktop edition.

| # | Change | Where | Why upstream would want it | Status |
|---|---|---|---|---|
| 1 | **Windows path fix in the portal's history fallback.** `_SpaStaticFiles` compares paths in URL form, and a non-GET request to an unknown API path gets 404, not 405. | `src/usali/server.py` | On Windows, Starlette passes `api\nope`, and every `/`-based check misses. Unknown API paths then answer **200 with the portal page**, and the `.git/HEAD` scanner guard never fires. Upstream's own `test_spa_mounted_when_dist_exists` fails on Windows for this reason. | Ready: fix plus a test in the fork |
| 2 | **`create_app(mount=…)` surface predicate.** Every router and inline route is registered through a named surface. The default mounts everything. | `src/usali/server.py` | It lets a deployment leave a surface unmounted (a staging environment without signup, say) with no code fork. The default path is identical to today's. | Ready: see ADR-D3 |
| 3 | **Split `GET /api/me` out of the workforce router.** | `src/usali/workforce.py` | The portal's identity call shouldn't depend on the employee-records surface being mounted. It's the one thing keeping ADR-D3 from unmounting all of Payroll & People. | Proposed, not written |

Before any of these become pull requests, the fork framing in PRD §10 and open
decision 1 should be settled, and the CLA signed (the upstream bot will prompt).

# What to do next

*Written 11 September 2026, after the first outside test run. Ordered by what
would cost most to get wrong, not by what is most interesting to build.*

## Where things actually stand

| Milestone | State |
|---|---|
| **M1** it runs without Docker | Done. Bundled Postgres, PyInstaller, tray, folder watch. |
| **M2** it has a front door | Done. Local accounts, recovery code, wizard, modules. |
| **M3** it's trustworthy | **Two thirds.** Backup and restore done; an update *check* done. **Not signed** — the one piece that needs money, not code. |
| **M4** it's connected | **Half.** AI is built (phases 1–3: per-hotel code decisions, the codes queue, the owner's own model, reading a report we have no parser for). **Email is designed, not built.** |
| **M5** it's reviewable | Not started. |

The first outside run produced exactly what a first outside run should: a real
bug (a pack the upload page could not read), a real gap (no hotel name on
screen), and a real piece of data (one unclassified code holding $145.81 out
of a real profit and loss).

---

## Update, 13 September (evening)

Built since the morning, all on `desktop/m1`, each with its own tests:

| | |
|---|---|
| **Upload** | A pack for a hotel not set up yet says which hotel to add, by code. |
| **Setup** | Ownership entity, hotel name, hotel code, state; rooms read from the first audit. |
| **AI helper** | A service picked by name, the model from a list with prices, "Check it works". |
| **Own window, icon, uninstall** | Edge app mode; Desktop and Start menu icons; one copy at a time; Settings › Apps uninstall that keeps the books unless told otherwise. |
| **Saved reports** | A daily summary PDF and the month's accountant pack (Excel) after every audit; a folders card that opens each folder. |
| **AI memory** | Notes an Obsidian vault opens; reading guides the model is given; layouts learned from confirmed readings, replayed with no model call. |
| **Schedule** | Standard shifts, "until done", everything editable, times as people say them, copy a week, printable. |
| **Reports by email** | The built-in IMAP client on the owner's schedule; senders allowed one by one. |
| **Bank and card** | Statement CSVs checked against the audits' settlements (fee rate learned from the statement), card purchases sorted with the merchant remembered. |
| **Demo world and the walk** | Three hotels, thirty staff, ninety audits, statements that line up; `scripts/desktop/e2e.py` walks the real app end to end — **18 of 18 steps** on this checkout — and `check.py` runs it as its ninth check. |

The walk found three bugs no layer's tests had: a posted day could not be
restated (facts are referenced by journal lines — now re-classified in
place), the hours projection was a 500 for any hotel made by the wizard (no
wage jurisdiction — the wizard now asks the state), and the bank matcher
picked wrong nights when thirty nights looked alike (it now learns the
processor's fee rate from the statement).

**Not shipped to the tester yet, on purpose:** the owner's decision is to ship
once the full testing is done — the packaged build's own walk and the nine
checks — not before.

Still open, in the order they matter:

1. **Signing** (money, then an afternoon) — unchanged below.
2. **Email against a real mailbox.** Tested only with a stand-in; the first
   real Gmail app password will be the real test.
3. **Timecard approval across a period boundary** — the walk can only show
   the refusal ("period still running"); approving needs punches from a
   closed period.
4. **OPERA has no cash code** in its dictionary, so an OPERA hotel's cash
   deposits stay unmatched. Needs a real OPERA trial balance with cash on it.
5. **The printed rota** is styled but has not been looked at on paper.
6. **CI still does not dispatch** on GitHub — the account-level question below.

## 1. Get the current build to the tester — *hours*

The zip they are running predates **fifteen commits**, including the fix for
the bug they reported. Everything since is invisible to them: the pack upload
fix, hotel names, codes to confirm, the AI, the logo.

Nothing else on this list produces feedback. This does.

## 2. Make the machine check the work — *a day*

**Today nothing does.** `.github/workflows/ci.yml` runs on `ubuntu-latest` and
never fetches the bundled Postgres, so **9 of the 19 desktop test files skip
entirely** — including every test that proves sign-in, backup, restore, the
codes queue and the AI work against a real cluster. They run when I run them,
by hand, and at no other time.

Two things shipped today that a machine would have caught and a person did not:

- A regex whose `\b` anchors a shell heredoc had turned into literal backspace
  characters. It read correctly in the file and matched nothing. It was the
  rule protecting guest names.
- A frontend build that failed only under `tsc -b` — the check I had been
  running, `tsc --noEmit`, covers a narrower set and passed.

**Done, and blocked on one thing.** `.github/workflows/ci.yml` now has a
`windows-latest` job that fetches the bundled cluster and runs the desktop
suite, refuses to pass when those tests skip themselves, and builds the portal
rather than only type-checking it. Its exact command was run here first: 197
passed, no skips.

**GitHub is not dispatching it.** Two pushes to `desktop/m1` — a real one and
an empty probe — created no workflow run at all. What I could check from here
says everything is in order:

- `repos/.../actions/permissions` → `{"enabled": true, "allowed_actions": "all"}`
- all six workflows listed `active`
- the `ci.yml` **on GitHub** reads `branches: [main, 'desktop/**']`, and the
  branch is `desktop/m1`
- the repository is private and is not a fork
- `actions/runs` → `total_count: 0`, for every workflow, ever

So the cause is above the repository, where an API token cannot see it. Worth
checking, in order:

1. **Billing → Actions minutes.** A private repo on the free tier gets 2,000
   minutes a month; at the limit, runs stop being created rather than failing.
   Windows minutes bill at **2× the rate**, which this job will consume.
2. **Settings → Actions → General**, at the account level as well as the repo.
3. **Making the repository public** removes the question entirely — Actions is
   free and unmetered there — and M5 makes it public anyway. That is a decision
   about timing, not a workaround.

Until it dispatches, one command runs the lot:

```
uv run python scripts/desktop/check.py
```

Eight checks — ruff, strict mypy, the engine suite on Docker, the desktop suite
on the real bundled cluster, and the portal's types, lint, tests and **build**.
`--quick` drops the three slow suites; `--list` says what is ready and what is
missing.

It will not call a run a pass when something did not run. A missing Docker, an
unfetched cluster or an absent `face` extra is reported as **skipped** and
exits non-zero unless you pass `--allow-skips`. It also catches the failure
this whole section is about: the desktop tests skip THEMSELVES when the cluster
is absent, so a green pytest over nothing is reported as **hollow** rather than
passed.

## 3. Email intake — *the rest of M4, about a week*

Designed in [M4-ai-and-ledger.md](M4-ai-and-ledger.md) phase 4. Himalaya
fetches, attachments land in the folder the watch already drains, and the
**recipe is learned once**: which hotel a sender means, and how that layout
reads. Confirmed by the owner, stored, replayed — no model call per morning.

The reason to do it after CI, not before: it is the first feature with a
moving part outside the machine, and the first that runs unattended every day.

## 4. Sign the app — *money, then an afternoon*

Still unsigned, so every tester meets **"Windows protected your PC"**. The
install guide explains it, but it remains the single thing most likely to stop
a real owner before they start. SmartScreen reputation now builds by file hash
and download volume regardless of certificate type, so the sooner a signed
build is in circulation the sooner the warning stops.

Mac has never been built or run. The darwin Postgres jars still have no
SHA-256 pin, and the fetch script refuses them until someone pins them on a
Mac.

## 5. Small things worth fixing while they are still small

| | Where |
|---|---|
| The Overview's "Codes to confirm" finding links to **Close the day** — the wrong screen. | `OverviewPage.tsx`, the audit section's fixed link |
| `*.bundle` is not in `.gitignore`; a 4.5 MB stray was swept into a commit and had to be amended out. | `.gitignore` |
| Two orphaned keychain credentials from old test installs, which I would not delete without knowing they are dead. | Credential Manager, `master-key:7b821269…` and `master-key:5663c750…` |
| Three version numbers that disagree: `pyproject` 0.1.0, `package.json` 0.0.0, and nothing shown in the app. A tester cannot tell us which build they have. | one source, surfaced in the UI |
| The wordmark is not Space Grotesk — the kit's own lockups carry no font. Bundling it is the only offline-safe fix. | `docs/brand/README.md` |
| Six dots on a dark square are hard to pick out at a true 16px tab size. | the kit's `favicon.svg` |
| **Portal tests are flaky under load.** Three sightings now — `PerformancePage`, `WelcomePage`, and once inside `check.py` — each passing alone and failing while something heavy ran beside them. They are `waitFor` timeouts, not real failures, but CI runs jobs in parallel and will hit this. Worth raising the timeout or reducing jsdom churn before it is dismissed as noise once too often. | `frontend/src/pages/*.test.tsx` |

## 6. Send the three upstream changes back — *half a day*

[UPSTREAM.md](UPSTREAM.md) has three, two of them written and tested here: the
Windows path fix in the portal's history fallback (upstream's own test fails
on Windows without it) and `create_app(mount=…)`. Several more have accumulated
since and are not yet listed: `is_pack`/`process_upload`, the stale-entry
direction in `CloseGaps`, `AmbiguousFactsError`, the `transform` resolver seam,
and the ledger read confinement.

A fork that only takes is a bad neighbour.

## 7. M5 — *two weeks, when the rest is true*

Public repository, documentation, sample data, a five-minute video, an issue
template.

---

## If you only do three

1. **Ship the build.** The tester is the only source of the bugs that matter.
2. **Windows CI.** Everything after it is protected; everything before it was luck.
3. **Email.** It is the difference between a tool someone opens and a tool that
   is simply up to date each morning.

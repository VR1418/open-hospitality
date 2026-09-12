# M4 — the owner's own AI, and the ledger it has to be safe around

**Status:** Phases 1 and 2 built and tested; 3 and 4 designed · **PRD:** [PRD-desktop-edition.md](PRD-desktop-edition.md) §6.3, AI-1…AI-8

Two requests, and they turn out to be one piece of work: *let the owner point their own
AI at the transactions and have it evaluate the entries*, and *check the ledger build*.

The short version: **the AI has nowhere to put an answer today.** The table that decides
how a transaction posts is global, unauditable and un-editable from inside the app. So
the first half of M4 is giving a hotel somewhere to record what its own codes mean; the
AI is then a source of suggestions into a queue that already works without it.

---

## Part 1 — what the ledger build does today, and what is wrong with it

The chain is sound and its refusals are well-chosen. A PDF becomes `detect` →
adapter → stage rows → `transform` → facts → `gl_posting.post_and_record`, all in one
transaction, with the file only moving to "Reports we read" after the commit
(`ingestion.py:272-287`). Debits must equal credits in the app (`gl_posting.py:190`)
*and* again at COMMIT in a deferred database trigger. Journal rows have `UPDATE` and
`DELETE` revoked from the serving role, so a correction is structurally a reversal.
That is a better-built ledger than most.

Five things are wrong. They are listed worst-first, and the first two are why the AI
work has to wait behind them.

### 1.1 Money from an unrecognised code disappears quietly, and every check still says green

When a transaction code is not in the dictionary, `transform` does not drop it and does
not quarantine the report — it writes a `MappingException` row and carries on
(`transform.py:87-101`). No fact is created, so `build_pms_daily_plan` never sees that
money. The journal still balances, because the difference is swept into the
`guest_ledger_clearing` account (`gl_posting.py:310-335`). And
`sos_journal_parity` **excludes the clearing account by design**
(`reporting.py:1055-1063`).

So: revenue is missing from the profit and loss, the books balance, the parity gate is
clean, and the intake log says `unmapped=0` on re-runs and on every statistics report
(the count is hardcoded `0` at `ingestion.py:135,149,163,177,203`). The only durable
trace is `FinancialCoverage.exception_count`, a badge on the Coverage page, and the
individual exception rows — with their amounts — are not shown anywhere, in any API.

**This is the single most important hole, and it is exactly the failure an AI
classification feature is most likely to cause and least likely to be caught causing.**

### 1.2 A hotel cannot record what its own transaction codes mean

`UsaliMappingDictionary` is `class UsaliMappingDictionary(Base)` (`models.py:145`) —
**not** `OrgScoped`, unlike every fact and stage table. No `org_id`, no `property_id`,
no `updated_by`, no `updated_at`, no audit hook. There is no HTTP endpoint and no page
that writes it: the only writers are the `usali seed-mappings` CLI and the desktop's
own first-run seed. Changing a mapping today means editing a YAML file on disk and
re-running a command.

Three consequences:

- **Two hotels in one group cannot both be right.** The row is keyed
  `(pms_source, trx_code, edition)`. Meanwhile `mapping/skytouch.yaml` says in its own
  header that choiceADVANTAGE codes are *franchise-configurable* and ships **all 22 rows
  as `confidence: LOW`, `review_status: needs-review`** — the one PMS whose codes are
  known to differ per property is the one that cannot hold a per-property answer.
- **`needs-review` does nothing.** `transform` never reads `review_status` or
  `confidence` (`transform.py:51-59, 87`). A `LOW`/`needs-review` row posts to the
  general ledger exactly like a confirmed one. Today, on a real choiceADVANTAGE hotel,
  every posted entry rests on an unverified guess — including
  `PO` (cash paid out), whose own note says *"sign is unverified … confirm on real
  sample"*.
- **Curation is erasable.** `load_mappings` upserts with
  `on_conflict_do_update` over `review_status`, `confidence` and `notes`
  (`mapping/loader.py:52-64`), where `gl_chart.seed_chart` deliberately does the opposite
  (insert-only, so an operator's edit survives every later seed). On the desktop the
  seed is guarded by `seeded_at` in the state file (`bootstrap.py:383`) so it runs once —
  the risk is a manual re-seed, or a restore onto a machine whose state file is missing,
  not every launch.

### 1.3 A stale journal entry can pass "close the day"

`_fail` sets `status="failed"` **only when there is no standing entry**
(`gl_posting.py:555-556`). So a day whose facts changed but whose re-post was refused —
closed period, deactivated account, a code that became unmapped — keeps
`status="posted"` with a stale `entry_id`. `period_gaps` builds its posted set from
`status` alone and never compares `source_hash` to a freshly built plan
(`gl_posting.py:702-706`), so that day shows in neither `unposted` nor `orphaned`, and
`close_period` reports a clean period over a journal that no longer matches the facts.
`QboPushLedger` has a `stale` status for exactly this; `GlPostingLedger`'s CHECK admits
only `posted` and `failed`.

### 1.4 The journal builder is blind to PMS source and USALI edition

`build_pms_daily_plan` selects facts on `(property_id, business_date)` only
(`gl_posting.py:241-246`). `UsaliFinancialFact` carries `pms_source` and
`usali_edition`, and both `night_audit._balances` and `reporting._financial_coverage`
filter on them with docstrings explaining why — a property that migrated PMS, or a
backfill through `/ingest`, legitimately holds two rows for one property-day. The plan
builder would sum both into one entry. `sos_journal_parity` sums facts the same
unfiltered way, so it would agree with itself and report parity.

### 1.5 Ledger reads were not confined to the caller's hotels

`gl_api.py` confines `/api/gl/periods`, `/trial-balance` and `/entries` with
`_require_readable_property`, matching the `property_config_api` read gate, so an
out-of-scope or another org's property is the same 403 everywhere. Both files are in
`NOTICE` (Apache §4(b)).

---

## Part 2 — the plan

### Phase 1 — somewhere to put an answer (no AI involved) — **built**

| | Where |
|---|---|
| 1a Ledger reads confined to the caller's hotels | `gl_api.py`, 29 tests |
| 1b Per-hotel code decisions | `desktop/mapping_decisions.py`, migration `d0003`, the `transform` resolver seam, 7 tests |
| 1c Codes to confirm | `desktop/codes_api.py` + `CodesPage.tsx`, 9 + 7 tests; the standing Overview finding, 1 test |
| 1d A stale journal no longer passes close | `gl_posting.CloseGaps.stale`, surfaced as `stale_dates`, 1 test |
| 1e Source- and edition-blind journal builder | `AmbiguousFactsError`, 1 test |

Suites after: 130 desktop, 222 GL/parity/night-audit/reporting, 591 frontend.

This is worth building on its own merits, and PRD **AI-8** requires it anyway: with AI
off, every feature still works, sorting is manual, nothing is gated behind a paid
provider. Phase 1 *is* the manual path.

**1a. Land the ledger access fix.** Add both files to `NOTICE`, run the tests under
Docker, commit.

**1b. A per-hotel mapping decision, org-scoped and attributable.** New desktop-owned
table (`desktop` schema, migration `d0003`), keyed
`(property_id, pms_source, pms_trx_code, usali_edition)` — no `org_id`, because the
`desktop` schema describes the install, one owner's machine, as `desktop.setting` and
`desktop.account` already do — carrying the same five
classification columns plus `decided_by`, `decided_at`, `origin`
(`owner` / `ai-accepted`) and a note. Resolution order in `transform` becomes:
**this hotel's decision → the shipped dictionary → `MappingException`.**

The engine change is one seam: `transform(session, …, resolver=None)`, defaulting to
today's behaviour, so upstream can take it as a pull request rather than a fork
(`docs/desktop/UPSTREAM.md`). Modified upstream files go in `NOTICE` as always. Needs
**ADR-D6** recording why an override table rather than writing to the global dictionary.

**1c. Show the money that is sitting in the clearing account.** Two pieces:
- A **"Codes to confirm"** page and API over `MappingException` and over every
  `needs-review` row in use at this hotel: the code, the description as printed, how
  many times it has been seen, **how much money**, and the dates. Confirming one writes
  a row from 1b and re-runs the affected days.
- A **finding on the Overview** when `guest_ledger_clearing` holds a non-trivial
  balance, alongside the night-audit findings already there. Nothing else will ever tell
  the owner, because parity is clean by design.

Note for 1c: an existing `MappingException` makes its stage row count as "already
processed" (`transform.py:63-77`), so confirming a code must delete the exception row
before re-running, or no fact will ever be created.

**1d. Make a stale entry visible to close.** Either add a `stale` status mirroring
`QboPushLedger`, or have `period_gaps` compare `source_hash` against a freshly built
plan. Upstream pull request.

**1e. Filter the plan builder by `pms_source` and `usali_edition`.** Small, and it
prevents a silent double-count. Upstream pull request.

### Phase 2 — the AI, as a source of suggestions into that queue — **built**

| | Where |
|---|---|
| Port, two adapters, a mock | `desktop/ai/port.py`, `openai_compatible.py`, `anthropic.py`, `mock.py`, `reply.py` — 15 tests, all offline |
| AI-1 key in its own keychain entry | `desktop/ai/config.py`, `keystore.install_id` |
| AI-2/3 cap and visible spend | `desktop/ai/spend.py`, migration `d0004` — 10 tests |
| AI-4 allow-list | `desktop/ai/allowlist.py` — 12 tests, its own file as the PRD asks |
| AI-5 audit | `desktop.ai_call` plus an `AuditEvent` per call |
| AI-6 human confirms | no apply endpoint; acceptance goes through `PUT /api/desktop/codes/{code}` with `origin="ai-accepted"` |
| AI-7 declining | `Answer.__post_init__` refuses a decline with no reason |
| AI-8 off by default | a module (ADR-D3); off means the routes are not mounted |
| Screens | `AiPage.tsx` (12 tests) and the suggest control on `CodesPage.tsx` (6 more) |

Decisions recorded in [ADR-D7](adr/adr-d7-owner-supplied-ai.md).

Suites after: 182 desktop, 609 frontend.



**What it does, in this order of value:**

1. **Confirm this hotel's transaction codes.** It sees a code, the description as
   printed on the report, the amounts it has been seen for, and the list of USALI lines,
   and proposes a line with a reason — or declines. This is PRD §6.3's highest-value use
   and it lands straight into 1c's queue.
2. **Explain a discrepancy in plain language.** The AR roll-forward delta already on the
   Overview, or the clearing-account balance from 1c, described in words. Advisory text,
   never a posting.

Deferred, with reasons: **coding card purchases** has nothing to code until statement
upload exists (PRD open decision 5); **answering questions about on-screen numbers**
would put the model near labour figures, which drags in ADR-006's suppression rule —
worth doing, not worth doing first; **drafting a parser** is developer-facing.

**How it is built:**

| Requirement | How |
|---|---|
| Two adapters, not five | `src/usali/desktop/ai/`: `port.py` (a `Protocol` and a frozen `Suggestion`, copying `payroll_provider.py`'s shape, including its rule that an error message never carries the payload), `openai_compatible.py` (base URL + key: OpenRouter, OpenAI, Ollama, LM Studio, Groq, Azure), `anthropic.py` (native Messages API), `mock.py`. `httpx` is already a core dependency — **no new packages**. |
| **AI-1** key in the OS keychain | Reuse `OsKeyStore`. Its own keychain entry, **not** inside `keys.sealed.json` — the sealed bundle rides along in the backup, and a provider key should not leave the machine in a file. Restoring onto a new computer asks for it again. |
| **AI-2** hard monthly cap, $10 default | New table `desktop.ai_call`: one row per call with provider, model, purpose, tokens, estimated cost, payload hash, outcome. The month's sum is checked *before* the call, in the same transaction that records it. Where a model's price is unknown we say so and cap on **call count** rather than invent a dollar figure. A local model is $0 and says so. |
| **AI-3** spend visible | The running figure sits on the AI page, not discovered later. |
| **AI-4** allow-list, in code | `allowlist.py`. The model is never handed a row: the payload is *constructed* from a typed object whose only fields are pms_source, code, printed description, date, amount, and the candidate USALI lines — everything else is structurally absent rather than stripped. Then an outbound scan that **refuses to send** (never masks — a mask would hide the bug) on a Luhn-valid card number, on any employee name in this org, or on anything the suppression rule hides. Its own test file, per the PRD. Scoping jobs 1 and 2 as above means the AI surface never queries a labour table at all, which is how ADR-006's outbound clause is satisfied by construction. |
| **AI-5** every call audited | The rich row goes to `desktop.ai_call`; an `AuditEvent` (`ai_suggestion_requested`) goes to the org trail — `AuditEvent` has no payload column, so it cannot carry this alone. Both commit with the work or not at all, per the existing house rule. |
| **AI-6** never in a write path | Suggestions land in a `pending` table. Accepting one writes the Phase-1b decision with `decided_by`/`decided_at` and an audit row; rejecting is recorded too. Copying timecard approval, **accepting a suggestion that no longer gates anything is refused** — the trail must never record a decision that had no effect. |
| **AI-7** it must be able to decline | `Suggestion.decline_reason`. Tax treatment and capitalisation are required refusals. The mock exercises the declining path, and a decline still counts toward spend. |
| **AI-8** works with AI off | A module entry (`ADR-D3`), `required=False`, `default_on=False`, mounted from `desktop/app.py` like the other desktop routers so `server.py` needs no edit. Off means the routes do not exist. Phase 1 is the manual path. |

Needs **ADR-D7** for the port, the cap, the allow-list and the audit — the PRD specifies
AI-1…AI-8 but there is no ADR yet.

**Wording.** PRD Appendix A: never "API key". The screen says *your AI helper*, and
"off", not "not connected".

### Phase 3

Job 2 above, plus the upstream pull requests from 1b, 1d and 1e.

---

## Honest note on scope

The PRD budgets M4 at three weeks for **email intake plus AI**. Phase 1 is not in that
line and is roughly a week on its own. It is still the right order: without it an
accepted AI suggestion has nowhere to be written that another hotel in the group won't
overwrite, and no record of who accepted it.


---

## Phase 3 — reading a report the product has no parser for

*Asked for after a tester hit the wall: a hotel whose front-desk system is not
one of the three cannot get past the wizard at all. It refuses with "Open
Hospitality can't read reports from that system yet" and will not create the
hotel, so nothing else in the app is reachable either.*

### The safety question, settled first

Reading an unknown report means showing a model text we did not write, and a
night-audit export is full of things that must never leave. The real
choiceADVANTAGE pack behind this carries guest names, account numbers, guest
tax IDs and balances.

The decision (owner's call, taken 11 Sep 2026): **the model only ever sees
pages that pass the outbound scan.** Not the whole report with a consent
tick — that would make "never a guest name" untrue, and it is currently
printed in the install guide.

Built already (`desktop/ai/pages.py`): the report is split into pages, each
page is run through `allowlist.check`, and a page either goes whole or is
dropped whole with the reason named. Measured on the real pack: 21 of 48 pages
kept, and **no kept page carries a person's name**. What survives is the
summary — the only part the books need.

### Still to build

| | |
|---|---|
| **Ask** | A second question type in `allowlist`: the kept page text plus the hotel's name, asking for `[{code, description, amount}]` and a business date. This one is FILTERED, not constructed — recorded in ADR-D7 as the single exception, with `pages` as the reason it is acceptable. |
| **Confirm** | The extracted rows are shown in a table and the owner accepts them. Nothing is staged from a model's word alone (AI-6). |
| **Stage** | Accepted rows become `PmsDailyFinancialStage` rows under `pms_source="OTHER"`, then upstream's ordinary `transform` → `post_and_record`. Because the shipped dictionary has no OTHER rows, every code lands as a `MappingException` — which is to say, straight into **Codes to confirm**, where Phase 1 already handles it. |
| **Wizard** | "My system isn't listed" stops being a dead end: the hotel is created, and the screen says plainly that reports will be read with the AI helper's assistance and confirmed by them. |

The thing to notice: Phase 1 and Phase 3 meet without new machinery. An
AI-read report produces unmapped codes, and unmapped codes already have a
queue, a money figure and a confirm button.

---

## Phase 4 — reports that arrive by email

*PRD M4's other half (Himalaya), plus what the owner asked for on top: the
reports differ hotel to hotel, so the AI must read them all, work out which
hotel each belongs to, and **remember** how — rather than being asked again
every morning.*

That last word is the design. Asking a model every day is expensive against
the AI-2 cap, slow, and — worse — non-deterministic: the same email could be
read two ways on two mornings. So the AI's job is to work out the recipe
**once**, and the app's job is to replay it.

| | |
|---|---|
| **Fetch** | Himalaya, bundled like Postgres, reading one mailbox the owner connects. Attachments land in the drop folder the folder watch already drains, so intake needs no new path. |
| **Whose hotel** | A learned route: sender address and subject shape → hotel. Proposed by the AI from the SUBJECT and SENDER only — never the body, which needs no scan because it is never read. Confirmed by the owner once, then stored and replayed. |
| **How to read it** | A recipe keyed by a fingerprint of the layout (the page titles and column headings, which carry no guest data). The first time a shape is seen, Phase 3 asks the model; the owner confirms; the recipe is stored. Every later email of that shape is read by replaying it, with no model call and no cost. |
| **When it drifts** | A recipe that stops matching — the PMS changed its layout — is not silently re-guessed. The report is set aside, the owner is told the shape changed, and the AI is asked again only on their say-so. |

Two tables, both following the `mapping_decision` pattern already proven in
Phase 1: keyed naturally, carrying who decided and when, never deleted.

### What this is not

Email is a door into the machine. The mailbox is read-only, attachments are
only ever PDFs, and nothing in an email's body is executed, followed or shown
to a model. A sender the owner has not confirmed gets its report set aside
rather than ingested.

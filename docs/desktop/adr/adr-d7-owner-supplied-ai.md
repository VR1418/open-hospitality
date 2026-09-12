# ADR-D7: The owner brings their own AI, and it never writes to the books

- **Status:** Proposed
- **Date:** 2026-09-11
- **Deciders:** desktop-edition owner *(to be named)*; drafted with Claude

## Context

PRD §6.3 requires that the owner supplies their own provider: we never hold a
key, never proxy a request, never take a margin. It sets eight requirements,
AI-1 to AI-8, and names two adapters plus a mock. There was no code — not an
adapter, not a client, not a dependency — so everything here is new.

The first job the AI is for is the one the product most needs done. Upstream
decides a transaction code's USALI line from `usali_mapping_dictionary`, and
`mapping/skytouch.yaml` ships all 22 choiceADVANTAGE rows as `confidence: LOW`
/ `review_status: needs-review`, because those codes are franchise-configurable.
A code the dictionary has never heard of is worse: `transform` banks it as a
`MappingException`, the journal balances by sweeping the money into
`guest_ledger_clearing`, and `reporting._journal_nets` excludes that account —
so `sos_journal_parity` reports parity over a profit and loss that is short.

Phase 1 (`desktop.mapping_decision`, the codes-to-confirm queue) gave that
question a place to be asked and answered by a person. This ADR adds a second
way to get a proposed answer. It does not add a second way to apply one.

Two existing rules constrain what may leave the machine. ADR-006 (suppression)
says outbound feeds "must obey the same suppression as the API and are the last
thing built". ADR-004 says the PII vault has no read path at all. Neither has an
allow-list; every existing control is a deny, a mask or a gate.

## Decision

- **One port, two adapters, one mock.** `OpenAiCompatibleAdapter` (a base URL
  and a key — OpenRouter, OpenAI, Ollama, LM Studio, Groq, Azure) and
  `AnthropicAdapter` (the native Messages API, a genuinely different shape).
  `MockAdapter` is deterministic and offline, and the test suite never needs a
  key or a network. `httpx` is already a core dependency; nothing is added.

- **AI-1 — the key is in the OS keychain, in its own entry.** Not in
  `keys.sealed.json`. That bundle is wrapped into every backup (ADR-D4), and a
  provider key should not leave the machine inside a file the owner syncs to a
  cloud drive. Restoring onto a new computer asks for the key again. It is
  never written to the database, a config file, a log, or an error message.

- **AI-4 — the payload is BUILT, not filtered.** The model is never handed a
  database row. `allowlist.CodeQuestion` names every field it may see:
  PMS source, transaction code, the description as printed on the report, dates,
  amounts, and the candidate USALI lines. Everything else is structurally
  absent rather than stripped.

  Then, immediately before the request leaves, the serialized body is
  **scanned** and the send is **refused** — never masked — if it contains a
  Luhn-valid card number, an SSN-shaped string, a long bare digit run, or any
  employee's name in this hotel group. Masking would hide a construction bug;
  a refusal makes it a test failure. The scan is defence in depth, not the
  control: the control is that the AI surface never queries a labour, payroll
  or PII table, which is how ADR-006's outbound clause is satisfied.

- **AI-2 / AI-3 — the cap is a table, checked before the call.**
  `desktop.ai_call` records one row per call: provider, model, purpose, tokens,
  estimated cost, a hash of what was sent, and the outcome. The month's sum is
  checked before each call and the row written in the same transaction as the
  result. Where a model's price is not known we say so and cap on **call
  count** rather than invent a dollar figure. A local model is zero and says so.

- **AI-5 — two records per call.** The detailed row goes to `desktop.ai_call`;
  an `AuditEvent` goes to the org trail. `AuditEvent` has no payload column, so
  it cannot carry this alone. Both commit with the work or not at all, which is
  the existing house rule (`integrations_api`, `crm_api`).

- **AI-6 — a suggestion is a proposal, and only a person applies it.** A
  suggestion is a row, never a write to `desktop.mapping_decision`. Accepting
  one goes through the same endpoint a person's own choice goes through, with
  `origin="ai-accepted"` and their subject in `decided_by`. Accepting a
  suggestion that no longer gates anything is refused, copying timecard
  approval's rule that the trail must never record a decision that had no
  effect.

- **AI-7 — declining is a first-class answer.** `Suggestion.decline_reason`.
  Tax treatment and capitalisation are required refusals. A decline still
  counts toward spend, and the mock exercises the path.

- **AI-8 — a module, off by default.** A disabled module is not mounted at all
  (ADR-D3), so with AI off the routes do not exist. The codes-to-confirm queue
  built in Phase 1 is the manual path and is unaffected.

## Consequences

- Three things an owner must do before any of this runs: turn the module on,
  choose a provider, and paste a key. Nothing happens by default, and nothing
  phones home — consistent with the PRD's no-telemetry rule.
- The allow-list has its own test file, as the PRD requires. A new AI job that
  needs a field the allow-list does not name is a deliberate change to that
  file, reviewed on its own.
- Spend is estimated, not billed. The provider's own figure is authoritative
  and will differ. The cap is therefore a guard, not an accounting record, and
  the app says so where it shows the number.
- `desktop.ai_call` grows one row per call. It is the audit trail, so it is
  never trimmed automatically.

## Alternatives considered

- **Put the AI key in `keys.sealed.json` with the others.** Simpler, one
  keychain entry, and it would survive a restore. Rejected: it would ride into
  every backup file, and the backup folder is deliberately one a cloud drive
  syncs.
- **Mask forbidden content instead of refusing.** Rejected: a mask turns a
  construction bug into a silent near-miss, and we would never learn the
  payload had been built wrong.
- **Let the AI write a decision directly when it is confident.** Rejected by
  AI-6, and by the ledger: an accepted classification restates posted days, and
  nothing in the product detects a journal that drifted from its facts except
  the check added in Phase 1.
- **Estimate nothing and cap on calls only.** Simpler and never wrong, but it
  fails AI-3's promise that running spend is visible. Cost is estimated where
  the price is known and call-capped where it is not.

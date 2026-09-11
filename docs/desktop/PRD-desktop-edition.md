# Product Requirements Document
## Open Hospitality — Desktop Edition

| | |
|---|---|
| **Version** | 0.1 — draft for review |
| **Date** | 11 September 2026 |
| **Status** | Proposed |
| **Upstream** | `csharp36/open-hospitality` @ `bba21e7` (8 Sep 2026), Apache-2.0 |
| **Owner** | *(to be named)* |

---

## 1. Summary

A **free, downloadable desktop application** for Mac and Windows that gives an independent hotel
owner a USALI-compliant picture of their money and labour, running entirely on their own computer.

One download. Everything it needs is inside it. No account with us, no server, no subscription, no
credit card in the install path. The owner connects their own AI provider, their own email, and
their own bank — each optional, each paid for directly by them, each capped.

The owner also **chooses which parts of the product they want**. Someone who wants a clean operating
statement should not have to walk past a payroll system to get one.

### Why this exists separately from upstream

Upstream has moved decisively toward a **hosted, multi-tenant SaaS**: invite-gated signup, a
marketing front door, a billing tier in Tier 1 of the roadmap, and bank feeds that (per ADR-012)
require a legal entity and a Plaid production agreement before they can run at all.

That is a coherent plan and probably the right one for a company. It is not a plan that reaches
the operator who will never sign up for a hosted service, and it cannot ship until somebody forms
an entity, signs agreements and carries liability.

This build takes the same engine in the other direction: **the owner's machine, the owner's
accounts, nobody's balance sheet.** The two are not competitors. If upstream's hosted product
succeeds, this is its free tier and its on-ramp.

---

## 2. Goals and non-goals

### Goals

| # | Goal | How we'll know |
|---|---|---|
| G1 | A non-technical owner installs and reaches a real number without help | 3 of 3 test owners complete setup unaided in under 15 minutes |
| G2 | Zero recurring cost to the owner for the core product | No paid dependency in the default install path |
| G3 | Zero recurring cost to the project beyond code signing | ~$220/yr total, no servers |
| G4 | The owner chooses their scope | Modules are selectable at install and changeable later |
| G5 | The product is honest about what it can't do | Every module and integration ships a published limitations panel |
| G6 | Their data survives their laptop | Backup configured during setup, not buried in settings |

### Non-goals

We are explicitly **not** building: a PMS, a booking engine, a channel manager, a payment
processor, a payroll disburser, a tax filer, a bank-credential holder, or a hosted service. Each of
these is either someone else's whole company or a liability we refuse to carry.

---

## 3. Who this is for

**Primary — the owner-operator.** Two to eight properties. Reviews numbers weekly, not daily.
Comfortable with a computer, not with a terminal. Currently gets a monthly package from a
bookkeeper and a stack of night-audit PDFs nobody reads. **Success for them is knowing on Tuesday
what used to take until the 20th of next month.**

**Secondary — the general manager.** Approves timecards, watches labour against occupancy, chases
paperwork. Uses the product daily if it's fast and never if it isn't.

**Tertiary — the bookkeeper or CPA.** Doesn't install it. Receives exports from it, and their
opinion decides whether the owner keeps using it.

**Explicitly not a target:** enterprise hotel groups with an IT department. They should use the
hosted version, or the cloud deployment upstream already supports.

---

## 4. Product principles

1. **The app is silent when things are fine.** Only exceptions surface. An empty "needs you" screen
   is the product working.
2. **Everything optional is skippable, and says so.** The install must complete with every
   integration declined.
3. **The owner pays their own providers directly.** We never resell, never mark up, never hold a
   payment method, never see a key.
4. **State the limits on the same screen as the feature.** A product that admits what it can't do
   is trusted about what it can.
5. **No refusal without a next step.** Every error names something the owner can do.
6. **Nothing posts without a human click.** The AI proposes; a person decides; the decision is
   logged.
7. **If a word would send someone to a hardware store, it doesn't ship.**

---

## 5. The module model

### 5.1 Why modules

The engine already contains three products' worth of surface area. Presenting all of it to an owner
who wants an operating statement is the single biggest usability problem this build inherits.

At install the owner picks what they want. Modules can be added or removed later without
reinstalling.

### 5.2 Module catalogue

#### **Accounting & Reporting** — *available, default on, cannot be disabled*

The core. Everything else is optional around it.

| Included | |
|---|---|
| Night-audit intake | Opera, AutoClerk, SkyTouch report packs |
| USALI mapping | Every transaction to its schedule and line |
| Summary Operating Statement | With drill-through to source documents |
| Ledger | Every posted line, traceable to the PDF page it came from |
| Performance statistics | Occupancy, ADR, RevPAR, TRevPAR, GOPPAR, CPOR |
| Budget and variance | Import a budget, see the gap |
| Bank cross-check | Statement upload; live feed optional |
| Card expense sorting | Card payments exploded into coded purchases via merchant category |
| Exports | Word, Excel, PDF, CSV, QuickBooks Online |

**Published limitations — shown in the app:**

- Reads **three PMS systems**. Others need a mapping file written by hand, or a report forwarded
  to us so we can add support.
- **A PMS vendor changing its report layout will break parsing** until an update ships. When that
  happens the file is quarantined with the error — nothing wrong is written to your books.
- Your property's **house-specific transaction codes must be categorised once**, by you. Expect
  roughly 10–20 minutes in the first month.
- **Not a tax product.** It will not compute, file, or advise on any tax.
- **Not an accounts-payable system.** It reads what happened; it does not route invoices for
  approval or pay them.
- Bank matching is **strong on settlements and payroll debits, weaker on cash deposits** and
  anything paid outside the connected accounts.

---

#### **Payroll & People** — *available, optional, off by default*

| Included | |
|---|---|
| Employee records | Lifecycle, departments, documents and expiry tracking |
| Scheduling | Demand-driven targets against rooms sold |
| Time clock | iPad kiosk, server-enforced punch order |
| Timecards | Exception-based approval |
| Labour cost | USALI Schedules 14 and 15, per department and day |
| Pay periods | Approve and push to a provider |
| Leave | Accrual and balances |

**Published limitations — shown in the app:**

- **This does not pay anybody.** It prepares an approved pay period and hands it to ADP or Gusto.
  Gross-to-net, tax withholding, filing and money movement all happen there.
- **No tax calculation or filing. Ever.** That is a licensed activity and a whole company.
- **Overtime and sick-leave rules are encoded for a limited set of jurisdictions.** Anywhere else,
  the app computes hours correctly and leaves the legal interpretation to you and your advisor.
- **Biometric time clock is off by default and refuses to enable in most jurisdictions.** Face
  matching touches biometric-privacy law that varies sharply by state; the app fails closed rather
  than guessing.
- Pay rates are **visible only to a payroll administrator**, and every reveal is recorded. This is
  not configurable.
- Labour figures for a department with **fewer than two paid employees are hidden**, and excluded
  from totals, to prevent an individual's rate being derived.

---

#### **Hotel Management Utilities** — *coming soon, visible but not selectable*

Listed at install so the owner knows the direction, greyed out so nobody is misled.

| Planned | |
|---|---|
| Housekeeping board | Room status, assignments, minutes-per-room |
| Maintenance tickets | Raised from the kiosk or by a manager |
| Document register | Certifications, permits, expiry alerts |
| Vendor directory | Contacts, contracts, renewal dates |
| Guest-demand feed | Read-only group and booking pace from a CRM |

**Published limitation:** *"None of this is built yet. It is shown here so you can see where the
product is going, not so you can plan around it."*

---

### 5.3 Cross-cutting options

These are not modules; they are connections any module can use. Each independently optional.

| Option | Default | Who pays |
|---|---|---|
| AI assistant | Off | The owner, to their chosen provider |
| Email intake | Off | Nobody |
| Bank connection | Off | The owner, if they exceed a free tier |
| Accounting export (QBO) | Off | The owner's existing QuickBooks |
| Payroll provider | Off | The owner's existing payroll plan |

### 5.4 How modules work technically

`create_app` already mounts every router with an explicit `include_router` call. Module gating is a
conditional around each one, driven by a local settings table.

- A disabled module's routes are **not mounted at all** — not merely hidden. A request to a
  disabled surface 404s because nothing is listening. This is fail-closed and reduces attack
  surface, consistent with the project's existing posture.
- The frontend builds its navigation from `GET /api/me/modules`. No client-side gating is trusted.
- The database schema migrates fully regardless. Unused tables stay empty. Enabling a module later
  requires no migration and loses no data.
- **`ModuleRegistry` is the single source of truth**: module id, display name, routers, nav
  entries, and its limitations text — so the published limitations cannot drift from what's
  actually mounted.

---

## 6. Feature specifications

### 6.1 Installation and dependencies

**Requirement:** one file, one double-click, nothing else to install. The word "dependency" never
appears in the user interface.

**Bundle contents:**

| Component | Purpose | Approx. |
|---|---|---|
| Application engine | PyInstaller single binary | 40 MB |
| PostgreSQL binaries | Real Postgres — row-level security must keep working | 62 MB |
| Frontend build | Static SPA, served by the engine | 5 MB |
| Himalaya | Mail fetch | 9 MB |
| Launcher | Menu-bar / tray control | 4 MB |
| **Total** | | **~120 MB compressed, ~168 MB download** |

**Explicitly excluded from the bundle:** Docker, Node, Java, Keycloak, and the biometric face
models (fetched on demand only if that feature is enabled, and it is off by default).

**Requirements:**

- **I-1** Install completes with no terminal, no prompts beyond the OS install dialog, and no
  network access after download.
- **I-2** The app is code-signed and notarised on both platforms; no security warning on first
  open.
- **I-3** Data lives in a folder the owner can see, name, and copy — the default is
  `Documents/Open Hospitality`.
- **I-4** Uninstall is dragging the app to the trash. Data survives, in the owner's folder, and
  this is stated on the uninstall path.
- **I-5** Updates check on launch and install on quit. An update never runs a migration the owner
  didn't consent to.
- **I-6** Backup is configured during setup, not after: the owner names a folder their existing
  cloud drive already syncs, and an encrypted copy is written there nightly.

### 6.2 Sign in

Keycloak is removed. It is a JVM identity server designed for multi-tenant federation, solving a
problem a single-property desktop install does not have.

**Requirements:**

- **A-1** First run creates the first account — full name, email as username, password. No invite,
  no token, no external service.
- **A-2** Passwords hashed with **Argon2id** at current OWASP parameters. Never stored or logged in
  any recoverable form.
- **A-3** Minimum 10 characters, checked against a bundled list of the most common breached
  passwords. No composition rules — no forced symbols, no forced digits.
- **A-4** Sessions are **short-lived RS256 tokens minted locally**, signed by a keypair generated
  on first run and held in the OS keychain. The existing `TokenVerifier` and every role check
  remain untouched — this is a swap at the issuer boundary only.
- **A-5** Optional Touch ID / Windows Hello unlock after first sign-in.
- **A-6** No password reset email — there is no mail server. Recovery is a **recovery code** issued
  at setup, with a clear warning that losing both password and code means losing access to the
  data. This is stated once, plainly, at the moment it matters.
- **A-7** The profile screen lists active sessions per device with individual sign-out.
- **A-8** Roles and scoping are **unchanged from upstream** — owner, bookkeeper, hotel manager,
  department head, payroll manager, staff; authority from database grants under row-level security.
  Only the labels are plain-language.

**Deliberately not built:** SSO, SAML, OAuth sign-in, and password reset by email. All require
infrastructure this product doesn't have.

### 6.3 AI connectivity

**Requirement:** the owner brings their own provider. We never hold a key, never proxy a request,
never take a margin.

#### Supported providers

| Provider | Why it's on the list |
|---|---|
| **OpenRouter** | One account, 300+ models across OpenAI, Anthropic, Google, Meta, Mistral and others. Best single choice for someone who doesn't want to pick. Passthrough pricing with a small platform fee. |
| **Anthropic** | Direct. Strong on document reading and structured extraction. |
| **OpenAI** | Direct. |
| **Ollama / LM Studio** | Local models. Nothing leaves the building. Free. |
| **Any OpenAI-compatible endpoint** | Base URL and key. Covers Groq, Together, Azure OpenAI, and self-hosted gateways. |

#### Architecture

This needs **two adapters, not five** — which fits the project's existing ports-and-adapters rule
(a port proven by two deliberately different-shaped adapters plus a runnable mock):

- **`OpenAICompatibleAdapter`** — a base URL and a key. OpenRouter, OpenAI, Ollama, LM Studio,
  Groq, Together and Azure are all configuration of this one adapter. OpenRouter's API is
  OpenAI-compatible at `https://openrouter.ai/api/v1`.
- **`AnthropicAdapter`** — native Messages API, a genuinely different shape, which is what proves
  the port rather than baking one vendor's assumptions into it.
- **`MockAdapter`** — deterministic, offline, exercised by the test suite. No test ever needs a
  key or a network.

**Requirements:**

- **AI-1** Keys are stored in the **OS keychain** — never the database, never a config file, never
  a log, never transmitted anywhere but the chosen provider.
- **AI-2** A **hard monthly spend cap**, defaulting to $10, enforced locally. At the cap the
  feature stops and says so. There is no path to a surprise bill.
- **AI-3** Running spend is visible in the app at all times, not discovered on a statement.
- **AI-4** **A strict content allow-list.** The model receives transaction codes, account names,
  merchant names, dates and amounts. It is blocked in code from employee names, pay rates, SSNs,
  bank details, account numbers, and any figure suppressed under the disclosure rules. Enforced by
  a redaction layer with its own tests — not by prompt instructions.
- **AI-5** **Every call writes an audit event** recording provider, model, purpose, token count and
  a hash of the payload — because we cannot audit what a provider does with a prompt, so we audit
  what left.
- **AI-6** **The AI is never in a write path.** Every suggestion requires a human click and records
  who accepted it.
- **AI-7** The model must be able to **decline**. On tax questions and capitalisation decisions it
  is required to refuse rather than guess, and to say why.
- **AI-8** With AI disabled, every feature still works. Sorting is manual. Nothing is gated behind
  a paid provider.

#### What AI is used for

1. Proposing USALI categories for unrecognised transaction codes *(highest value — the main
   onboarding bottleneck)*
2. Coding card purchases that merchant category codes can't resolve
3. Explaining a bank/ledger discrepancy in plain language
4. Answering plain-English questions about the numbers on screen
5. Drafting a parser for an unsupported PMS report layout *(developer-facing)*

### 6.4 Email connectivity

**Requirement:** the owner's night-audit reports arrive by email. Point at them once; never think
about it again.

**Himalaya** is the fetch engine — Apache-2.0/MIT licensed (compatible), speaks IMAP, JMAP, the
Gmail API and Microsoft Graph, emits JSON, and reads secrets from a command rather than a file so a
credential never has to touch disk.

| Path | Setup | Approval needed | Cost |
|---|---|---|---|
| **Gmail — app password** | Paste a 16-character app password | None | $0 |
| **Outlook / Microsoft 365 — own tenant** | Register a free app in the owner's own tenant, paste the ID | None — it's their tenant | $0 |
| **Any IMAP mailbox** | Server, username, password | None | $0 |
| **Watch a folder** | A mail rule saves attachments to a folder | None | $0 |

**Requirements:**

- **E-1** A **mandatory filter**. The app only ever touches messages matching a sender and subject
  pattern the owner sets. It does not read the mailbox.
- **E-2** Credentials in the OS keychain, passed to Himalaya at call time via a command.
- **E-3** Attachments are written to a local inbox folder; the existing pipeline takes over. Unread
  state in the mailbox is not modified.
- **E-4** Fetch failures are **visible and specific** — never silent. A refused password says which
  two things usually cause it.
- **E-5** **Folder-watching is always available** as a zero-credential fallback, and is offered
  first to anyone who picks "I'm not sure".

**Deliberately not built:** a shared "forward to us" inbox. That needs a mail server, which needs a
domain, a bill and an entity.

### 6.5 The limitations surface

This is a **feature**, not documentation. It is the thing most likely to earn trust from a sceptical
owner, and the thing most competitors hide.

**Requirements:**

- **L-1** Every module shows **"What this can and can't do"** in the module chooser at install, and
  permanently under Setup.
- **L-2** Limitations text lives in `ModuleRegistry` next to the code it describes — not in a wiki
  that drifts.
- **L-3** Where a limitation has a workaround, the workaround is on the same screen.
- **L-4** **Definition of done for any new feature includes its limitations entry.** A feature
  without one does not ship.
- **L-5** Limitations are written in the same plain language as everything else. *"Does not support
  multi-currency consolidation"* → *"If your hotels bill in more than one currency, this will add
  the numbers up wrong. Don't use it for that yet."*

---

## 7. Non-functional requirements

| | Requirement |
|---|---|
| **Platforms** | macOS 12+ (Apple Silicon and Intel), Windows 10+ (x64) |
| **Hardware** | 8 GB RAM, 5 GB free disk. Local AI models need 16 GB. |
| **Offline** | Fully functional with no network. Only AI, email and bank need connectivity. |
| **Cold start** | Under 10 seconds from launch to usable |
| **Report ingest** | A night-audit pack processed in under 30 seconds |
| **Accessibility** | Keyboard navigable; contrast meets WCAG AA; no meaning carried by colour alone |
| **Localisation** | English only at v1. Strings externalised so this isn't a rewrite later. |
| **Telemetry** | **None.** No analytics, no crash reporting, no phone-home. Diagnostics are a file the owner chooses to send. |
| **Data** | The owner's folder. Portable, copyable, theirs. |

---

## 8. Architecture — what changes from upstream

| Layer | Upstream | Here | Effort |
|---|---|---|---|
| Database | Cloud SQL / Docker Postgres | Bundled Postgres binaries, local data dir | Low |
| Identity | Keycloak (JVM) | Local issuer + Argon2id, existing verifier untouched | Medium |
| Frontend | Vite dev server / Cloud Run | Static build served by the engine *(already supported)* | None |
| Mail | Not present | Himalaya subprocess | Medium |
| AI | Not present | Two adapters behind a port | Medium |
| Modules | All routers always mounted | Conditional mount from `ModuleRegistry` | Low |
| Backup | **Not present anywhere** | Nightly encrypted copy to the owner's synced folder | Medium |
| Onboarding | Invite-gated signup | Local first-run wizard | Medium |

**The critical constraint: do not fork the engine.** Ingestion, USALI mapping, reporting, labour,
tenancy and the disclosure rules stay as close to upstream as possible, so improvements flow both
ways. Every change above is at an edge — packaging, identity issuance, transport — not in the
accounting core.

**Decisions to record as ADRs before building:**

- **ADR-D1** Local single-tenant issuer replacing Keycloak for desktop deployments
- **ADR-D2** Bring-your-own-AI with an enforced content allow-list and audit
- **ADR-D3** Module gating at router mount
- **ADR-D4** Backup and restore posture

---

## 9. Milestones

Each milestone ends in something installable by a real person.

| | Milestone | Contents | Estimate |
|---|---|---|---|
| **M1** | **It runs without Docker** | Bundled Postgres, PyInstaller engine, static SPA, tray launcher. Unsigned. Folder-watch intake only. No AI, no modules. | 3–4 weeks |
| **M2** | **It has a front door** | Local accounts, Argon2id, recovery code, first-run wizard, module chooser, limitations surface. | 3 weeks |
| **M3** | **It's trustworthy** | Code signing and notarisation both platforms, auto-update, **backup and restore**. First outside testers. | 2 weeks |
| **M4** | **It's connected** | Himalaya email intake; AI via the two adapters with cap, allow-list and audit. | 3 weeks |
| **M5** | **It's reviewable** | Public repository, documentation, sample data, a five-minute video, an issue template. | 2 weeks |

**Roughly 13 weeks for one experienced developer.** M1–M3 is the honest minimum for putting it in
front of a hotel owner; M1–M2 is enough for developers to review.

---

## 10. Repository and licensing

Upstream is **Apache-2.0**, which permits this without asking. The obligations are real but light:

1. Include the Apache 2.0 licence text.
2. Retain all copyright, patent, trademark and attribution notices.
3. Carry forward the contents of the upstream `NOTICE` file.
4. **State prominently that files have been modified** — Apache 2.0 §4(b).

Beyond the licence, three things are worth doing because they're right, not because they're
required:

- **Say what this is, in the README's first paragraph:** a desktop-focused build of
  `csharp36/open-hospitality`, with a link upstream and a plain statement of how it differs.
- **Don't imply endorsement.** A distinct name and no use of upstream's branding or domains.
- **Send fixes upstream.** Anything improved in the shared engine should go back as a pull request.
  A fork that only takes is a bad neighbour; one that contributes is a second pair of hands.

### A judgement call worth making deliberately

A public fork of an actively-developed project reads as a statement, whether or not it's meant as
one — and you are in an ongoing conversation with its maintainer. Two framings:

- **"A desktop build we're prototyping"** — named as an experiment, README points upstream, changes
  offered back. Reads as collaboration.
- **"A separate product"** — own name, own direction, own roadmap. Entirely legitimate under the
  licence, and it reads as a split.

Both are defensible. It is much easier to start with the first and move to the second than the
reverse — and worth one message to Chris before the repository goes public, not after.

### Naming

The build needs its own name. Candidate directions: something plain and descriptive
(*Night Audit*, *Front Desk Books*), or something that signals the ownership model
(*Ledgerhouse*, *Housekeeping*). **Open decision — not blocking M1.**

---

## 11. Open decisions

| # | Decision | Blocks | Recommendation |
|---|---|---|---|
| 1 | Fork framing — experiment or separate product | Public repo | Start as an experiment; message Chris first |
| 2 | Name | M5 | Not urgent; placeholder is fine through M4 |
| 3 | Whose Apple and Microsoft developer accounts sign the app | M3 | Whoever signs owns the distribution channel — decide before, not after |
| 4 | Support model — community only, or is someone answering | M5 | Say which, publicly, at launch |
| 5 | Bank feed: statement upload only at v1, or aggregator too | M4 | Upload only at v1. An aggregator needs an entity. |
| 6 | Is the GL module in scope, given upstream is building one | M4 | Track upstream; don't build a second one |

---

## 12. Risks

| Risk | Impact | What we do about it |
|---|---|---|
| **Upstream diverges so fast the fork can't track it** | High — 456 commits in 3 weeks | Keep changes strictly at the edges. Rebase weekly. Never touch the accounting core. |
| **A PMS changes its report layout** | High — silent wrong numbers | Already handled: parse failures quarantine and fail loud. Keep that. Never "best effort" parse. |
| **Owner loses their laptop with no backup** | Severe — total data loss | Backup is in the setup flow, not settings. Nag until configured. |
| **Owner forgets password and recovery code** | Severe — data unrecoverable | State it once, plainly, at setup. Do not build a back door — a back door is a vulnerability with better marketing. |
| **A mapping error produces wrong books** | High | Human confirms every AI suggestion; every figure traces to a source document; PMS→ledger reconciliation must be zero |
| **Nobody uses it** | Fatal | M3 puts it in front of three real owners before M4 is built |
| **One-maintainer bus factor** | High | Documented decisions, tests as specification, nothing clever |

---

## 13. Success measures

**At M3 — does it work for a human?**
- 3 of 3 test owners install and reach a real operating statement unaided
- Zero support contacts needed to complete setup
- Time from download to first number: under 15 minutes

**At M5 — does it work in the world?**
- 10 installs that survive past 30 days
- At least one owner who cancels an existing paid tool because of it
- At least one fix contributed back upstream

**Always:**
- $0/month for the owner, for the core product
- $0/month infrastructure for the project
- Zero surprise charges. Ever.

---

## Appendix A — Words this product does not use

| Never | Instead |
|---|---|
| workspace | hotel group |
| sandbox | practice copy |
| dependency | *(never mentioned — it's already inside)* |
| API key | your helper account |
| ingest / sync | get your reports |
| reconcile | check against your bank |
| provision / configure / deploy | set up |
| credentials | password |
| tenant / org | your hotel group |
| jurisdiction | state |
| quarantine | we couldn't read this one |
| not connected | off |

## Appendix B — Sources

- [Upstream repository](https://github.com/csharp36/open-hospitality) — `bba21e7`, 8 Sep 2026; `ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/adr/adr-012-bank-aggregator-tokens.md`, `server.py`, `tests/authkit.py`
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) — §4 redistribution terms
- [Himalaya](https://github.com/pimalaya/himalaya) — licence, protocols, JSON output
- [OpenRouter pricing and API compatibility](https://costbench.com/software/llm-api-providers/openrouter/)
- [Apple Developer Program](https://developer.apple.com/programs/enroll/) · [Windows code signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)

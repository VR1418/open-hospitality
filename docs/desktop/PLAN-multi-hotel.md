# Plan — the multi-hotel owner's picture

*Asked for 14 September 2026: emails carrying several hotels' night audits in one inbox need rules for which subject belongs to which hotel, with "add the hotel" when none matches; the Overview should show the whole portfolio with a way to look at one hotel, total rooms and rooms sold, and an owner-set breakeven per hotel so it is plain which hotels are making money; and once the day's reports are in, the whole picture — the overview and every hotel's numbers with the breakdown — should be emailed to addresses the owner supplies. Below is what exists, what to build, in what order, and what each piece is for.*

## What exists today, and where it falls short

| Today | Falls short when |
|---|---|
| A report is filed under a hotel by what its own header prints (a code on choiceADVANTAGE; a name on OPERA and AutoClerk), matched against the hotel's registered name or code. Nothing about the email decides it. | Two hotels' reports print the same brand name; a system prints neither name nor code; or a hotel isn't set up yet — the file lands in *Reports we couldn't read* with "which hotel to add", and the owner has to notice. |
| The Overview is all hotels: This morning, What's connected, a hotels table, totals, a 14-day revenue trend, last night's findings, staff. The hotel picker at the top right is ignored here. | An owner with six hotels wants to narrow to one without leaving the page; wants rooms, not only revenue; and has no way to say what each hotel needs to make. |
| Per-hotel facts in the books: revenue, occupancy, ADR, RevPAR, rooms sold, rooms total (from the report, or the inventory), month revenue, estimated labour. | No owner-entered number exists anywhere, so "profit" can't be shown. |

## Part A — Email rules: which subject line is which hotel

**Rule.** *When the subject contains "…" (and, optionally, the sender is …) → the report belongs to hotel X.* First matching rule wins; rules are reordered by drag or arrows. A "Try a subject" box shows which rule a pasted subject would hit.

**Where it lives.** A `rules` list in the mail settings (`desktop.setting` key `mail_settings`, beside senders), one screen down from *Take reports only from these senders* on **Reports by email**.

**How it is used.** When the mailbox is read, each PDF saved into *Drop reports here* gets a sidecar note (`<file>.hint.json`: subject, sender, the hotel the rule chose). The intake passes that hotel to the reader as a *hint*. Then:

- The report's own header still decides when it can. If it agrees with the hint, or prints nothing usable, the hint stands.
- If the header names a **different** hotel from the rule, the file is set aside with the plain reason — *"the subject says Redstone Inn, the report says Cedar Point"* — rather than filed under the wrong books. A rule may not overrule the report; it may only fill in what the report leaves out.
- The hint also lets a report with **no** printed name or code be read at all — the case that is unreadable today.

**When nothing matches.** The file goes to *Reports we couldn't read* as now, **and** the Email page (and *Just read* on Add reports) shows a **"From a hotel you haven't set up"** list: subject, sender, and what the header printed (code and name when present). Each row has **Add this hotel**, which opens the wizard's add-a-hotel step pre-filled (code and front-desk system from the header, name from the subject) and, on save, writes the rule *subject contains "…" → new hotel* and re-reads the file. One flow, two clicks.

**Learning a rule from a manual fix.** On Add reports, when the owner files an unreadable email report under a hotel by hand, offer *"Always file emails with this subject under X"* — the same rule, made from the fix.

**Guard rails.** A rule can never send a report to a hotel the report contradicts; rules are shown in plain words; the sidecar is deleted with the file; nothing about the email body is read (unchanged).

**Code touched.** `mail.py` (`_save` writes the sidecar; `MailSettings.rules`; `MailState.unrouted`), `mail_api.py` (rules and unrouted in GET/PUT), `intake.py` (reads the sidecar, passes the hint), **upstream** `ingestion.py` (`process_upload(..., property_hint=)`, the contradiction check; listed in NOTICE), `welcome_api.py` (prefill from a hint), `EmailPage.tsx` (rules editor, try-a-subject, the unrouted list), `WelcomePage.tsx` (prefill), `RecentReportsCard.tsx`. Tests: mail stand-in with three hotels' subjects; a contradicting header; the add-from-unrouted flow in the e2e walk.

## Part B — The Overview for the whole portfolio

### B1. All hotels, or one

A selector in the page header: **All hotels ▾** listing each hotel. Choosing one keeps the page and narrows every card to that hotel (the portfolio endpoint takes `?property=`); the hotel dashboard stays one click away. "All hotels" is the default and what the app opens on.

### B2. Rooms, not only revenue

A **Rooms** card beside the totals: *412 rooms across 3 hotels · 318 sold last night (77%) · this month 9,420 of 12,360 room-nights sold (76%)*. The hotels table gains **Rooms** (sold / total) and **Labour %** (estimated labour ÷ revenue, month to date). Portfolio occupancy becomes rooms sold ÷ rooms available, which is the honest figure across hotels of different sizes (an average of percentages is not).

**Code.** `portfolio_api.py`: `rooms_sold`, `rooms_total`, `rooms_sold_month`, `rooms_available_month` per hotel and in totals, read from the statistics already promoted (`ROOMS_OCCUPIED`, `TOTAL_ROOMS`, and the room inventory where a system prints no total).

### B3. Breakeven — the owner's number

**What it is.** For each hotel, the owner types one number: **the revenue the hotel needs in a year to cover its costs** — the annual breakeven, worked out from their own past years (rent or mortgage, payroll, utilities, franchise fees, everything). It is the owner's estimate; they change it whenever they know better, and the app never guesses it.

**Why a year, and what the app does with it.** Hotel costs are yearly things and hotel revenue is seasonal, so a monthly figure would be wrong in both directions. The app divides the annual number by the days in the year (365, or 366) into a **breakeven per day**, and every comparison is against that:

- *Last night:* revenue against the daily breakeven — above or below, by how much.
- *Month to date:* revenue against daily breakeven × days elapsed.
- *Year to date:* revenue against daily breakeven × days elapsed this year — the one that answers "will the year cover it?"
- *Heading for:* year-to-date ÷ days elapsed × days in the year, a plain run rate the card names as such (a busy season ahead or behind will move it, and the card says so).

The verdict, in words: **"Above breakeven — $1,640 a night against $1,479 needed; heading for $598,000 this year against $540,000"** in green, or **"Behind — $310 a night short; at this pace $497,000 against $540,000"** in red, or **"No breakeven set — type this hotel's annual breakeven"** with the pencil.

**Heading for — shaped by last year, when the report carries it.** A plain run rate ignores the seasons. But the night audit itself often prints **last year**: choiceADVANTAGE's Hotel Statistics carries *Last Year PTD* and *Last YTD* revenue beside this year's, and the app already keeps those columns apart (`is_prior_year`). So where they exist, the projection is shaped by the hotel's own past year:

- *growth so far* = this year's revenue to date ÷ last year's revenue to the same date (both printed on the report);
- *heading for* = last year's full-year revenue × growth so far.

Last year's full-year revenue comes from the report where a report prints it (a January audit's *Last YTD* is the whole prior year), from the app's own books once it has read a full year, or — until then — from **one more number the owner can type beside the breakeven: last year's total revenue**, which every owner has from their tax return. When none of the three is known, the card falls back to the plain run rate and says so: *"a plain run rate — type last year's revenue for a seasonal projection"*. Systems that print no last-year column (AutoClerk's pack, OPERA's trial balance) use the owner's number or the run rate, and the card names which it used.

The projection is then compared with the annual breakeven: **"Heading for $598,000 this year (shaped by last year's seasons) against $540,000 needed."**

**Where it is entered.** On the Overview's Profit picture card (a pencil beside each hotel → *Annual breakeven* and, optionally, *Last year's revenue* → Save; the card shows the per-day figure it makes, so the owner can sanity-check it), and on **Your hotels**. Stored in the hotel profile setting (`hotel_profiles`, beside the ownership entity), per hotel, with when it was last changed. Changing it re-reads the whole picture at once — nothing is stored from an old number.

A **Profit picture** card at the top, under This morning: one bar per hotel (year to date against where the year should be by today, with last night marked), the portfolio total on the first line — *"3 hotels · 2 above breakeven, 1 behind · $9,300 above year to date"* — and the worst first.

**Words.** "Breakeven" is the owner's term and stays. The card never says "profit": revenue above breakeven is what the owner's own estimate says is profit, and the card says *above breakeven*. Estimated labour is shown beside it as the one cost the app does know.

### B3c. A budget, if the owner has one

Many owners already keep a budget — a revenue figure per month, sometimes per department, often with the costs beside it. That is better than any projection the app can make, so the app takes it.

**How it is uploaded.** On **Your hotels** (and from the pencil on the Profit picture card): **Upload a budget** takes a spreadsheet — `.xlsx` or `.csv` — one row per month. A **Download the template** button gives the exact shape: *Month · Total revenue · Room revenue (optional) · Other revenue (optional) · Rooms sold (optional) · Costs (optional)*, twelve rows, this year. The owner fills the total revenue column at least; anything else is a bonus. The upload is read with the same care as a bank statement (headers matched by name, not position; numbers with commas and $ accepted; a month written as "Jan", "January", "2026-01" or "1/2026" all understood), and the page shows what it read before it is saved: *"12 months, total $612,000 — save?"*

**What the budget does.**

- **The seasonal shape.** Where a budget exists, the projection uses it first: *heading for* = actual to date + budget for the rest of the year × (actual to date ÷ budget to date). Budget beats last year's report, which beats the owner's single number, which beats the run rate — and the card always says which it used.
- **Month against budget.** *Month so far* gains *vs budget to date* per hotel and in the totals; the Profit picture gains a budget marker on each bar.
- **Breakeven from the budget.** If the budget carries a costs column, the annual breakeven is filled from it (the owner can still overwrite it); if not, the breakeven stays the owner's number.
- **Needs a look** gains *behind budget* — a hotel more than 5% under its budget to date.
- The morning email carries *vs budget* on every hotel's block.

**Where it lives.** A `desktop.budget_line` table (hotel, year, month, the figures, uploaded when, file name), one budget per hotel per year, replaced whole on re-upload — never merged, so what the owner sees on the page is exactly the file they sent. A budget is not a book entry; nothing in the ledger changes.

**Code.** `src/usali/desktop/budgets.py` (parse like `statements.py` parses a CSV, plus `.xlsx` through openpyxl, which the accountant pack already uses), `budgets_api.py` (template, preview, save, get), migration `d0007_budgets`, `portfolio_api.py` (budget to date and the projection basis), `PropertyConfigPage.tsx` / the Profit picture pencil, and the morning email.

### B4. Needs a look — the operational picture in one list

Extend *Last night's audit* into **Needs a look**, worst first, each line a hotel, a reason and a link:

- last night's report missing (exists);
- a check on the audit failed (exists);
- **behind breakeven** last night or year to date (new, from B3), or **behind budget** to date (B3c);
- **occupancy fell** more than 15 points against the hotel's own last 7 nights (new);
- **codes waiting** to be confirmed for that hotel (new; the count exists);
- **labour above** the owner's target for that hotel, when a target is set (later — needs a labour target, the same shape as breakeven).

An empty list says so: *"Nothing to look at — every hotel's reports are in, balances tie, and all are on pace."*

### B5. Month against month

*Month so far* gains **vs last month to the same day** and, when a year of books exists, **vs the same month last year** — per hotel in the table, and in the totals. The 14-day trend gains a small per-hotel line in each table row, so a dip is seen where it happened.

### B6. The morning sheet

The app already writes a daily summary PDF per hotel into *Saved reports*. A **portfolio morning sheet** — the Profit picture, the Rooms line, Needs a look, then one section per hotel with its breakdown — is written each night beside them. It is the page an owner prints, and it is what Part C sends.

## Part C — The report in the owner's mailbox

**What the owner asks for.** *"After today's reports are in, email the whole thing to me (and my partner, and my accountant)."* Addresses the owner types, as many as they like.

**What is sent.** One email a day, in plain words, no login needed to read it:

- **The body** is the overview, readable on a phone: the date; the portfolio line (*3 hotels · $14,887 revenue · 318 of 412 rooms sold, 77% · month to date $148,300 · 2 above breakeven, 1 behind*); then **one block per hotel** — revenue, rooms sold of total, occupancy, average rate, RevPAR, month to date, the breakeven verdict, estimated labour, codes waiting — and *Needs a look* at the end. A hotel whose report has not arrived is listed as **not in yet**, never shown as zero.
- **Attached:** the portfolio morning sheet (B6) and each hotel's daily summary PDF, the same files already in *Saved reports*, so the breakdown by department and charge code is there without opening the app.
- Nothing in it names a guest or an employee: the summaries never carried one. It does carry money, which is why the recipients are the owner's own list and nothing else.

**When it goes.** Two choices on the page, like the collect schedule:

- *As soon as every hotel's report for last night is in* (the usual case: the intake reads the last one, waits a minute for stragglers, sends).
- *At a fixed time* (say 7:30 AM) *with whatever is in*, saying which hotels are missing — for the owner who wants the email at the same time every day.

Either way, **one email per business date**: a late report re-read after the send updates the books, and the next morning's email says so, rather than sending twice. A **Send now** button sends today's, for the owner who wants to see it before trusting the schedule.

**How it sends.** Through the same mail account already set up for collecting reports — Gmail, Yahoo, iCloud and IMAP all pair with an SMTP server, and the app password already saved works for both — so for most owners this is *an address to type and a switch to turn on*. An owner who collects nothing by email fills in the mail account here instead (the same form). The page has **Send a test** and shows *last sent · to whom · what it contained*, and any refusal in the mail service's own words. Nothing else is ever sent from that account.

**Code.** `mail.py` gains an `Outbox` (SMTP, `smtplib` with STARTTLS/SSL, presets beside the IMAP ones); `mail_api.py` gains the recipients, the schedule and *Send a test*; `saved_reports.py` writes the portfolio sheet (B6) and hands the intake a "day complete" signal; a `morning_mail.py` thread composes the body from the same figures as `portfolio_api` (one source of truth) and sends once per date; `EmailPage.tsx` gains a **Send the morning report to** section. Tests: the mail stand-in grows a fake SMTP; one email per date; missing hotels named; the body's numbers match the Overview's.

## Order, and what each step is worth

| Step | Builds | Owner gets | Effort |
|---|---|---|---|
| 1 | B1 selector · B2 rooms · table columns · sortable table | The whole portfolio in rooms and money, and one hotel in a click | **Built 14 Sep** (sorting not yet) |
| 2 | B3 breakeven and last year's revenue · **B3c budget upload with a template** · Profit picture card · B4 list | Which hotels are making money, at a glance, by their own numbers — and against their budget | **B3, B4 built 14 Sep**; B3c next |
| 3 | A email rules · unrouted list · Add this hotel from an email · the reader's hint | Six hotels' audits in one inbox file themselves; a new hotel is two clicks | 1–1½ days |
| 4 | B6 morning sheet · **C the report in the mailbox** (recipients, schedule, send once per date, Send a test) | The whole picture, every morning, in the owner's inbox — no app to open | 1–1½ days |
| 5 | B5 month comparisons | The picture over time | ½ day |

Each step ships with its own tests, an e2e step (rules with three hotels' subjects; a breakeven typed and the verdict checked; a hotel added from an unrouted email), the nine checks, and a packaged walk before a zip.

## Two things to confirm before step 2

1. **Breakeven is one annual total-revenue figure per hotel**, from the owner's own past years; the app divides it by the days in the year and compares every day, month and year against that. Room revenue only, or a monthly figure, would both mislead — total revenue and a year it is.
2. **The projection is shaped by last year where the report prints it** (growth so far × last year's total), and by a plain run rate otherwise — the card always says which. Last year's total may be typed by the owner until the books or a report supply it.

3. **The email is sent from the same account the reports are collected from.** Simplest for the owner, and the app password already saved covers sending. A separate sending account can be added later if someone needs it.

If these are fine, step 1 starts on "go".

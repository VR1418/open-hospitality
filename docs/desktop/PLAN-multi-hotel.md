# Plan — the multi-hotel owner's picture

*Asked for 14 September 2026: emails carrying several hotels' night audits in one inbox need rules for which subject belongs to which hotel, with "add the hotel" when none matches; the Overview should show the whole portfolio with a way to look at one hotel, total rooms and rooms sold, and an owner-set breakeven per hotel so it is plain which hotels are making money. Below is what exists, what to build, in what order, and what each piece is for.*

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

**What it is.** For each hotel, the owner types one number: **the revenue the hotel needs in a month to cover its costs** (rent or mortgage, payroll, utilities, franchise fees…). It is an estimate the owner owns, changed any time, and the app never guesses it.

**Where it is entered.** On the Overview's Profit picture card (a pencil beside each hotel → type → Save), and on **Your hotels**. Stored in the hotel profile setting (`hotel_profiles`, beside the ownership entity), so it is per hotel and survives everything.

**What the app shows from it.** For each hotel, month to date:

- *Where it should be by today:* breakeven × (days elapsed ÷ days in month).
- *Where it is:* month-to-date revenue.
- *Where it is heading:* month-to-date ÷ days elapsed × days in month (a plain run rate — the card says so, and says a weekend-heavy month will read low early).
- The verdict, in words: **"Above breakeven pace — heading for $48,200 against $45,000"** in green, or **"Behind — short $6,100 at this pace"** in red, or **"No breakeven set"** with the pencil.

A **Profit picture** card at the top, under This morning: one bar per hotel (month-to-date against breakeven, with a marker for where today should be), the portfolio total on the first line — *"3 hotels · 2 above breakeven pace, 1 behind · $9,300 above in total"* — and the worst first.

**Words.** "Breakeven" is the owner's term and stays. The card never says "profit": revenue above breakeven is what the owner's own estimate says is profit, and the card says *above breakeven*. Estimated labour is shown beside it as the one cost the app does know.

### B4. Needs a look — the operational picture in one list

Extend *Last night's audit* into **Needs a look**, worst first, each line a hotel, a reason and a link:

- last night's report missing (exists);
- a check on the audit failed (exists);
- **behind breakeven pace** (new, from B3);
- **occupancy fell** more than 15 points against the hotel's own last 7 nights (new);
- **codes waiting** to be confirmed for that hotel (new; the count exists);
- **labour above** the owner's target for that hotel, when a target is set (later — needs a labour target, the same shape as breakeven).

An empty list says so: *"Nothing to look at — every hotel's reports are in, balances tie, and all are on pace."*

### B5. Month against month

*Month so far* gains **vs last month to the same day** and, when a year of books exists, **vs the same month last year** — per hotel in the table, and in the totals. The 14-day trend gains a small per-hotel line in each table row, so a dip is seen where it happened.

### B6. The morning sheet (optional)

The app already writes a daily summary PDF per hotel into *Saved reports*. A **portfolio morning sheet** — one page: the Profit picture, the Rooms line, Needs a look — written each night beside them, is the thing an owner prints or forwards to a partner.

## Order, and what each step is worth

| Step | Builds | Owner gets | Effort |
|---|---|---|---|
| 1 | B1 selector · B2 rooms · table columns · sortable table | The whole portfolio in rooms and money, and one hotel in a click | 1 day |
| 2 | B3 breakeven: setting, entry on two pages, Profit picture card · B4 list | Which hotels are making money, at a glance, by their own number | 1 day |
| 3 | A email rules · unrouted list · Add this hotel from an email · the reader's hint | Six hotels' audits in one inbox file themselves; a new hotel is two clicks | 1–1½ days |
| 4 | B5 month comparisons · B6 morning sheet | The picture over time, and a page to forward | ½–1 day |

Each step ships with its own tests, an e2e step (rules with three hotels' subjects; a breakeven typed and the verdict checked; a hotel added from an unrouted email), the nine checks, and a packaged walk before a zip.

## Two things to confirm before step 2

1. **Breakeven is total revenue per calendar month.** Not per fiscal period, not room revenue only. (Calendar month matches how owners think of rent and payroll; a 4-4-5 hotel can be handled later.)
2. **The verdict uses a plain run rate.** Month-to-date ÷ days elapsed × days in month. Simple and honest early in the month; a later version can weight by the hotel's own day-of-week pattern.

If both are fine, step 1 starts on "go".

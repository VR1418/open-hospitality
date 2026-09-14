# How the PII holdback works — a walkthrough

*Written for the upstream author's question, 14 September 2026: "card numbers and SSNs never leave the PC" is now a promise in writing in front of owners; OCR'd audit packs split numbers across line breaks and the standard patterns miss those. This is exactly what the mechanism does, what it does not do, and what was changed today because of the question.*

## Two different questions, protected two different ways

The AI helper asks a provider two kinds of question. They are protected differently because they are different problems.

### 1. "Where does charge code X belong?" — safe by construction

`src/usali/desktop/ai/allowlist.py`, `CodeQuestion`.

The prompt is assembled from one typed object with named fields — the front-desk system, the code, the description **as printed on the report**, how often it was seen, the dates, the amounts, and the USALI lines it may be filed on. There is no other path from the database to the prompt. The queries that build a `CodeQuestion` read the transaction-code staging table and the mapping dictionary; they never touch a guest, staff, payroll, bank or account table, so a name, a pay rate, an SSN or a card number is **structurally absent** — not filtered out, never there.

The one field that carries free text is the description the report printed beside the code ("Room Charge", "Visa Payment"). That is why the scan below runs on this question too: if a front-desk system ever printed a guest's name in a code description, the request is refused, and a refused request is a failing test and a visible error rather than something masked and forgotten.

### 2. "Read this report nobody has a reader for" — filtered, page by page

`src/usali/desktop/ai/pages.py`, then `allowlist.check`.

This question cannot be built from typed fields: its whole content is text we did not write. So the protection moves earlier, and it is deliberately blunt:

1. **The unit is the page.** The PDF is split into pages, and each page is rendered as rows the way the engine's own readers see it (`cluster_rows`). A page either goes **whole** or is **held back whole**. Nothing is masked, trimmed or edited to make a page acceptable, because a masked page leaves us guessing whether what remained was safe.
2. **A page is judged by what it is** before by what is on it (new today, see below): a page whose title names a section about guests, accounts or staff is held back without further reading.
3. **Then the scan** (`allowlist.check`) runs on the page text. If it finds anything forbidden, the page is held back and the owner is told *the kind* of thing found — never the value.
4. **If nothing survives, nothing is sent.** The owner sees how many pages were held back and why.

Measured on the real choiceADVANTAGE pack that prompted the feature: 21 of 48 pages survive, none carries a person's name, and the survivors are the summary pages — which are the only part the books need.

## What the scan recognises

| Shape | Rule | Since |
|---|---|---|
| Card number on one line, spaces or hyphens between groups | `redaction.mask_pans`: a 13–19-digit run that passes the **Luhn check** | original |
| **Card number split across whitespace, tabs, hyphens or line breaks** — 4-4-4-4, or Amex 4-6-5 | groups joined, then Luhn | **today** |
| Nine or more bare digits in a row (account, routing, unformatted SSN) | digit run ≥ 9 | original |
| SSN as printed, `123-45-6789` | fixed-position windows | original |
| **SSN with its groups split across a break** — `123-45-\n6789`, `123 - 45 - 6789` | hyphens required, any whitespace around them | **today** |
| Guest name as a front-desk system prints one, `DOE, JANE MARIE` | two capitalised runs around a comma | original |
| **The same with the break after the comma** — `DOE,\nJANE` | comma then any whitespace | **today** |
| An employee's name, any case | this hotel group's staff names from the database, as needles | original |
| **An email address; a phone number** `(408) 555-0134`, `408-555-0134` | patterns | **today** |

And, before the scan, **what the page is** (`pages.section_about_people`, today):

- a page whose **title** (first line) contains any of: guest, ledger, aging, in house, arrival, departure, no show, reservation, cashier, folio, registration, payroll, employee, staff, tax exempt, pre-paid, deposit, credit limit, direct bill detail, company, travel agent, member — is held back as *a section about people or accounts*;
- a page that lists people in **mixed case line after line** (`Doe, Jane` / `Roe, Richard` / …, more than two such lines) is held back as *a list of people's names*, whatever its title. One such line is a column heading ("Name, Company"); several are a guest list.

## What it deliberately does not do, and why

- **It does not join every digit across every space.** A statistics page is columns of integers — `Total Rooms 60 46 47 44 2026 47 318 45` — and joining those would make "long digit runs" of everything and hold back the one page the books need. So the cross-break rules are shaped: card-like groups put to the Luhn check (four year-like columns are not a card unless they happen to pass Luhn, in which case the page is held back — the safe direction); SSNs must keep at least one hyphen (`318 45 2026` is rooms, a percentage and a year).
- **It cannot recognise a lone guest name in prose** — "Jane Doe checked out" has no shape a pattern can tell from "Room Charge". That is why pages are judged by what they are first: a guest's name lives on guest pages, and guest pages are held back by title and by density before the scan is asked. A single stray name on a summary page is the residual risk, and it is stated here rather than promised away.
- **It never masks.** A masked page would be sent with our guess about what remained. A held-back page is not sent at all, and the owner is told.
- **It never logs the value.** `BlockedContent` carries the kind ("something shaped like a card number"), never the thing; a reason that quoted the number would copy it into the log the reason ends up in.
- **A provider error never carries the request.** `AiError` messages say what failed and what the owner can do, nothing about what was sent (the same rule as the payroll provider adapter).

## How it is tested

`tests/test_desktop_ai_allowlist.py` and `tests/test_desktop_ai_pages.py`, offline, no key:

- every shape in the table above is refused, and the refusal never quotes the value;
- a built code question is never refused (the two halves must agree, or the scan would be switched off);
- summary rows and statistics rows pass — `RM Room Charge 7,147.07 T1 State Occ Tax 437.42`, `Total Rooms 60 46 47 44 2026 47 318 45`, `Rooms available 2026 2025 2024 2022`;
- on the real sample pack, the summary survives and the guest pages do not, a page is kept or dropped whole, an employee name holds a page back, and an unreadable file sends nothing.

## What would make it stronger still

- **Run the page filter on OCR'd text from real scanned packs**, not only born-digital PDFs — the current sample is born-digital. A tester's scanned pack (with the guest pages removed by hand) is the next fixture worth having.
- **Address-shaped lines** (street number + name + ZIP) are not yet a shape; they live on guest pages, which are held back by title, but a rule would close the residual.
- **A per-hotel "never send" word list** the owner can add to (a franchise name, a manager's nickname) — the employee-name needle mechanism already exists; this is a UI for it.

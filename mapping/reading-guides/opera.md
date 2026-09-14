---
system: OPERA
shown_as: Oracle OPERA
tags: [reading-guide]
---

# Oracle OPERA — reading the night audit

OPERA's night audit is **several separate PDFs**, one report each.

## Which hotel

The first line of every page is the hotel's **name in capitals**, as set up in
OPERA. OPERA does not print a short hotel code there, so the hotel is recognised
by that printed name — which is why setup asks for it exactly as printed.

## Which night

The header prints the business date as `MM-DD-YY` (for example `07-07-26`),
next to the time the report was run.

## Trial Balance — the money

- Sections: **Daily Transactions**, then the ledgers (guest, city/A/R, deposit,
  package).
- Each transaction line is a **number code**, a description, and the amount:
  `1000 *Accommodation 10,395.00`, `5105 Parking 410.00`.
- Revenue, taxes and payments all appear as lines; the code range and the
  description say which. Payments are money coming in, not revenue.
- `Balance Brought Forward` is yesterday's ledger balance, not a transaction.
- The ledger section at the end gives each ledger's opening and closing balance;
  a trial balance always has one.

## Manager Flash — the rooms

- Columns: `DAY MONTH YEAR` for this year, then the same three for last year.
- Lines include `Rooms Occupied`, `Total Rooms in Hotel`, `% Rooms Occupied`,
  average rate and revenue per available room.

## Market Code Statistics — who stayed

Rooms and room revenue by market segment, for the day, month and year.

# Open Hospitality — installing it, and what to expect

*For the first few people trying this. Windows 10 or 11. About 20 minutes,
most of it your own reading.*

## Before you start

- **5 GB of free disk space.** Everything the app needs is inside it —
  there is nothing else to install, and no account to create with us.
- **Your night audit reports** as PDFs, the ones your front-desk system
  emails out every morning.
- **No internet needed.** The app runs entirely on your computer.

## 1. Install it

1. Unzip the folder you were sent. **Somewhere with a short path** —
   `C:\Open Hospitality` is ideal. Windows still refuses file names longer
   than 260 characters, and some of the files inside are long, so unzipping
   into something deeply nested can silently leave a few behind. If it starts
   and immediately closes with an error naming a file it can't find, that is
   what happened: unzip it again somewhere shorter.
2. Open that folder and double-click **Open Hospitality.exe**.

## 2. The warning you will see

Windows will stop you the first time, with a blue box saying **"Windows
protected your PC"**.

**This is expected.** It appears because the app isn't signed yet — signing
means buying a certificate, and that hasn't been done during testing. It is
not a virus warning, and Windows is not telling you anything is wrong; it is
telling you it doesn't recognise the publisher.

To continue: click **More info**, then **Run anyway**.

You will see it on the first run. If it bothers you, say so — it is the
single thing most likely to stop a real owner, and that's worth knowing.

A black window shows the app starting. If something stops it starting, the
reason is written there. Once it is running, the black window tucks itself
away and the ◆ icon near the clock (bottom-right) is how you reach the app.

The first time it runs, it also puts an **Open Hospitality** icon on your
Desktop and in the Start menu. Use that from now on. Opening it again while
the app is already running just brings up its window.

## 3. Setting up your books

The app opens in its own window: no tabs and no address bar. It uses Microsoft
Edge behind the scenes, which every copy of Windows has. If the window
doesn't appear, click the ◆ icon near the clock and choose **Open my books**.

1. **Create your account** — your name, the email you'll sign in with, and a
   password. Nothing is sent anywhere; this is all on your computer.
2. **Save your recovery code.** It is shown once. Write it down, or print
   it, and keep it somewhere that isn't this computer.
   **If you forget your password and lose this code, nobody can open your
   books — not even us.** There is no reset email, because there is no email.
3. **Five short questions:** your hotel group's name; your first hotel; its
   financial year; where backups go; and which parts of the app you want.

For each hotel it asks for three things: the **ownership entity** (the
company that owns the hotel), the **hotel name**, and the **hotel code**. The
code is the one printed at the top of your night audit reports next to
"Property Code", for example NM236. That code is how the app knows which
hotel a report belongs to, so type it exactly.

It doesn't ask how many rooms the hotel has: it reads that from your first
night audit.

If your front-desk system prints the hotel's name on reports instead of a code
(OPERA and AutoClerk do), you're also asked for the name exactly as printed.

**Got "these reports are for a hotel that isn't set up here yet"?** The
message names the hotel and its code. Go to **Overview › Add a hotel**, enter
that code, then drop the report in again. You'll find it in **Reports we
couldn't read**.

## 4. Give it your reports

Put your night audit PDFs in **Documents › Open Hospitality › Drop reports
here**. Each one is read within a few seconds and moves to **Reports we
read**. Anything it couldn't read goes to **Reports we couldn't read** — send
those to us, they're the most useful thing you can report.

Then open **Overview**: every hotel, last night's figures, and anything the
audit turned up.

**Reports save themselves.** After every night audit, the app writes two files
for that hotel into **Documents › Open Hospitality › Saved reports › (hotel) ›
(month)**:

- **Daily summary (PDF):** rooms, occupancy, ADR, RevPAR and revenue for the
  day, month and year, plus revenue by department, taxes and payments;
- **Accountant pack (Excel):** the month so far (sales, taxes, and the guest,
  city and deposit ledgers), refreshed every night.

**Where everything is:** Overview and **Add reports** both have a **Your report
folders** card listing each folder, how many files it holds, and an **Open
folder** button. The ◆ icon near the clock has **Show my saved reports** too.

## 5. Codes to confirm — the one job only you can do

Your front-desk system labels every charge with a short code of its own.
We ship a guess at what the common ones mean, but on choiceADVANTAGE
especially those codes are set up per hotel, so our guess may be wrong for
yours — and a code we have never seen at all has nowhere to go.

**That second case is the one that matters.** Its money stays out of your
profit and loss. Your books still balance, because the amount is parked in a
holding account, which is why nothing else in the app mentions it.

Open **Accounting › Codes to confirm**. The number at the top is what your
unrecognised codes add up to. Each row says what your report calls the code,
how often it has appeared and for how much. Pick the line it belongs on and
press Confirm: every day that code appears on is worked out again and your
books reposted. Days in a month you have already closed are left alone, and
it tells you so.

Expect ten or twenty minutes, once. It is the most useful thing you can do
with this app, and the most useful thing you can report back on: **any code
you could not work out yourself is worth telling us about.**

## 6. The AI helper, if you want it

Off unless you turn it on, under **Modules**. It is the only part of the app
that can reach the internet, and only with your own AI account.

If you switch it on, go to **AI helper**:

1. **Who you have an account with.** OpenRouter, Anthropic, OpenAI, or a model
   running on your own computer. The screen fills in the web address for you.
2. **Which model.** Pick one from the list. On OpenRouter, Claude is under
   **Anthropic (Claude)**, and **Claude Sonnet 5** is marked recommended. Each
   model shows its price, and picking one fills in the prices, so the monthly
   limit counts dollars.
3. **Paste your key.** The screen says where to get one (on OpenRouter: open
   **Keys** and create one; it starts with `sk-or-`). Then press **Save**.
4. **Press "Check it works".** It asks your model one fixed question that
   contains nothing about your hotel, and tells you whether it answered and
   what that cost (a fraction of a cent).

There is a **practice mode** that answers offline and costs nothing, if you
just want to see what it does.

**What it knows, in notes you can read.** The app keeps
**Documents › Open Hospitality › AI memory** up to date:

- a note for each hotel, with its code, ownership entity, the reports read,
  and every charge code decided (by you, or from an AI suggestion you
  accepted);
- a **reading guide** for each front-desk system: how its night audit is laid
  out and read, which is also what the AI helper is told.

Open that folder in **Obsidian** (free, obsidian.md: choose "Open folder as
vault") to browse it with links between hotels and guides, or read the files in
Notepad. The notes are a mirror: editing one doesn't change how your reports
are read. Make changes in the app.

Then "Ask the AI" appears next to each code you are confirming. It suggests a
line and says why, or it tells you it won't guess — on tax questions it is
meant to refuse rather than risk it.

Three things worth knowing:

- **It only ever suggests.** Nothing reaches your books until you press
  Confirm, and the decision is recorded in your name, not the model's.
- **There is a monthly limit**, $10 to begin with. The app stops when it is
  reached and says so. You can change it.
- **What it is shown is fixed**: the charge code, how your report describes
  it, the dates and the amounts. Never a person's name, a pay rate, a bank
  detail or an account number. The key stays in this computer's password
  store, and is never included in a backup.

## Removing it

Use **Settings › Apps › Installed apps › Open Hospitality › Uninstall**,
or right-click the ◆ icon near the clock and choose **Uninstall Open
Hospitality…**.

- The app closes itself first, so nothing is left half-written.
- It removes the program folder, the Desktop and Start menu icons, and the
  entry in Installed apps.
- It then asks whether to delete **your books** from this computer. The
  answer is **No** unless you choose Yes. Keep them and installing again
  opens the same books. Delete them only if you have a backup and your
  recovery code, or no longer need them.
- It never deletes **Documents › Open Hospitality** (your reports and saved
  reports) or your backups. Those are your files, and the last message says
  where they are.

## 7. Backups, which is the part to get right

You chose a folder during setup — ideally one OneDrive, iCloud or Dropbox
already syncs. A copy of your books is written there when you start the app,
once a day.

To put a backup back on a new computer you need **two things**: the backup
file, and your recovery code. Keep the code somewhere separate from the
computer.

Restoring is a command for now, on a computer with no books on it yet:

```
"Open Hospitality.exe" --restore "D:\your-folder\Open Hospitality 2026-09-11 0410.ohbackup"
```

It asks for your recovery code, and it refuses to write over books that are
already there.

## 8. Stopping and starting

Click the ◆ icon near the clock and choose **Quit**. Your books stay where
they are. Starting it again picks up exactly where you left off.

## What it doesn't do yet

- **Mac.** Windows only for now.
- **Bank feeds, and updates that install themselves.** Neither exists yet.
- **Email.** Reports go in the folder by hand.
- **Front-desk systems:** Oracle OPERA, AutoClerk and choiceADVANTAGE. If
  yours isn't one of those, the app can't read its reports yet.

Leave the AI helper off and every screen works the same — you confirm codes
yourself instead of being offered a suggestion. Nothing is behind it.

## When something goes wrong

Tell us what you were doing and what you saw. If you can, send:

- the black window's last few lines, and
- `Open Hospitality\logs\open-hospitality.log` from
  `C:\Users\<you>\AppData\Local` — it holds no guest names or money, only
  what the app did.

Two things worth reporting even if they seem small: anything you had to read
twice, and anything you expected to be there and wasn't.

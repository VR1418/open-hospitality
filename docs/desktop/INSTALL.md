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

1. Unzip the folder you were sent — `C:\Open Hospitality` is a good place.
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

A black window opens and stays open while the app runs. That is deliberate
for now: it shows what the app is doing, which helps when something goes
wrong.

## 3. Setting up your books

Your browser opens by itself. If it doesn't, look for the ◆ icon near the
clock (bottom-right), click it and choose **Open my books**.

1. **Create your account** — your name, the email you'll sign in with, and a
   password. Nothing is sent anywhere; this is all on your computer.
2. **Save your recovery code.** It is shown once. Write it down, or print
   it, and keep it somewhere that isn't this computer.
   **If you forget your password and lose this code, nobody can open your
   books — not even us.** There is no reset email, because there is no email.
3. **Five short questions:** your hotel group's name; your first hotel; its
   financial year; where backups go; and which parts of the app you want.

On the hotel question, one field matters more than it looks: **the hotel's
name as it appears at the top of your night audit reports**. That is how the
app knows which hotel a report belongs to. Type it exactly as printed —
capital letters don't matter.

## 4. Give it your reports

Put your night audit PDFs in **Documents › Open Hospitality › Drop reports
here**. Each one is read within a few seconds and moves to **Reports we
read**. Anything it couldn't read goes to **Reports we couldn't read** — send
those to us, they're the most useful thing you can report.

Then open **Overview**: every hotel, last night's figures, and anything the
audit turned up.

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

If you switch it on, go to **AI helper**, choose who you have an account with
— OpenRouter, OpenAI, Anthropic, or a model running on your own computer —
and paste the key they gave you. There is a **practice mode** that answers
offline and costs nothing, if you just want to see what it does.

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

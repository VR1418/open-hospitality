# Signing the app — what it costs, and what only you can do

**Status:** not done. The build is ready for it; the certificates are not.
PRD **I-2** ("code-signed and notarised on both platforms; no security warning
on first open") and open decision **3** ("whose Apple and Microsoft developer
accounts sign the app") block on this, and the PRD says to decide it before
M3, not after.

Signing identities are issued to a legal person or company after an identity
check. They cannot be obtained on your behalf, and they should not be: whoever
holds them owns the distribution channel, and their name is what users see.

## What an unsigned build does today

| | Windows | macOS |
|---|---|---|
| First open | SmartScreen: "Windows protected your PC", with **More info → Run anyway** | Gatekeeper refuses outright; the owner must right-click → Open, or clear it in System Settings → Privacy & Security |
| What the owner sees | A blue warning naming an unknown publisher | "Apple could not verify this app is free of malware" |
| Can they proceed? | Yes, two clicks | Yes, but the path is obscure enough that most people stop |

That is the M3 gap: three outside testers cannot be asked to do this.

## The two accounts

**Apple — Apple Developer Program.** About **$99 a year** (Apple charges the
same fee worldwide in local currency; an organisation enrolment also needs a
D-U-N-S number and takes longer). It gives you a Developer ID Application
certificate — the one for apps distributed outside the App Store — and access
to the notary service.

**Windows — a code-signing certificate from a certificate authority.** Roughly
**$200–$450 a year** depending on the CA and the term; the exact figure moves,
so price it when you buy. Two things to know:

- Since June 2023 the private key must live on **certified hardware** — a
  USB token the CA ships you, or a cloud signing service (Azure Trusted
  Signing, DigiCert KeyLocker, SSL.com eSigner). A file on disk is no longer
  allowed. That decides how the build machine signs.
- **Azure Trusted Signing** is the cheapest current route (about **$10 a
  month**) and needs a verified organisation or an individual with three
  years' verifiable history. Worth checking first — it removes the token.
- An **EV** certificate costs more and clears SmartScreen immediately. A
  standard (OV) certificate still shows the warning until the app builds
  reputation, which for a low-volume installer can take a long time. If the
  warning is what you are paying to remove, EV or Trusted Signing is the
  honest choice.

Budget: the PRD's G3 line, "~$220/yr total", matches an Apple membership plus
a modest Windows certificate. EV or a token pushes it higher.

## What happens in the build once you have them

Nothing about the app changes — only the last step of `scripts/desktop/build.py`
and one line in `packaging/desktop/open-hospitality.spec`.

1. **Turn the console window off.** `open-hospitality.spec` sets
   `console=True` with a comment saying M3 turns it off; signed builds should
   not open a black window on launch.
2. **Windows:** sign `Open Hospitality.exe` **and** every bundled `.exe`/`.dll`
   that PyInstaller wrote, then sign the installer if one is added. With a
   token: `signtool sign /tr <CA timestamp URL> /td sha256 /fd sha256 /a <files>`.
   With Trusted Signing, the same `signtool` call through its dlib provider.
   **Timestamp every signature** — without it, everything you shipped stops
   validating the day the certificate expires.
3. **macOS:** sign every binary inside the bundle from the inside out, with a
   hardened runtime (`codesign --deep` is not enough and Apple advises against
   it), then notarise the zipped `.app` with
   `xcrun notarytool submit --apple-id … --team-id … --wait`, then
   `xcrun stapler staple "Open Hospitality.app"` so a first open works
   offline. Python apps usually need the entitlement
   `com.apple.security.cs.allow-unsigned-executable-memory`; add entitlements
   one at a time, only as failures demand.
4. **Keep the secrets out of the repo.** Certificates, tokens and app-specific
   passwords belong in the build machine's own store, never in git and never
   in `.env`.

## What I'd need from you to finish it

- Which name signs the app — you personally, or a company.
- Apple: the Team ID and a Developer ID Application certificate installed on
  the build machine, plus an app-specific password for notarisation.
- Windows: the certificate, and which route (token, or Azure Trusted Signing).

With those in place the signing step is an afternoon: the build already
produces a single folder, and nothing in the app has to change.

## Until then

The app is unsigned, and the M1 note stands: builds keep the console window,
and reviewers see an OS warning on first open. Backup and restore (ADR-D4) and
the update check do not depend on signing, so M3's other two thirds can ship
without it — but **"first outside testers" should wait**, because the warning
is exactly the moment a hotel owner decides this software isn't for them.

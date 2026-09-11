# ADR-D5: The install's keys are sealed under a master key in the OS keychain

- **Status:** Proposed
- **Date:** 2026-09-11
- **Deciders:** desktop-edition owner *(to be named)*; drafted with Claude

## Context

An install has six secrets, generated on first run:

- the three database passwords (owner, app role, provisioner)
- the field-encryption key
- the HPKE private key that opens sealed payroll PII
- the RSA-3072 key that signs sign-in tokens (ADR-D1)

In M1 they sat together in `keys.json` in the per-user app-data folder, in
plain text. PRD A-4 puts the signing key in the OS keychain, and AI-1 says
keys are "never … a config file". Any process running as the owner, and
anything that copies the folder, could read `keys.json`.

Putting each secret in the keychain directly doesn't work on Windows. A
Credential Manager credential holds at most 2,560 bytes, and `keyring` stores
text as UTF-16. The signing key's PEM is about 2.5 KB, so it can't fit.

## Decision

- **Seal the key file.** The six secrets are written together to
  `keys.sealed.json`, encrypted with AES-256-GCM under a random 32-byte
  **master key**. The install's id is bound in as associated data.
- **The master key lives only in the OS keychain:** Windows Credential Manager
  or the macOS Keychain, through `keyring`. The service is `Open Hospitality`
  and the account is `master-key:<install id>`. It is never written to disk,
  and the sealed file on its own opens nothing.
- **Nothing is trusted until it has been read back.** On sealing, the master
  key is stored, read back from the keychain, and used to open the new seal
  before the sealed file is written. Only then is the plain file deleted, and
  only if it holds exactly the sealed keys.
- **M1 installs move over on their first M2 launch.** If the keychain refuses,
  the install keeps running from `keys.json` exactly as before and tries again
  next launch. An existing install is never locked out by this step.
- **A first run refuses rather than write secrets in plain text** when no
  keychain is usable, and says so in plain words.
- **Each install has its own keychain entry,** so two installs on one computer
  (`OH_DATA_DIR`) can't overwrite each other's key.

## Consequences

- A copy of the system folder, on its own, no longer yields the database
  passwords or the signing key.
- **Losing the keychain entry loses the books.** This happens when a user
  profile is reset, or the folder is copied to another computer without the
  keychain. That was already true of losing `keys.json`, but copying the folder
  is no longer enough to move or back up an install.
  **M3's backup must therefore carry the master key, protected.** The proposal
  is to wrap it with a key derived (Argon2id) from the owner's recovery code,
  re-wrapped whenever the recovery code is replaced. Then the one thing the
  owner was told to keep safe also reopens a backup on a new computer.
  Until M3 ships, restoring onto a new computer means restoring the keychain
  as well.
- Keychain entries from throwaway installs (`OH_DATA_DIR`) stay behind in the
  developer's keychain after the folder is deleted. They're small and inert.
- Every process running as the owner can still ask the keychain for the key;
  macOS may prompt the first time. The keychain protects against file copies
  and other users, not against malware running as the owner. No local design
  does.
- New third-party code in the build: `keyring` and its small `jaraco.*`
  helpers (MIT), plus `pywin32-ctypes` on Windows (BSD-3-Clause), all listed
  in `NOTICE`. The PyInstaller spec collects `keyring`'s backends and
  metadata, because `keyring` finds its backends through entry points.

## Alternatives considered

- **Each secret as its own keychain entry.** It doesn't fit on Windows for the
  signing key (see above), and six entries can be half-updated.
- **Windows DPAPI directly, the Keychain directly on macOS.** No dependency,
  but two code paths to maintain, and `keyring` already wraps both.
- **Keep `keys.json`, and rely on owner-only file permissions.** Windows
  app-data isn't permissioned that way by default, and it's a config file.
  AI-1 rules it out.
- **Derive the master key from the owner's password.** The server couldn't
  start (the database needs its password) until someone signed in, and
  changing the password would mean re-sealing. Recovery still has to work
  without the password.

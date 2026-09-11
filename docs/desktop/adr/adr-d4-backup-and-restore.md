# ADR-D4: Backup is a stopped-cluster copy, unlocked by the recovery code

- **Status:** Proposed
- **Date:** 2026-09-11
- **Deciders:** desktop-edition owner *(to be named)*; drafted with Claude

## Context

PRD I-6 and G6: "Backup is configured during setup, not after: the owner names a
folder their existing cloud drive already syncs, and an encrypted copy is
written there nightly." The risks table calls losing the laptop with no backup
"severe — total data loss", and says to nag until it is configured.

Two facts make this concrete.

**The bundle has no dump tool.** `vendor/postgres/<tag>/bin` holds exactly
`initdb`, `pg_ctl` and `postgres` — the stripped zonky build
`scripts/desktop/fetch_postgres.py` fetches under a pinned SHA-256. There is no
`pg_dump`, `pg_restore` or `pg_basebackup`. Adding them means changing the
artifact and its pin.

**A copy of the folder is no longer enough.** Since ADR-D5 the six install
secrets are sealed under a master key that lives only in the OS keychain. A
backup that carries the database and not that key restores to an unopenable
database — and ADR-D5 says so explicitly, leaving the fix to this decision.

A live Postgres data directory must never be copied by a sync client
(`paths.py`'s opening note): half-written WAL is how the books get corrupted.

## Decision

**A backup is the database files, copied while the database is stopped, sealed
into one file in the owner's folder, and openable with the owner's recovery
code.**

- **When.** The launcher already has the one moment when the cluster is
  quiescent by construction: at start-up, before `PgCluster.start`. If a backup
  folder is configured and the last backup is older than 20 hours, the copy is
  taken there, then the app starts as usual. `oh-desktop --backup-now` forces
  one. This is "nightly" in the sense an owner experiences — a backup a day,
  taken on the first launch of the day — without stopping a running database or
  shipping replication tooling.
- **What goes in.** The cluster directory, `keys.sealed.json`, `state.json`, and
  a manifest naming the install id, the app version, both migration heads
  (upstream and desktop) and when it was taken. Not the owner's report folders:
  those are already in the owner's own folder, which is what a cloud drive
  syncs, and they would double the size of every backup.
- **How it is sealed.** One random 32-byte **backup key** per install, held in
  the OS keychain beside the master key (`backup-key:<install id>`). The archive
  is AES-256-GCM under it. **Every backup carries its own copy of that key,
  wrapped with a key derived from the owner's recovery code (Argon2id, the
  parameters `passwords.py` already uses).**
- **Why the recovery code and not a new passphrase.** It is the one secret the
  owner was already told to keep somewhere safe, and the screen that gives it
  says losing it loses the books. A second backup passphrase would be a second
  thing to lose, and the honest warning would have to be repeated for it.
  Wrapping per backup — rather than deriving the archive key from the code
  directly — means replacing the recovery code never orphans older backups:
  each file stays readable with the code that was current when it was written.
- **Restore.** `oh-desktop --restore <file>` on a machine with no books yet:
  the recovery code unwraps the backup key, the archive opens, the cluster
  directory and keys are put in place, and the normal start-up runs. It refuses
  to overwrite an existing install — a restore that silently replaced live books
  would be the one mistake nobody could undo. The keychain entries are rebuilt
  from what the archive carries, so a new computer needs the backup file and the
  recovery code and nothing else.
- **Migrations on restore.** Unchanged from PRD I-5: a restored database older
  than this build refuses to open until the owner starts it with
  `--upgrade-database`, which is what `NeedsUpgradeConsent` already does.

## Consequences

- A backup is self-contained: the file plus the recovery code reopens the books
  on another computer. That is the hole ADR-D5 left, closed.
- **A backup is only as fresh as the last launch.** An owner who never quits the
  app can go days without one. The Overview says when the last backup was taken
  and warns past two days; M4 can add a scheduled copy if that proves too thin.
- The backup is a file-level copy of a Postgres cluster, so it restores onto the
  same major version (16) only. The bundled version is pinned, and the manifest
  records it, so a mismatch is refused with a sentence rather than a corrupt
  start.
- Backups are opaque: the owner cannot open one in a spreadsheet. Their reports
  stay readable in the owner's folder, and a future "export my books" is a
  separate feature, not this one.
- An owner who loses both the recovery code and their computer has lost the
  books. That is the same promise the recovery-code screen already makes, and it
  is why the code screen and the backup folder are both in the setup flow.
- Size: the cluster is about 40 MB on a fresh install, so a daily file in a
  synced folder is modest — but it is a full copy each time, not an increment.
  Old backups are the owner's to delete; the app keeps the last 7 and says so.

## Alternatives considered

- **`pg_dump` to SQL.** The cleanest restore story (version-portable, readable),
  but the tool is not in the bundle and adding it means re-pinning the Postgres
  artifact and carrying more third-party attribution. Worth revisiting if a
  cross-version restore is ever needed.
- **A dump in-process over libpq** (psycopg is already a dependency). No new
  binaries, but it means writing and maintaining a correct dump of an
  RLS-heavy schema — exactly the kind of clever code the fork avoids.
- **`pg_backup_start()` / file copy / `pg_backup_stop()` on a running cluster.**
  Supported by Postgres and needs no extra tooling, but it is a replication-grade
  procedure whose failure mode is a backup that looks fine and cannot be
  restored. A stopped copy has no such mode.
- **Copy the folder and trust the cloud drive.** What owners do today, and what
  `paths.py` refuses: sync clients corrupt live clusters, and since ADR-D5 the
  copy would not open anyway.
- **A separate backup passphrase.** One more secret to lose, for no gain over
  the recovery code the owner already keeps.

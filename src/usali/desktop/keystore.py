"""Keys at rest (PRD A-4 and AI-1, ADR-D5).

Everything that unlocks an install — the database passwords, the field
encryption key, the HPKE key and the token-signing key — used to sit in
keys.json in plain text. It is now SEALED: AES-256-GCM under a 32-byte
master key, and the master key is kept in the OS keychain (Windows
Credential Manager, the macOS Keychain) and never written to disk. The
sealed file on its own opens nothing.

Why seal one file instead of putting each key in the keychain: Windows caps
a credential at 2,560 bytes and `keyring` stores text as UTF-16, so the
RSA-3072 signing key (a PEM of about 2.5 KB) cannot fit. One small key in
the keychain and one file it seals works on every platform, and the set of
keys stays atomic — written and read together, never half-updated.

The keychain entry is named per install (`master-key:<install id>`), so two
installs on one computer (OH_DATA_DIR) can never overwrite each other's key.

What this costs: lose the keychain entry (a reset user profile, a new
computer) and the books cannot be opened — the same as losing keys.json
was, but now copying the folder alone is not enough. M3's backup has to
carry the master key, protected; ADR-D5 records that.
"""

import base64
import json
import logging
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from usali.desktop.bootstrap import DesktopKeys, KeysMissing

_LOG = logging.getLogger(__name__)

SERVICE = "Open Hospitality"
_FORMAT = 1


class KeychainUnavailable(RuntimeError):
    """The OS keychain refused, or this computer has none we can use."""


class KeyStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


_NO_KEYCHAIN = (
    "Open Hospitality keeps the key to your books in this computer's password store "
    "(Credential Manager on Windows, Keychain on a Mac), and couldn't use it: {why}. "
    "Sign in to your computer normally (not as a guest or over a remote session) and "
    "start Open Hospitality again."
)


class OsKeyStore:
    """The OS keychain, through `keyring`."""

    def __init__(self, service: str = SERVICE) -> None:
        self._service = service

    def _backend(self) -> object:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            raise KeychainUnavailable(_NO_KEYCHAIN.format(why="none was found"))
        return backend

    def get(self, name: str) -> str | None:
        from keyring.errors import KeyringError

        try:
            value = self._backend().get_password(self._service, name)  # type: ignore[attr-defined]
        except KeyringError as exc:
            raise KeychainUnavailable(_NO_KEYCHAIN.format(why=exc)) from exc
        return value if isinstance(value, str) else None

    def set(self, name: str, value: str) -> None:
        from keyring.errors import KeyringError

        try:
            self._backend().set_password(self._service, name, value)  # type: ignore[attr-defined]
        except KeyringError as exc:
            raise KeychainUnavailable(_NO_KEYCHAIN.format(why=exc)) from exc

    def delete(self, name: str) -> None:
        from keyring.errors import KeyringError, PasswordDeleteError

        try:
            self._backend().delete_password(self._service, name)  # type: ignore[attr-defined]
        except PasswordDeleteError:
            pass  # already gone
        except KeyringError as exc:
            raise KeychainUnavailable(_NO_KEYCHAIN.format(why=exc)) from exc


class MemoryKeyStore:
    """A keychain that lives only as long as the process (tests)."""

    def __init__(self) -> None:
        self.entries: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.entries.get(name)

    def set(self, name: str, value: str) -> None:
        self.entries[name] = value

    def delete(self, name: str) -> None:
        self.entries.pop(name, None)


def entry_name(install_id: str) -> str:
    return f"master-key:{install_id}"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _seal(keys: DesktopKeys, master: bytes, install_id: str) -> dict[str, object]:
    nonce = os.urandom(12)
    plain = json.dumps(asdict(keys)).encode()
    # The install id is bound in as associated data: a sealed file cannot be
    # passed off under another install's keychain entry.
    sealed = AESGCM(master).encrypt(nonce, plain, install_id.encode())
    return {"format": _FORMAT, "install_id": install_id, "nonce": _b64(nonce),
            "sealed": _b64(sealed)}


def _unseal(doc: dict[str, object], master: bytes, path: Path) -> DesktopKeys:
    try:
        plain = AESGCM(master).decrypt(
            base64.b64decode(str(doc["nonce"])), base64.b64decode(str(doc["sealed"])),
            str(doc["install_id"]).encode(),
        )
    except (InvalidTag, KeyError, ValueError) as exc:
        raise KeysMissing(
            f"The file that holds the keys to your books ({path}) has been changed or damaged, "
            "so it can't be opened. Put it back from a copy, then start Open Hospitality again."
        ) from exc
    return DesktopKeys(**json.loads(plain))


def _write_owner_only(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _seal_new(keys: DesktopKeys, sealed: Path, store: KeyStore) -> None:
    """Put a new master key in the keychain, then write the sealed file —
    but only after the keychain has handed the key BACK and it opens the
    seal. A keychain can accept a write it later can't return; finding that
    out after the plain copy is gone would lock the owner out of their books."""
    install_id = uuid.uuid4().hex
    master = os.urandom(32)
    store.set(entry_name(install_id), _b64(master))
    doc = _seal(keys, master, install_id)
    kept = store.get(entry_name(install_id))
    if kept is None or _unseal(doc, base64.b64decode(kept), sealed) != keys:
        store.delete(entry_name(install_id))
        raise KeychainUnavailable(
            _NO_KEYCHAIN.format(why="it accepted the key but didn't give it back")
        )
    _write_owner_only(sealed, json.dumps(doc, indent=2))


def _retire_plain_copy(legacy: Path, keys: DesktopKeys) -> None:
    """Delete the old plain-text keys.json — only if it holds exactly the
    keys the sealed file does. Anything else is left for a person to look at."""
    if not legacy.is_file():
        return
    try:
        old = DesktopKeys(**json.loads(legacy.read_text(encoding="utf-8")))
    except (ValueError, TypeError):
        _LOG.warning("left %s in place: it isn't a key file this version understands", legacy)
        return
    if old != keys:
        _LOG.warning("left %s in place: it doesn't match the sealed keys", legacy)
        return
    legacy.unlink()
    _LOG.info("keys are sealed; removed the plain-text copy %s", legacy)


def open_keys(
    *, sealed: Path, legacy: Path, store: KeyStore, database_exists: bool,
) -> DesktopKeys:
    """The install's keys, sealed at rest. Handles, in order: a sealed
    install; an M1 install still holding plain keys.json (sealed, then the
    plain copy removed); a lost key file; and a first run."""
    if sealed.is_file():
        doc = json.loads(sealed.read_text(encoding="utf-8"))
        install_id = str(doc.get("install_id", ""))
        master = store.get(entry_name(install_id))
        if master is None:
            raise KeysMissing(
                "This computer's password store no longer holds the key that unlocks your "
                f"books (\"{SERVICE}\", {entry_name(install_id)}), so they can't be opened. "
                "This happens after a user account is reset or the books are copied to "
                "another computer. Restore the password store, or the books from a backup."
            )
        keys = _unseal(doc, base64.b64decode(master), sealed)
        # A launch that died between sealing and deleting finishes the job.
        _retire_plain_copy(legacy, keys)
        return keys

    if legacy.is_file():
        keys = DesktopKeys(**json.loads(legacy.read_text(encoding="utf-8")))
        try:
            _seal_new(keys, sealed, store)
        except KeychainUnavailable as exc:
            # Never lock an existing install out over this: run from the
            # plain copy exactly as before, and try again next launch.
            _LOG.warning("keys stay in %s for now: %s", legacy, exc)
            return keys
        _retire_plain_copy(legacy, keys)
        return keys

    if database_exists:
        # Generating fresh keys here would lock the owner out of their own
        # books AND make every encrypted field unreadable. Stop and say so.
        raise KeysMissing(
            f"The file that holds the keys to your books is missing ({sealed}). Without it "
            "the database cannot be opened. Put it back in that folder from your backup, "
            "then start Open Hospitality again."
        )

    # A first run refuses rather than write secrets in plain text: a
    # KeychainUnavailable here propagates to the launcher's message.
    keys = DesktopKeys.generate()
    _seal_new(keys, sealed, store)
    return keys

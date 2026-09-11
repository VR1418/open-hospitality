"""Keys at rest (PRD A-4, ADR-D5): sealed under a master key in the OS
keychain, never in plain text. No database needed.

Most tests use MemoryKeyStore; the last one goes through this computer's
real keychain and is skipped where there isn't one.
"""

import json
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from usali.desktop.bootstrap import DesktopKeys, KeysMissing
from usali.desktop.keystore import (
    KeychainUnavailable,
    MemoryKeyStore,
    OsKeyStore,
    entry_name,
    open_keys,
)


@pytest.fixture(scope="module")
def some_keys() -> DesktopKeys:
    return DesktopKeys.generate()  # RSA generation is slow: once per module


def _open(root: Path, store: object, *, database_exists: bool = False) -> DesktopKeys:
    return open_keys(
        sealed=root / "keys.sealed.json", legacy=root / "keys.json",
        store=store, database_exists=database_exists,  # type: ignore[arg-type]
    )


def _plain_copy(root: Path, keys: DesktopKeys) -> Path:
    path = root / "keys.json"
    path.write_text(json.dumps(asdict(keys)), encoding="utf-8")
    return path


class RefusingStore(MemoryKeyStore):
    def set(self, name: str, value: str) -> None:
        raise KeychainUnavailable("refused")


class ForgetfulStore(MemoryKeyStore):
    """Accepts a write and can't give it back (it happens)."""

    def get(self, name: str) -> str | None:
        return None


def test_a_first_run_seals_its_keys_and_writes_no_secret_to_disk(tmp_path: Path) -> None:
    store = MemoryKeyStore()
    keys = _open(tmp_path, store)

    sealed = (tmp_path / "keys.sealed.json").read_text(encoding="utf-8")
    for secret in asdict(keys).values():
        assert secret not in sealed
    assert not (tmp_path / "keys.json").exists()
    [(name, master)] = store.entries.items()
    assert name == entry_name(json.loads(sealed)["install_id"])
    assert master not in sealed
    # The next launch opens the same keys.
    assert _open(tmp_path, store, database_exists=True) == keys


def test_the_sealed_file_alone_opens_nothing(tmp_path: Path) -> None:
    _open(tmp_path, MemoryKeyStore())
    with pytest.raises(KeysMissing, match="password store no longer holds"):
        _open(tmp_path, MemoryKeyStore(), database_exists=True)


def test_a_changed_file_is_refused_not_misread(tmp_path: Path) -> None:
    store = MemoryKeyStore()
    _open(tmp_path, store)
    path = tmp_path / "keys.sealed.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    sealed = bytearray(doc["sealed"].encode())
    sealed[10] = ord("A") if sealed[10] != ord("A") else ord("B")
    doc["sealed"] = sealed.decode()
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(KeysMissing, match="changed or damaged"):
        _open(tmp_path, store, database_exists=True)


def test_an_m1_install_is_sealed_and_its_plain_copy_removed(
    tmp_path: Path, some_keys: DesktopKeys,
) -> None:
    store = MemoryKeyStore()
    plain = _plain_copy(tmp_path, some_keys)
    assert _open(tmp_path, store, database_exists=True) == some_keys
    assert not plain.exists()
    assert (tmp_path / "keys.sealed.json").is_file()
    assert _open(tmp_path, store, database_exists=True) == some_keys


def test_a_keychain_that_refuses_never_locks_an_existing_install_out(
    tmp_path: Path, some_keys: DesktopKeys,
) -> None:
    for store in (RefusingStore(), ForgetfulStore()):
        plain = _plain_copy(tmp_path, some_keys)
        assert _open(tmp_path, store, database_exists=True) == some_keys
        # Still running from the plain copy, and nothing sealed that the
        # next launch would trust over it.
        assert plain.exists()
        assert not (tmp_path / "keys.sealed.json").exists()


def test_a_first_run_without_a_keychain_refuses_to_write_secrets_in_plain_text(
    tmp_path: Path,
) -> None:
    with pytest.raises(KeychainUnavailable):
        _open(tmp_path, RefusingStore())
    assert list(tmp_path.iterdir()) == []


def test_an_interrupted_move_is_finished_but_a_stranger_file_is_left_alone(
    tmp_path: Path, some_keys: DesktopKeys,
) -> None:
    store = MemoryKeyStore()
    keys = _open(tmp_path, store)
    # The launch sealed its keys and died before deleting the plain copy.
    plain = _plain_copy(tmp_path, keys)
    _open(tmp_path, store, database_exists=True)
    assert not plain.exists()
    # A keys.json holding something ELSE is a person's to look at.
    stranger = _plain_copy(tmp_path, some_keys)
    _open(tmp_path, store, database_exists=True)
    assert stranger.exists()


def test_missing_keys_for_an_existing_database_refuse_loudly(tmp_path: Path) -> None:
    store = MemoryKeyStore()
    with pytest.raises(KeysMissing, match="missing"):
        _open(tmp_path, store, database_exists=True)
    # Fresh keys would lock the owner out of their own books: none are made.
    assert store.entries == {} and list(tmp_path.iterdir()) == []


def test_two_installs_on_one_computer_keep_their_own_keys(tmp_path: Path) -> None:
    store = MemoryKeyStore()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _open(tmp_path / "a", store)
    b = _open(tmp_path / "b", store)
    assert a != b and len(store.entries) == 2
    assert _open(tmp_path / "a", store, database_exists=True) == a
    assert _open(tmp_path / "b", store, database_exists=True) == b


def test_this_computers_keychain_round_trip() -> None:
    store = OsKeyStore(service="Open Hospitality (tests)")
    name = f"probe:{uuid.uuid4().hex}"
    try:
        store.set(name, "a-master-key")
    except KeychainUnavailable as exc:
        pytest.skip(f"no usable keychain here: {exc}")
    try:
        assert store.get(name) == "a-master-key"
    finally:
        store.delete(name)
    assert store.get(name) is None
    store.delete(name)  # deleting twice is not an error

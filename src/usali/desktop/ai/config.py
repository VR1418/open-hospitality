"""What the owner chose, and where their key lives (PRD AI-1, ADR-D7).

The settings — provider, model, address, limits, prices — are ordinary install
settings and sit in `desktop.setting` beside the module choice.

The key does not. It goes in the OS keychain under its own entry,
`ai-key:<install id>`, and deliberately NOT inside `keys.sealed.json` with the
install's own six secrets: that bundle is wrapped into every backup (ADR-D4),
and the backup folder is one the owner's cloud drive syncs. A provider key
should not leave this machine in a file. Restoring onto a new computer asks
for it again.

It is never written to the database, never to a config file, never to a log,
and never into an exception message.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from usali.desktop.ai.spend import DEFAULT_CAP, DEFAULT_MAX_CALLS, Prices
from usali.desktop.keystore import KeyStore, install_id
from usali.desktop.settings import read_setting, write_setting

SETTING_KEY = "ai"

#: The three shapes a call can take. "mock" is the offline stand-in — useful
#: for trying the screens without a provider, and never a paid call.
PROVIDERS = ("openai_compatible", "anthropic", "mock")

#: What an owner reads, for each. The PRD's vocabulary rules apply: no
#: "API key" anywhere the owner can see (Appendix A).
PROVIDER_NAMES = {
    "openai_compatible": "OpenRouter, OpenAI, Ollama, or any compatible service",
    "anthropic": "Anthropic",
    "mock": "Practice mode (answers offline, costs nothing)",
}


def key_entry(iid: str) -> str:
    return f"ai-key:{iid}"


@dataclass(frozen=True)
class AiSettings:
    """`provider is None` means the owner has not set this up. Everything
    else has a working default so a half-filled form cannot produce an
    uncapped install."""

    provider: str | None = None
    model: str = ""
    base_url: str | None = None
    cap: Decimal = DEFAULT_CAP
    max_calls: int = DEFAULT_MAX_CALLS
    prices: Prices = Prices()

    @property
    def ready(self) -> bool:
        return self.provider is not None and bool(self.model)


def _decimal(value: object, fallback: Decimal | None) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return fallback


def is_local(base_url: str | None) -> bool:
    """A model served from this machine costs nothing, and that is the one
    price we can assert without being told."""
    if not base_url:
        return False
    lowered = base_url.lower()
    return any(host in lowered for host in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0"))


def read(session: Session) -> AiSettings:
    """The stored choice. A corrupt or half-written row reads as "not set up"
    rather than raising — the `read_modules` pattern."""
    raw = read_setting(session, SETTING_KEY)
    if not isinstance(raw, dict):
        return AiSettings()
    provider = raw.get("provider")
    if provider not in PROVIDERS:
        provider = None
    base_url = raw.get("base_url")
    base_url = str(base_url) if base_url else None
    cap = _decimal(raw.get("cap"), DEFAULT_CAP) or DEFAULT_CAP
    try:
        max_calls = int(raw.get("max_calls", DEFAULT_MAX_CALLS))
    except (TypeError, ValueError):
        max_calls = DEFAULT_MAX_CALLS
    return AiSettings(
        provider=provider,
        model=str(raw.get("model", "")),
        base_url=base_url,
        cap=cap,
        max_calls=max(1, max_calls),
        prices=Prices(
            per_million_input=_decimal(raw.get("price_in"), None),
            per_million_output=_decimal(raw.get("price_out"), None),
            local=is_local(base_url),
        ),
    )


def write(session: Session, settings: AiSettings) -> None:
    """Store the choice. Does not commit — the caller owns the transaction."""
    body: dict[str, Any] = {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "cap": str(settings.cap),
        "max_calls": settings.max_calls,
        "price_in": (
            str(settings.prices.per_million_input)
            if settings.prices.per_million_input is not None
            else None
        ),
        "price_out": (
            str(settings.prices.per_million_output)
            if settings.prices.per_million_output is not None
            else None
        ),
    }
    write_setting(session, SETTING_KEY, body)


def read_key(store: KeyStore, sealed: Path) -> str | None:
    iid = install_id(sealed)
    return None if iid is None else store.get(key_entry(iid))


def write_key(store: KeyStore, sealed: Path, key: str) -> None:
    """Keep the key, and prove it can be read back before saying so — the
    `keystore._seal_new` rule: a store that silently accepts and forgets
    would leave the owner thinking they were set up."""
    iid = install_id(sealed)
    if iid is None:
        raise RuntimeError("this install has no id yet, so there is nowhere to keep the key")
    store.set(key_entry(iid), key)
    if store.get(key_entry(iid)) != key:
        store.delete(key_entry(iid))
        raise RuntimeError(
            "this computer's password store accepted the key but did not keep it"
        )


def clear_key(store: KeyStore, sealed: Path) -> None:
    iid = install_id(sealed)
    if iid is not None:
        store.delete(key_entry(iid))

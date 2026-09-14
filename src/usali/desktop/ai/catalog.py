"""Which service, and which model — without the owner typing either (ADR-D7).

An owner with an OpenRouter key was left with two blank boxes: "which model,
exactly as they write it" and a web address. Nobody outside the industry
knows that Claude on OpenRouter is `anthropic/claude-sonnet-5`, or that the
address is `https://openrouter.ai/api/v1`. So the choice is a SERVICE the
owner recognises, and the model is picked from a list.

The list for OpenRouter (and the prices for Anthropic and OpenAI, which charge
the same through it) comes from OpenRouter's PUBLIC model catalogue — a GET
that carries no key and nothing about the hotel. It changes every few weeks,
which is why it is fetched, not written here. When it cannot be reached the
owner gets a short built-in list with no prices, and the spend limit falls back
to counting questions, as it already does for an unpriced model.

Nothing in this module talks to the owner's provider or sends a report.
"""

import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from usali.desktop.ai import config

CATALOG_URL = "https://openrouter.ai/api/v1/models"
_TIMEOUT = 10.0
_CACHE_SECONDS = 3600

#: Makers whose models are offered. Others are reachable by typing a name.
MAKERS = {"anthropic": "Anthropic (Claude)", "openai": "OpenAI (GPT)", "google": "Google (Gemini)"}

#: Variants that are the same model sold differently, or models for another
#: job (images, code, audio) — listing them would be noise for this one.
_SKIP = (":", "image", "preview", "customtools", "codex", "audio", "realtime", "search",
         "-pro", "deep-research", "embedding")

#: How many of each maker's model families to show (newest model of each).
PER_MAKER = 6

_VERSION = re.compile(r"[-.]?\d+(?:[.-]\d+)*")


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    #: The adapter kind (`config.PROVIDERS`).
    provider: str
    #: Fixed for hosted services; a suggestion for "local"; None for "custom".
    base_url: str | None
    #: Whether the owner may change the address.
    address_editable: bool
    needs_key: bool
    #: Where the key comes from, in the owner's words.
    key_hint: str
    lists_models: bool


SERVICES: tuple[Service, ...] = (
    Service("openrouter", "OpenRouter — one account for Claude, GPT, Gemini and more",
            "openai_compatible", "https://openrouter.ai/api/v1", False, True,
            "On openrouter.ai, open Keys and create one. It starts with sk-or-.", True),
    Service("anthropic", "Anthropic (Claude) — directly", "anthropic", None, False, True,
            "On console.anthropic.com, open API keys and create one. It starts with sk-ant-.",
            True),
    Service("openai", "OpenAI (ChatGPT's maker) — directly", "openai_compatible",
            "https://api.openai.com/v1", False, True,
            "On platform.openai.com, open API keys and create one. It starts with sk-.", True),
    Service("local", "A model on this computer (Ollama or LM Studio)", "openai_compatible",
            "http://localhost:11434/v1", True, False,
            "No key needed — nothing leaves this computer.", False),
    Service("custom", "Another compatible service", "openai_compatible", None, True, True,
            "The key that service gave you.", False),
    Service("mock", "Practice mode — answers offline, costs nothing", "mock", None, False,
            False, "No key needed.", False),
)

_BY_ID = {s.id: s for s in SERVICES}


def service(service_id: str) -> Service | None:
    return _BY_ID.get(service_id)


def infer_service(settings: config.AiSettings) -> str | None:
    """Which service a saved choice is. Stored settings predate services, and
    a service is fully described by its adapter and address, so it is worked
    out rather than stored twice."""
    if settings.provider is None:
        return None
    if settings.provider in ("anthropic", "mock"):
        return settings.provider
    url = (settings.base_url or "").lower()
    if "openrouter.ai" in url:
        return "openrouter"
    if "api.openai.com" in url:
        return "openai"
    if config.is_local(settings.base_url):
        return "local"
    return "custom"


@dataclass(frozen=True)
class ModelChoice:
    #: Exactly what the service is asked for.
    id: str
    name: str
    maker: str
    #: Dollars per million tokens, or None when not known.
    price_in: Decimal | None
    price_out: Decimal | None


@dataclass(frozen=True)
class Catalog:
    models: tuple[ModelChoice, ...]
    #: False when the public list could not be reached and this is the
    #: built-in fallback — the screen says so.
    live: bool
    recommended: str | None


#: Used only when the public list cannot be reached. No prices: a stale
#: price is worse than none, because the limit would trust it.
_FALLBACK = {
    "openrouter": ("anthropic/claude-sonnet-5", "anthropic/claude-haiku-4.5",
                   "anthropic/claude-opus-5", "openai/gpt-5.4-mini", "google/gemini-2.5-flash"),
    "anthropic": ("claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"),
    "openai": ("gpt-5.4-mini", "gpt-5.4"),
}

#: A good balance of reading skill and cost for classifying codes and reading
#: report pages; first one present wins.
_RECOMMENDED = ("anthropic/claude-sonnet-5", "anthropic/claude-sonnet-4.6",
                "anthropic/claude-haiku-4.5")

_cache: tuple[float, list[dict[str, object]]] | None = None


def _per_million(value: object) -> Decimal | None:
    try:
        per_token = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return None if per_token < 0 else (per_token * 1_000_000).quantize(Decimal("0.01"))


def _fetch(client: httpx.Client | None) -> list[dict[str, object]] | None:
    global _cache
    if client is None and _cache is not None and time.monotonic() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        http = client or httpx.Client(timeout=_TIMEOUT)
        response = http.get(CATALOG_URL)
        response.raise_for_status()
        data = response.json().get("data")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    if not isinstance(data, list):
        return None
    rows = [m for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]
    if client is None:
        _cache = (time.monotonic(), rows)
    return rows


def _openrouter_models(rows: list[dict[str, object]]) -> list[ModelChoice]:
    by_maker: dict[str, list[tuple[int, ModelChoice]]] = {m: [] for m in MAKERS}
    for row in rows:
        model_id = str(row["id"])
        maker, _, rest = model_id.partition("/")
        if maker not in MAKERS or not rest or any(s in rest for s in _SKIP):
            continue
        raw_pricing = row.get("pricing")
        pricing: dict[str, object] = raw_pricing if isinstance(raw_pricing, dict) else {}
        name = str(row.get("name") or rest)
        if ": " in name:
            name = name.split(": ", 1)[1]
        created = row.get("created")
        by_maker[maker].append((
            created if isinstance(created, int) else 0,
            ModelChoice(
                id=model_id, name=name, maker=MAKERS[maker],
                price_in=_per_million(pricing.get("prompt")),
                price_out=_per_million(pricing.get("completion")),
            ),
        ))
    out: list[ModelChoice] = []
    for maker in MAKERS:
        # The newest model of each FAMILY, then the newest families: otherwise
        # five Opus and Fable releases push the cheap Haiku off the list.
        seen: set[str] = set()
        families: list[ModelChoice] = []
        for _, choice in sorted(by_maker[maker], key=lambda pair: pair[0], reverse=True):
            family = _VERSION.sub("", choice.id.partition("/")[2])
            if family not in seen:
                seen.add(family)
                families.append(choice)
        out.extend(families[:PER_MAKER])
    return out


def _direct_id(service_id: str, openrouter_id: str) -> str | None:
    """OpenRouter's name for a model, as its maker's own service spells it:
    `anthropic/claude-haiku-4.5` is `claude-haiku-4-5` at Anthropic."""
    maker, _, rest = openrouter_id.partition("/")
    if service_id == "anthropic" and maker == "anthropic":
        return rest.replace(".", "-")
    if service_id == "openai" and maker == "openai":
        return rest
    return None


def models(service_id: str, client: httpx.Client | None = None) -> Catalog:
    """The models to offer for a service, newest first within each maker."""
    if service_id not in _FALLBACK:
        return Catalog(models=(), live=False, recommended=None)
    rows = _fetch(client)
    if rows is None:
        fallback = tuple(
            ModelChoice(id=m, name=m.split("/")[-1], maker="", price_in=None, price_out=None)
            for m in _FALLBACK[service_id]
        )
        return Catalog(models=fallback, live=False, recommended=fallback[0].id)

    listed = _openrouter_models(rows)
    if service_id != "openrouter":
        listed = [
            ModelChoice(id=direct, name=m.name, maker=m.maker,
                        price_in=m.price_in, price_out=m.price_out)
            for m in listed
            if (direct := _direct_id(service_id, m.id)) is not None
        ]
    ids = [m.id for m in listed]
    wanted = [_direct_id(service_id, r) or r for r in _RECOMMENDED]
    recommended = next((r for r in wanted if r in ids), None)
    return Catalog(models=tuple(listed), live=True, recommended=recommended)

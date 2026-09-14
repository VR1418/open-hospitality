"""Choosing a service and a model from a list (ADR-D7).

Reported: an owner with an OpenRouter key could not work out how to choose
Claude — the screen asked for a model "exactly as they write it" and a web
address. Offline: an `httpx.MockTransport` stands in for OpenRouter's public
model catalogue.
"""

from decimal import Decimal

import httpx

from usali.desktop.ai import catalog, config

LISTING = {"data": [
    {"id": "anthropic/claude-sonnet-5", "name": "Anthropic: Claude Sonnet 5", "created": 50,
     "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
    {"id": "anthropic/claude-sonnet-5:batch", "name": "Anthropic: Claude Sonnet 5 (batch)",
     "created": 50, "pricing": {"prompt": "0.000001", "completion": "0.000005"}},
    {"id": "anthropic/claude-sonnet-4.6", "name": "Anthropic: Claude Sonnet 4.6", "created": 40,
     "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
    {"id": "anthropic/claude-haiku-4.5", "name": "Anthropic: Claude Haiku 4.5", "created": 10,
     "pricing": {"prompt": "0.000001", "completion": "0.000005"}},
    {"id": "openai/gpt-5.4-image-2", "name": "OpenAI: GPT-5.4 Image 2", "created": 60,
     "pricing": {"prompt": "0.000008", "completion": "0.000015"}},
    {"id": "meta/llama-9", "name": "Meta: Llama 9", "created": 70, "pricing": {}},
]}


def _client(body: object = LISTING, status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def test_openrouter_offers_claude_by_name_with_its_price() -> None:
    http, seen = _client()
    got = catalog.models("openrouter", client=http)
    assert got.live
    by_id = {m.id: m for m in got.models}
    sonnet = by_id["anthropic/claude-sonnet-5"]
    assert sonnet.name == "Claude Sonnet 5" and sonnet.maker == "Anthropic (Claude)"
    assert (sonnet.price_in, sonnet.price_out) == (Decimal("2.00"), Decimal("10.00"))
    assert got.recommended == "anthropic/claude-sonnet-5"
    # The catalogue request carries no key and nothing about the hotel.
    [request] = seen
    assert str(request.url) == catalog.CATALOG_URL and request.method == "GET"
    assert "authorization" not in request.headers


def test_the_list_is_one_model_per_family_and_nothing_for_another_job() -> None:
    http, _ = _client()
    ids = [m.id for m in catalog.models("openrouter", client=http).models]
    # Batch pricing is the same model; the older Sonnet is superseded; image
    # models are for another job; makers not offered are reachable by typing.
    assert ids == ["anthropic/claude-sonnet-5", "anthropic/claude-haiku-4.5"]


def test_anthropic_directly_uses_its_own_spelling_of_the_same_models() -> None:
    http, _ = _client()
    got = catalog.models("anthropic", client=http)
    assert [m.id for m in got.models] == ["claude-sonnet-5", "claude-haiku-4-5"]
    assert got.recommended == "claude-sonnet-5"


def test_without_the_catalogue_there_is_a_short_list_and_no_invented_prices() -> None:
    http, _ = _client(status=503)
    got = catalog.models("openrouter", client=http)
    assert not got.live and got.models
    assert all(m.price_in is None and m.price_out is None for m in got.models)


def test_a_saved_choice_is_recognised_as_its_service() -> None:
    def svc(provider: str | None, url: str | None = None) -> str | None:
        return catalog.infer_service(config.AiSettings(provider=provider, model="m", base_url=url))

    assert svc(None) is None
    assert svc("anthropic") == "anthropic" and svc("mock") == "mock"
    assert svc("openai_compatible", "https://openrouter.ai/api/v1") == "openrouter"
    assert svc("openai_compatible", "https://api.openai.com/v1") == "openai"
    assert svc("openai_compatible", "http://localhost:11434/v1") == "local"
    assert svc("openai_compatible", "https://llm.example.com/v1") == "custom"
    # Every hosted service's address is recognised as itself.
    for s in catalog.SERVICES:
        if s.base_url and not s.address_editable:
            assert svc(s.provider, s.base_url) == s.id

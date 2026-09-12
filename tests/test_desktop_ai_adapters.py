"""The two adapters, and what they refuse (ADR-D7, ADR-009).

Offline: an `httpx.MockTransport` stands in for the network, so no test needs
a key or a provider. The point of having two adapters is that their shapes
genuinely differ — a bearer token and `choices[0].message.content` on one side,
`x-api-key` with a dated version header and a content LIST on the other — so
both shapes are exercised here rather than assumed.
"""

import json

import httpx
import pytest

from usali.desktop.ai.anthropic import VERSION, AnthropicAdapter
from usali.desktop.ai.mock import MockAdapter
from usali.desktop.ai.openai_compatible import OpenAiCompatibleAdapter
from usali.desktop.ai.port import AiError, Provider

KEY = "sk-never-log-me-123"
ANSWER = {"choice": 1, "confidence": "high", "reason": "It is a rooms extra.",
          "decline_reason": None}


def _openai_client(body: object, status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def _openai_reply(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def _anthropic_reply(text: str) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 120, "output_tokens": 30},
    }


PROVIDER = Provider(kind="openai_compatible", model="some-model", base_url="https://host/v1")
CLAUDE = Provider(kind="anthropic", model="claude-test")


def test_an_openai_shaped_call_goes_where_it_was_told_with_a_bearer_token() -> None:
    client, seen = _openai_client(_openai_reply(json.dumps(ANSWER)))
    answer = OpenAiCompatibleAdapter(client).ask(
        provider=PROVIDER, key=KEY, prompt="where does CBN go?", choices=3
    )
    [request] = seen
    assert str(request.url) == "https://host/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "some-model" and body["temperature"] == 0
    assert body["messages"][0]["content"] == "where does CBN go?"
    assert (answer.choice, answer.confidence) == (1, "high")
    assert (answer.usage.prompt_tokens, answer.usage.completion_tokens) == (120, 30)


def test_a_local_model_is_just_a_different_address() -> None:
    """Ollama and LM Studio are the same adapter — which is the whole reason
    there are two adapters and not five."""
    client, seen = _openai_client(_openai_reply(json.dumps(ANSWER)))
    local = Provider(kind="openai_compatible", model="llama", base_url="http://localhost:11434/v1")
    OpenAiCompatibleAdapter(client).ask(provider=local, key="", prompt="q", choices=3)
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"


def test_an_openai_shaped_helper_without_an_address_is_refused() -> None:
    bare = Provider(kind="openai_compatible", model="x", base_url=None)
    with pytest.raises(AiError, match="web address"):
        OpenAiCompatibleAdapter().ask(provider=bare, key=KEY, prompt="q", choices=1)


def test_anthropics_own_shape_is_a_different_shape() -> None:
    client, seen = _openai_client(_anthropic_reply(json.dumps(ANSWER)))
    answer = AnthropicAdapter(client).ask(
        provider=CLAUDE, key=KEY, prompt="where does CBN go?", choices=3
    )
    [request] = seen
    assert str(request.url).endswith("/messages")
    # A key header, not a bearer token; a dated version; a top-level max_tokens.
    assert request.headers["x-api-key"] == KEY
    assert "authorization" not in request.headers
    assert request.headers["anthropic-version"] == VERSION
    assert json.loads(request.content)["max_tokens"] > 0
    assert answer.choice == 1
    # input/output tokens, not prompt/completion.
    assert (answer.usage.prompt_tokens, answer.usage.completion_tokens) == (120, 30)


def test_anthropic_joins_the_text_it_sent_back() -> None:
    body = {
        "content": [
            {"type": "text", "text": '{"choice": 0, "confidence"'},
            {"type": "text", "text": ': "low", "reason": "ok"}'},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client, _ = _openai_client(body)
    assert AnthropicAdapter(client).ask(
        provider=CLAUDE, key=KEY, prompt="q", choices=2
    ).choice == 0


def test_a_reply_wrapped_in_a_fence_still_reads() -> None:
    """Models are asked for JSON and nothing else, and mostly comply. A
    ```json fence is the common near-miss and is not worth failing a paid
    call over."""
    fenced = "Here you go:\n```json\n" + json.dumps(ANSWER) + "\n```"
    client, _ = _openai_client(_openai_reply(fenced))
    assert OpenAiCompatibleAdapter(client).ask(
        provider=PROVIDER, key=KEY, prompt="q", choices=3
    ).choice == 1


def test_a_line_that_was_not_offered_is_refused_not_clamped() -> None:
    """The model naming a line that was not on the menu means it did not do
    the task. Quietly filing the charge somewhere is the exact failure this
    feature exists to prevent."""
    client, _ = _openai_client(_openai_reply(json.dumps({**ANSWER, "choice": 99})))
    with pytest.raises(AiError, match="not one of the 3"):
        OpenAiCompatibleAdapter(client).ask(
            provider=PROVIDER, key=KEY, prompt="q", choices=3
        )


def test_an_answer_that_is_not_json_is_refused() -> None:
    client, _ = _openai_client(_openai_reply("I think it's probably rooms revenue?"))
    with pytest.raises(AiError, match="JSON"):
        OpenAiCompatibleAdapter(client).ask(
            provider=PROVIDER, key=KEY, prompt="q", choices=3
        )


def test_declining_without_a_reason_is_not_an_answer() -> None:
    """AI-7 asks the model to refuse on tax and capitalisation — and to say
    why. A bare refusal tells the owner nothing, so it is not accepted."""
    client, _ = _openai_client(
        _openai_reply(json.dumps({"choice": None, "confidence": "low", "reason": ""}))
    )
    with pytest.raises(AiError, match="declined without saying why"):
        OpenAiCompatibleAdapter(client).ask(
            provider=PROVIDER, key=KEY, prompt="q", choices=3
        )


@pytest.mark.parametrize(
    ("status", "says"),
    [(401, "refused the key"), (403, "refused the key"), (429, "rate-limiting"),
     (500, "error")],
)
def test_a_refusal_says_what_to_do_and_never_echoes_the_key(status: int, says: str) -> None:
    client, _ = _openai_client({"error": KEY}, status=status)
    with pytest.raises(AiError) as raised:
        OpenAiCompatibleAdapter(client).ask(
            provider=PROVIDER, key=KEY, prompt="q", choices=3
        )
    assert says in str(raised.value)
    # AI-1: never the key, and never the payload, in anything that reaches a log.
    assert KEY not in str(raised.value)


def test_an_unreachable_provider_says_so_without_naming_the_address() -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    with pytest.raises(AiError) as raised:
        OpenAiCompatibleAdapter(client).ask(
            provider=PROVIDER, key=KEY, prompt="q", choices=3
        )
    assert "could not reach" in str(raised.value)
    # An httpx error carries the full URL, and some gateways put the key in
    # one — so the message is ours, not the library's.
    assert "host/v1" not in str(raised.value) and KEY not in str(raised.value)


def test_the_practice_provider_answers_offline_and_can_decline() -> None:
    mock = MockAdapter()
    prompt = "Printed on the report as: Cabana Rental\n"
    assert mock.ask(provider=PROVIDER, key="", prompt=prompt, choices=2).choice == 0
    taxed = "Printed on the report as: Occupancy tax collected\n"
    declined = mock.ask(provider=PROVIDER, key="", prompt=taxed, choices=2)
    assert declined.choice is None and "tax" in (declined.decline_reason or "")

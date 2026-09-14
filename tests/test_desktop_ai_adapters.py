"""The two adapters, and what the product makes of what they return (ADR-D7).

Offline: an `httpx.MockTransport` stands in for the network, so no test needs
a key or a provider.

The split these tests follow is the port's: an adapter does the HTTP and the
envelope and nothing else, so its tests are about the REQUEST it sends and the
text it hands back. What the words mean is `reply.parse` (where does this code
belong) or `report.parse` (what rows are on this page), and those are tested
apart from any transport — which is the point of separating them.
"""

import json

import httpx
import pytest

from usali.desktop.ai import reply
from usali.desktop.ai.anthropic import VERSION, AnthropicAdapter
from usali.desktop.ai.mock import MockAdapter
from usali.desktop.ai.openai_compatible import OpenAiCompatibleAdapter
from usali.desktop.ai.port import AiError, Provider, Usage

KEY = "sk-never-log-me-123"
ANSWER = {"choice": 1, "confidence": "high", "reason": "It is a rooms extra.",
          "decline_reason": None}
USED = Usage(prompt_tokens=120, completion_tokens=30)


def _client(body: object, status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
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


# --- transport: what goes out, and what comes back ---------------------------

def test_an_openai_shaped_call_goes_where_it_was_told_with_a_bearer_token() -> None:
    client, seen = _client(_openai_reply(json.dumps(ANSWER)))
    got = OpenAiCompatibleAdapter(client).ask(
        provider=PROVIDER, key=KEY, prompt="where does CBN go?"
    )
    [request] = seen
    assert str(request.url) == "https://host/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "some-model" and body["temperature"] == 0
    assert body["messages"][0]["content"] == "where does CBN go?"
    assert json.loads(got.text)["choice"] == 1
    assert (got.usage.prompt_tokens, got.usage.completion_tokens) == (120, 30)


def test_a_local_model_is_just_a_different_address() -> None:
    """Ollama and LM Studio are the same adapter — which is the whole reason
    there are two adapters and not five."""
    client, seen = _client(_openai_reply(json.dumps(ANSWER)))
    local = Provider(kind="openai_compatible", model="llama", base_url="http://localhost:11434/v1")
    OpenAiCompatibleAdapter(client).ask(provider=local, key="", prompt="q")
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"


def test_an_openai_shaped_helper_without_an_address_is_refused() -> None:
    bare = Provider(kind="openai_compatible", model="x", base_url=None)
    with pytest.raises(AiError, match="web address"):
        OpenAiCompatibleAdapter().ask(provider=bare, key=KEY, prompt="q")


def test_anthropics_own_shape_is_a_different_shape() -> None:
    client, seen = _client(_anthropic_reply(json.dumps(ANSWER)))
    got = AnthropicAdapter(client).ask(provider=CLAUDE, key=KEY, prompt="where does CBN go?")
    [request] = seen
    assert str(request.url).endswith("/messages")
    # A key header, not a bearer token; a dated version; a top-level max_tokens.
    assert request.headers["x-api-key"] == KEY
    assert "authorization" not in request.headers
    assert request.headers["anthropic-version"] == VERSION
    assert json.loads(request.content)["max_tokens"] > 0
    assert json.loads(got.text)["choice"] == 1
    # input/output tokens, not prompt/completion.
    assert (got.usage.prompt_tokens, got.usage.completion_tokens) == (120, 30)


def test_anthropic_joins_the_text_it_sent_back() -> None:
    body = {
        "content": [
            {"type": "text", "text": '{"choice": 0, "confidence"'},
            {"type": "text", "text": ': "low", "reason": "ok"}'},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client, _ = _client(body)
    got = AnthropicAdapter(client).ask(provider=CLAUDE, key=KEY, prompt="q")
    assert reply.parse(got.text, got.usage, choices=2).choice == 0


@pytest.mark.parametrize(
    ("status", "says"),
    [(401, "refused the key"), (403, "refused the key"), (429, "rate-limiting"),
     (500, "error")],
)
def test_a_refusal_says_what_to_do_and_never_echoes_the_key(status: int, says: str) -> None:
    client, _ = _client({"error": KEY}, status=status)
    with pytest.raises(AiError) as raised:
        OpenAiCompatibleAdapter(client).ask(provider=PROVIDER, key=KEY, prompt="q")
    assert says in str(raised.value)
    # AI-1: never the key, and never the payload, in anything that reaches a log.
    assert KEY not in str(raised.value)


def test_an_unreachable_provider_says_so_without_naming_the_address() -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    with pytest.raises(AiError) as raised:
        OpenAiCompatibleAdapter(client).ask(provider=PROVIDER, key=KEY, prompt="q")
    assert "could not reach" in str(raised.value)
    # An httpx error carries the full URL, and some gateways put the key in
    # one — so the message is ours, not the library's.
    assert "host/v1" not in str(raised.value) and KEY not in str(raised.value)


# --- interpretation: what the product makes of the words ---------------------

def test_a_reply_wrapped_in_a_fence_still_reads() -> None:
    """Models are asked for JSON and nothing else, and mostly comply. A
    ```json fence is the common near-miss and is not worth failing a paid
    call over."""
    fenced = "Here you go:\n```json\n" + json.dumps(ANSWER) + "\n```"
    assert reply.parse(fenced, USED, choices=3).choice == 1


def test_a_line_that_was_not_offered_is_refused_not_clamped() -> None:
    """The model naming a line that was not on the menu means it did not do
    the task. Quietly filing the charge somewhere is the exact failure this
    feature exists to prevent."""
    with pytest.raises(AiError, match="not one of the 3"):
        reply.parse(json.dumps({**ANSWER, "choice": 99}), USED, choices=3)


def test_an_answer_that_is_not_json_is_refused() -> None:
    with pytest.raises(AiError, match="JSON"):
        reply.parse("I think it's probably rooms revenue?", USED, choices=3)


def test_declining_without_a_reason_is_not_an_answer() -> None:
    """AI-7 asks the model to refuse on tax and capitalisation — and to say
    why. A bare refusal tells the owner nothing, so it is not accepted."""
    with pytest.raises(AiError, match="declined without saying why"):
        reply.parse(
            json.dumps({"choice": None, "confidence": "low", "reason": ""}), USED, choices=3
        )


# --- the offline stand-in ----------------------------------------------------

def test_the_practice_provider_answers_both_questions_offline() -> None:
    mock = MockAdapter()
    asked = mock.ask(provider=PROVIDER, key="", prompt="Printed on the report as: Cabana Rental\n")
    assert reply.parse(asked.text, asked.usage, choices=2).choice == 0

    taxed = mock.ask(
        provider=PROVIDER, key="", prompt="Printed on the report as: Occupancy tax collected\n"
    )
    declined = reply.parse(taxed.text, taxed.usage, choices=2)
    assert declined.choice is None and "tax" in (declined.decline_reason or "")


def test_the_practice_provider_reads_a_page_of_charges() -> None:
    """It stands in for reading a report, so the read path is exercised end to
    end without a key or a network."""
    from usali.desktop.ai import report

    # Lines as a real choiceADVANTAGE summary prints them: the description,
    # its code in brackets, then the money. Bracketed means money going out.
    # Per LINE, which is only possible because `pages` keeps the page's rows.
    page = "\n".join([
        "REPORT PAGES",
        "--- page 38 ---",
        "Hotel Journal Summary",
        "Date Range: 9/10/2026 - 9/10/2026 Property Code: RTI22",
        "Description (Transaction Code) Postings Corrections Adjustments Totals",
        "Room Charge (RM) 7,147.07 0.00 0.00 7,147.07",
        "State Occ Tax (T1) 437.42 0.00 0.00 437.42",
        "Visa Payment (VI) (2,406.13) 0.00 0.00 (2,406.13)",
    ])
    got = MockAdapter().ask(provider=PROVIDER, key="", prompt=page)
    read = report.parse(got.text, got.usage)
    codes = {r.code for r in read.rows}
    assert {"RM", "T1", "VI"} <= codes
    # The header is not a row: "Transaction Code" is two words, not a code.
    assert not any("Transaction" in c for c in codes)
    assert read.business_date is not None and read.business_date.isoformat() == "2026-09-10"
    # A figure in brackets is money going out.
    [visa] = [r for r in read.rows if r.code == "VI"]
    assert visa.amount < 0


def test_reading_a_report_carries_the_reading_guide_and_the_practice_provider_ignores_it() -> None:
    """The skill half of memory and skills: the model is told how night audits
    are laid out, from a guide shipped with the app — and that guide is not
    mistaken for the report itself."""
    from usali.desktop.ai import report
    from usali.desktop.ai.allowlist import check
    from usali.desktop.ai.pages import Page

    guide = report.reading_guide("SOME-NEW-SYSTEM")
    assert guide is not None and "in brackets" in guide  # the general guide
    assert not guide.startswith("---")  # front matter is for Obsidian, not the model
    page = Page(number=1, text="Business Date: 9/10/2026\nRoom Charge (RM) 100.00")
    prompt = report.render(report.ReportQuestion(hotel="Redstone Lodge", pages=(page,), guide=guide))
    assert prompt.index("READING GUIDE") < prompt.index("REPORT PAGES")
    check(prompt)  # nothing in a guide is refused on the way out
    got = MockAdapter().ask(provider=PROVIDER, key="", prompt=prompt)
    read = report.parse(got.text, got.usage)
    assert [(r.code, str(r.amount)) for r in read.rows] == [("RM", "100.00")]

"""The port every provider is reached through (ADR-D7, ADR-009).

Two adapters prove it — `OpenAiCompatibleAdapter`, which is a base URL and a
key, and `AnthropicAdapter`, whose Messages API is a genuinely different shape
— plus `MockAdapter`, which is deterministic and offline so no test needs a key
or a network.

`payroll_provider.py` is the shape being copied, including its rule that an
error must never carry the request: a provider error that echoed the payload
would put transaction data in a log, which is the one thing AI-1 forbids.
"""

from dataclasses import dataclass
from typing import Protocol


class AiError(RuntimeError):
    """A provider call failed.

    Messages must NEVER include the request payload, the key, or any part of
    either — the same rule as `payroll_provider.ProviderError`. Say what
    failed and what the owner can do, and nothing about what was sent.
    """


class SpendCapReached(AiError):
    """The month's cap is spent. The feature stops and says so (AI-2)."""


class NotConfigured(AiError):
    """No provider chosen, or no key in the keychain (AI-1)."""


@dataclass(frozen=True)
class Usage:
    """What the call cost, as the provider reported it.

    `prompt_tokens`/`completion_tokens` are None when a provider does not say
    — a local model often does not. The spend ledger records that honestly
    rather than guessing.
    """

    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class Reply:
    """What a provider said, and what it cost.

    Raw text on purpose: an adapter does the HTTP and the envelope, and
    nothing else. Interpreting the words is the caller's job, because the
    product asks two different questions — where does this code belong, and
    what rows are on this page — and an adapter that knew the difference would
    be an adapter that has to change every time a new question is asked.
    """

    text: str
    usage: Usage


@dataclass(frozen=True)
class Answer:
    """One model reply: the JSON object it returned, and what it cost.

    `choice` is the index of the line it picked, or None when it declined.
    `decline_reason` is required to be present when `choice` is None (AI-7):
    the model must be able to refuse on tax and capitalisation questions, and
    a refusal without a reason is not an answer.
    """

    choice: int | None
    confidence: str
    reason: str
    decline_reason: str | None
    usage: Usage

    def __post_init__(self) -> None:
        if self.choice is None and not self.decline_reason:
            raise AiError("the model declined without saying why")


@dataclass(frozen=True)
class Provider:
    """Where a call goes. The key is NOT here — it is read from the keychain
    at the moment of the call and never stored beside this (AI-1)."""

    #: "openai_compatible" | "anthropic" | "mock"
    kind: str
    model: str
    #: Only meaningful for `openai_compatible`; the adapter's whole point.
    base_url: str | None = None


class Adapter(Protocol):
    """Ask one question, get the provider's reply.

    Implementations do the HTTP and the response shape, and nothing else: the
    allow-list has already decided what may be in `prompt`, and the spend
    ledger has already decided the call may happen.
    """

    def ask(self, *, provider: Provider, key: str, prompt: str) -> Reply: ...

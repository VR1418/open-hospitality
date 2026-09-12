"""Asking the owner's model a question, safely (ADR-D7).

The order here is the design. Nothing reaches a provider that has not been
capped, built and scanned, and nothing comes back that is not recorded:

1. Is this set up at all, and is there a key? (AI-1)
2. Is the month's cap already spent? Refuse BEFORE the call, not after. (AI-2)
3. Build the prompt from a `CodeQuestion` — the allow-list's construction half.
4. Scan the outbound body and refuse if anything forbidden is in it. (AI-4)
5. Ask.
6. Record what left, what it cost, and how it ended — including when it ended
   badly. (AI-5)

A suggestion is the end of this module's job. Applying one is somebody's
click, through the same endpoint their own choice goes through (AI-6).
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from usali.desktop.ai import config, spend
from usali.desktop.ai.allowlist import (
    BlockedContent,
    CodeQuestion,
    LineChoice,
    check,
    forbidden_names,
    render,
)
from usali.desktop.ai.anthropic import AnthropicAdapter
from usali.desktop.ai.mock import MockAdapter
from usali.desktop.ai.openai_compatible import OpenAiCompatibleAdapter
from usali.desktop.ai.port import Adapter, AiError, NotConfigured, Provider, Usage
from usali.desktop.keystore import KeyStore
from usali.models import AuditEvent

PURPOSE_CLASSIFY = "classify_code"


@dataclass(frozen=True)
class Suggestion:
    """What the model proposed. Never written anywhere by itself."""

    code: str
    property_id: str
    #: None when the model declined, which AI-7 requires it to be able to do.
    line: LineChoice | None
    confidence: str
    reason: str
    decline_reason: str | None
    #: None when this call could not be priced — see `spend`.
    estimated_cost: Decimal | None
    model: str


def adapter_for(kind: str) -> Adapter:
    if kind == "anthropic":
        return AnthropicAdapter()
    if kind == "openai_compatible":
        return OpenAiCompatibleAdapter()
    if kind == "mock":
        return MockAdapter()
    raise NotConfigured(f"no such provider: {kind}")


def _record_and_commit(
    session: Session,
    *,
    settings: config.AiSettings,
    actor_subject: str,
    property_id: str | None,
    prompt: str,
    outcome: str,
    message: str,
) -> None:
    """Keep the record of a call that ended badly, and nothing else.

    Rolls back FIRST so the commit cannot sweep in a partial write — the rule
    `crm_api` already follows for its refusal audit. Without this the handler's
    own rollback would take the record with it, and AI-5 asks that every call
    be recorded, not every successful one.
    """
    session.rollback()
    spend.record(
        session, actor_subject=actor_subject, provider=settings.provider or "?",
        model=settings.model, purpose=PURPOSE_CLASSIFY, property_id=property_id,
        usage=Usage(None, None), prices=settings.prices, prompt=prompt,
        outcome=outcome, message=message,
    )
    session.commit()


def suggest_line_for_code(
    session: Session,
    *,
    store: KeyStore,
    sealed: Path,
    question: CodeQuestion,
    property_id: str,
    actor_subject: str,
    adapter: Adapter | None = None,
) -> Suggestion:
    """Ask the owner's model where one charge code belongs."""
    settings = config.read(session)
    if not settings.ready or settings.provider is None:
        raise NotConfigured(
            "No AI helper is set up yet. Choose one in AI settings first."
        )
    key = ""
    if settings.provider != "mock":
        found = config.read_key(store, sealed)
        if not found:
            raise NotConfigured(
                "Your AI helper has no key saved on this computer. Add it in AI settings."
            )
        key = found

    spend.check(spend.this_month(session, cap=settings.cap, max_calls=settings.max_calls))

    prompt = render(question)
    try:
        check(prompt, names=forbidden_names(session))
    except BlockedContent as blocked:
        _record_and_commit(
            session, settings=settings, actor_subject=actor_subject,
            property_id=property_id, prompt=prompt, outcome="blocked",
            message=str(blocked),
        )
        raise

    use = adapter or adapter_for(settings.provider)
    provider = Provider(
        kind=settings.provider, model=settings.model, base_url=settings.base_url
    )
    try:
        answer = use.ask(
            provider=provider, key=key, prompt=prompt, choices=len(question.choices)
        )
    except AiError as failed:
        _record_and_commit(
            session, settings=settings, actor_subject=actor_subject,
            property_id=property_id, prompt=prompt, outcome="failed", message=str(failed),
        )
        raise

    outcome = "answered" if answer.choice is not None else "declined"
    cost = spend.record(
        session, actor_subject=actor_subject, provider=settings.provider,
        model=settings.model, purpose=PURPOSE_CLASSIFY, property_id=property_id,
        usage=answer.usage, prices=settings.prices, prompt=prompt, outcome=outcome,
    )
    # AI-5's second half: the org trail, which `desktop.ai_call` cannot be —
    # it is an install table and carries no org.
    session.add(AuditEvent(
        actor_subject=actor_subject, action=f"ai_suggestion_{outcome}",
        resource_type="pms_trx_code", resource_id=f"{property_id}:{question.code}"[:64],
    ))
    return Suggestion(
        code=question.code,
        property_id=property_id,
        line=question.choices[answer.choice] if answer.choice is not None else None,
        confidence=answer.confidence,
        reason=answer.reason,
        decline_reason=answer.decline_reason,
        estimated_cost=cost,
        model=settings.model,
    )

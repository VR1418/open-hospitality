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
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from usali.desktop.ai import config, report, reply, spend
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
from usali.desktop.ai.pages import HeldBack, Reading, safe_pages
from usali.desktop.ai.port import Adapter, AiError, NotConfigured, Provider, Usage
from usali.desktop.keystore import KeyStore
from usali.models import AuditEvent

PURPOSE_CLASSIFY = "classify_code"
PURPOSE_READ = "read_report"
PURPOSE_TEST = "connection_test"

_NO_KEY = "Your AI helper has no key saved on this computer. Add it in AI settings."

#: The whole of what a connection check sends. Fixed, and about nothing: the
#: owner is checking the key and the model name, not asking a question.
TEST_PROMPT = "This is a connection check from Open Hospitality. Reply with the single word OK."


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


def _said(got: object) -> tuple[str, Usage]:
    """A provider's reply, unpacked. The adapter does transport; reading the
    words is the caller's job, and the two questions read them differently."""
    return str(getattr(got, "text", "")), getattr(got, "usage", Usage(None, None))


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
    purpose: str = PURPOSE_CLASSIFY,
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
        model=settings.model, purpose=purpose, property_id=property_id,
        usage=Usage(None, None), prices=settings.prices, prompt=prompt,
        outcome=outcome, message=message,
    )
    session.commit()


def _key(settings: config.AiSettings, store: KeyStore, sealed: Path, missing: str) -> str:
    """The saved key, or "" where none is needed: practice mode, and a model
    on this computer (Ollama and LM Studio ignore it)."""
    found = config.read_key(store, sealed)
    if settings.provider == "mock" or settings.prices.local:
        return found or ""
    if not found:
        raise NotConfigured(missing)
    return found


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
    key = _key(settings, store, sealed, _NO_KEY)

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
        answer = reply.parse(
            *_said(use.ask(provider=provider, key=key, prompt=prompt)),
            choices=len(question.choices),
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


@dataclass(frozen=True)
class ReportReading:
    """What the model made of a report the product cannot parse.

    `held_back` is part of the answer, not a footnote: the owner is entitled
    to know which pages were kept from the model and why before deciding
    whether to trust what came back from the rest.
    """

    hotel: str
    rows: tuple[report.ExtractedRow, ...]
    business_date: date | None
    decline_reason: str | None
    pages_read: tuple[int, ...]
    held_back: tuple[HeldBack, ...]
    estimated_cost: Decimal | None
    model: str


def read_report(
    session: Session,
    *,
    store: KeyStore,
    sealed: Path,
    pdf: Path,
    hotel: str,
    property_id: str,
    actor_subject: str,
    adapter: Adapter | None = None,
) -> ReportReading:
    """Ask the owner's model what charges are on a report we cannot parse.

    The order is the same as every other call — configured, capped, scanned,
    asked, recorded — with one difference that matters: the scan runs BEFORE
    the prompt exists, page by page, and decides what the prompt may contain
    (`pages`). Nothing is staged here. The rows come back to be confirmed.
    """
    settings = config.read(session)
    if not settings.ready or settings.provider is None:
        raise NotConfigured("No AI helper is set up yet. Choose one in AI settings first.")
    key = _key(settings, store, sealed, _NO_KEY)

    spend.check(spend.this_month(session, cap=settings.cap, max_calls=settings.max_calls))

    reading: Reading = safe_pages(pdf, names=forbidden_names(session))
    if not reading.anything_to_send:
        raise BlockedContent(
            "nothing on any page of this report that could be shown to a model"
        )

    question = report.ReportQuestion(
        hotel=hotel, pages=reading.kept, guide=report.reading_guide(report.OTHER_SOURCE)
    )
    prompt = report.render(question)
    # Belt and braces: the pages passed one at a time, so the whole prompt
    # must pass too. A failure here is a bug in `pages`, not in the report.
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
        extracted = report.parse(*_said(use.ask(provider=provider, key=key, prompt=prompt)))
    except AiError as failed:
        _record_and_commit(
            session, settings=settings, actor_subject=actor_subject,
            property_id=property_id, prompt=prompt, outcome="failed", message=str(failed),
        )
        raise

    outcome = "answered" if extracted.rows else "declined"
    cost = spend.record(
        session, actor_subject=actor_subject, provider=settings.provider,
        model=settings.model, purpose=PURPOSE_READ, property_id=property_id,
        usage=Usage(None, None), prices=settings.prices, prompt=prompt, outcome=outcome,
    )
    session.add(AuditEvent(
        actor_subject=actor_subject, action=f"ai_report_{outcome}",
        resource_type="property", resource_id=property_id[:64],
    ))
    return ReportReading(
        hotel=hotel,
        rows=extracted.rows,
        business_date=extracted.business_date,
        decline_reason=extracted.decline_reason,
        pages_read=tuple(p.number for p in reading.kept),
        held_back=reading.held_back,
        estimated_cost=cost,
        model=settings.model,
    )


@dataclass(frozen=True)
class ConnectionCheck:
    model: str
    #: The first few words it said — enough to see it answered.
    said: str
    estimated_cost: Decimal | None


def test_connection(
    session: Session,
    *,
    store: KeyStore,
    sealed: Path,
    actor_subject: str,
    adapter: Adapter | None = None,
) -> ConnectionCheck:
    """Ask the saved helper one fixed, content-free question.

    The same gates as any call — set up, key present, under the cap — and the
    same record afterwards, because it costs the owner money like any other
    (AI-2, AI-5). What it proves is what setup cannot: that the service
    accepts this key and knows this model's name.
    """
    settings = config.read(session)
    if not settings.ready or settings.provider is None:
        raise NotConfigured("Save a helper and a model first, then check it.")
    key = _key(settings, store, sealed, "There is no key saved on this computer yet.")
    spend.check(spend.this_month(session, cap=settings.cap, max_calls=settings.max_calls))

    use = adapter or adapter_for(settings.provider)
    provider = Provider(kind=settings.provider, model=settings.model, base_url=settings.base_url)
    try:
        text, usage = _said(use.ask(provider=provider, key=key, prompt=TEST_PROMPT))
    except AiError as failed:
        _record_and_commit(
            session, settings=settings, actor_subject=actor_subject, property_id=None,
            prompt=TEST_PROMPT, outcome="failed", message=str(failed), purpose=PURPOSE_TEST,
        )
        raise
    cost = spend.record(
        session, actor_subject=actor_subject, provider=settings.provider,
        model=settings.model, purpose=PURPOSE_TEST, property_id=None, usage=usage,
        prices=settings.prices, prompt=TEST_PROMPT, outcome="answered",
    )
    return ConnectionCheck(
        model=settings.model, said=" ".join(text.split())[:60], estimated_cost=cost
    )

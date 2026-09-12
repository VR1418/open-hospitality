"""Turning a provider's reply into an `Answer` (ADR-D7).

Shared by both adapters, because the model is asked for the same JSON object
whichever endpoint carries it — the shapes that differ are the request and the
envelope, which is what the two adapters are for.
"""

import json
from typing import Any

from usali.desktop.ai.port import Answer, AiError, Usage

_CONFIDENCE = ("high", "medium", "low")


def _object_in(text: str) -> str:
    """The JSON object in a reply that may be wrapped in prose or a fence.

    Models are asked for JSON and nothing else, and mostly comply; a ```json
    fence is the common near-miss and is not worth failing a paid call over.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise AiError("the model did not answer with the JSON it was asked for")
    return text[start : end + 1]


def parse(text: str, usage: Usage, *, choices: int) -> Answer:
    """`Answer` from the model's reply, or `AiError` if it is not usable.

    A choice outside the list offered is refused rather than clamped: the
    model picking a line that was not on the menu means it did not do the task,
    and quietly filing the charge somewhere is exactly the failure this whole
    feature is supposed to prevent.
    """
    try:
        body: Any = json.loads(_object_in(text))
    except json.JSONDecodeError as exc:
        raise AiError("the model's answer was not readable JSON") from exc
    if not isinstance(body, dict):
        raise AiError("the model's answer was not a JSON object")

    choice = body.get("choice")
    if choice is not None:
        if not isinstance(choice, int) or isinstance(choice, bool):
            raise AiError("the model's choice was not a whole number")
        if not 0 <= choice < choices:
            raise AiError(
                f"the model chose line {choice}, which was not one of the "
                f"{choices} it was offered"
            )

    confidence = str(body.get("confidence", "low")).lower()
    if confidence not in _CONFIDENCE:
        confidence = "low"
    decline = body.get("decline_reason")
    return Answer(
        choice=choice,
        confidence=confidence,
        reason=str(body.get("reason", "")).strip()[:500],
        decline_reason=str(decline).strip()[:500] if decline else None,
        usage=usage,
    )

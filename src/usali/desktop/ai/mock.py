"""A provider that answers without a network or a key (PRD §6.3).

Deterministic on purpose: the same question gives the same answer every run,
so tests assert on behaviour rather than on a model's mood. It also exercises
the paths a real provider must support and a happy-path fake would skip —
declining (AI-7), reporting usage (AI-2), and both of the questions the
product actually asks.
"""

import json
import re

from usali.desktop.ai.port import Adapter, AiError, Provider, Reply, Usage

#: Words in a charge description that a model is REQUIRED to decline on
#: (AI-7): where the answer turns on this hotel's tax treatment, or on whether
#: something is an expense or a capital item, guessing is worse than refusing.
MUST_DECLINE = ("tax", "vat", "gst", "capital", "asset", "depreciation")

#: The line `allowlist.render` writes the charge's printed description on.
_DESCRIPTION = "printed on the report as:"

#: A row as a night-audit summary actually prints it, taken from a real
#: choiceADVANTAGE export: the description first, its transaction code in
#: brackets, then the money. The header line reads "Description (Transaction
#: Code)" and is excluded for free — that is two words, not a code.
#:
#: Matching per LINE is only possible because `pages` hands the page over as
#: lines rather than as one run-on string.
_ROW = re.compile(
    r"^(?P<desc>.+?)\s*\((?P<code>[A-Z0-9]{1,6})\)\s+"
    r"(?P<amount>\(\d[\d,]*\.\d{2}\)|-?[\d,]+\.\d{2})"
)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _described(prompt: str) -> str:
    for line in prompt.splitlines():
        lowered = line.lower()
        if lowered.startswith(_DESCRIPTION):
            return lowered[len(_DESCRIPTION) :].strip()
    return ""


def _read_pages(prompt: str) -> str:
    """Stand in for reading a report: take the description, code and amount
    off each line that has them."""
    rows = []
    for line in prompt.splitlines():
        found = _ROW.match(line.strip())
        if found is None:
            continue
        raw = found.group("amount")
        negative = raw.startswith("(")
        amount = raw.strip("()").replace(",", "")
        rows.append({
            "code": found.group("code"),
            "description": found.group("desc").strip(),
            "amount": ("-" + amount) if negative else amount,
        })
    when = _DATE.search(prompt)
    business_date = (
        f"{when.group(3)}-{int(when.group(1)):02d}-{int(when.group(2)):02d}"
        if when
        else None
    )
    if not rows:
        return json.dumps({
            "business_date": None,
            "rows": [],
            "decline_reason": "I could not find any charge lines on these pages.",
        })
    return json.dumps({
        "business_date": business_date, "rows": rows, "decline_reason": None,
    })


class MockAdapter(Adapter):
    def ask(self, *, provider: Provider, key: str, prompt: str) -> Reply:
        if not prompt:
            raise AiError("nothing to ask about")
        usage = Usage(prompt_tokens=len(prompt) // 4, completion_tokens=24)

        if "REPORT PAGES" in prompt:
            return Reply(text=_read_pages(prompt), usage=usage)

        # Only the charge's own description, never the whole prompt: the
        # instructions themselves mention tax and capital items, so a mock
        # that read those would decline every question ever asked.
        found = next((w for w in MUST_DECLINE if w in _described(prompt)), None)
        if found is not None:
            return Reply(
                text=json.dumps({
                    "choice": None, "confidence": "low", "reason": "",
                    "decline_reason": (
                        f"This looks like it turns on {found} treatment, which depends on "
                        "your hotel's own circumstances. Ask your accountant rather than me."
                    ),
                }),
                usage=usage,
            )
        # The first line offered, which is deterministic and always valid.
        return Reply(
            text=json.dumps({
                "choice": 0, "confidence": "medium",
                "reason": "Picked the first line offered — this is the offline stand-in provider.",
                "decline_reason": None,
            }),
            usage=usage,
        )

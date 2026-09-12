"""A provider that answers without a network or a key (PRD §6.3).

Deterministic on purpose: the same question gives the same answer every run,
so tests assert on behaviour rather than on a model's mood. It also exercises
the two paths a real provider must support and a happy-path fake would skip —
declining (AI-7) and reporting usage (AI-2).
"""

from usali.desktop.ai.port import Answer, Adapter, AiError, Provider, Usage

#: Words in a charge description that a model is REQUIRED to decline on
#: (AI-7): where the answer turns on this hotel's tax treatment, or on whether
#: something is an expense or a capital item, guessing is worse than refusing.
MUST_DECLINE = ("tax", "vat", "gst", "capital", "asset", "depreciation")


#: The line `allowlist.render` writes the charge's printed description on.
_DESCRIPTION = "printed on the report as:"


def _described(prompt: str) -> str:
    for line in prompt.splitlines():
        lowered = line.lower()
        if lowered.startswith(_DESCRIPTION):
            return lowered[len(_DESCRIPTION) :].strip()
    return ""


class MockAdapter(Adapter):
    def ask(
        self, *, provider: Provider, key: str, prompt: str, choices: int
    ) -> Answer:
        if not prompt:
            raise AiError("nothing to ask about")
        if choices < 1:
            raise AiError("there were no lines to choose from")
        # Only the charge's own description, never the whole prompt: the
        # instructions themselves mention tax and capital items, so a mock
        # that read those would decline every question ever asked.
        found = next((w for w in MUST_DECLINE if w in _described(prompt)), None)
        usage = Usage(prompt_tokens=len(prompt) // 4, completion_tokens=24)
        if found is not None:
            return Answer(
                choice=None, confidence="low", reason="",
                decline_reason=(
                    f"This looks like it turns on {found} treatment, which depends on your "
                    "hotel's own circumstances. Ask your accountant rather than me."
                ),
                usage=usage,
            )
        # The first line offered, which is deterministic and always valid.
        return Answer(
            choice=0, confidence="medium",
            reason="Picked the first line offered — this is the offline stand-in provider.",
            decline_reason=None, usage=usage,
        )

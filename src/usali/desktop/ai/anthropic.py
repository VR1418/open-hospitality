"""Anthropic's native Messages API (PRD §6.3, ADR-D7).

The second adapter exists to PROVE the port rather than to add a vendor: its
request and envelope are a genuinely different shape — a top-level
`max_tokens`, a key in `x-api-key` rather than a bearer token, a dated version
header, and a content LIST in the reply — so a port that fits both is not
quietly one vendor's assumptions (ADR-009).
"""

from typing import Any

import httpx

from usali.desktop.ai import reply
from usali.desktop.ai.port import Answer, Adapter, AiError, Provider, Usage

BASE_URL = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"
MAX_TOKENS = 1024
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _usage(body: dict[str, Any]) -> Usage:
    got = body.get("usage") or {}
    prompt = got.get("input_tokens")
    completion = got.get("output_tokens")
    return Usage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
    )


class AnthropicAdapter(Adapter):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def ask(self, *, provider: Provider, key: str, prompt: str, choices: int) -> Answer:
        url = (provider.base_url or BASE_URL).rstrip("/") + "/messages"
        request = {
            "model": provider.model,
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        client = self._client or httpx.Client(timeout=TIMEOUT)
        try:
            res = client.post(
                url, json=request,
                headers={"x-api-key": key, "anthropic-version": VERSION},
            )
        except httpx.HTTPError:
            raise AiError(
                "could not reach Anthropic. Check that you are online."
            ) from None
        finally:
            if self._client is None:
                client.close()
        if res.status_code in (401, 403):
            raise AiError("Anthropic refused the key. Check it and paste it again.")
        if res.status_code == 429:
            raise AiError("Anthropic is rate-limiting you. Try again in a minute.")
        if res.status_code >= 400:
            raise AiError(f"Anthropic answered with an error ({res.status_code}).")
        body = res.json()
        try:
            text = "".join(
                part.get("text", "") for part in body["content"] if part.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise AiError("Anthropic's answer was not in the shape we expected") from exc
        return reply.parse(text, _usage(body), choices=choices)

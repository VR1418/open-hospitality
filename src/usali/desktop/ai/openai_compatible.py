"""One adapter for every OpenAI-shaped endpoint (PRD §6.3, ADR-D7).

A base URL and a key is the whole configuration, which is why OpenRouter,
OpenAI, Ollama, LM Studio, Groq, Together and Azure are all this one adapter
rather than five. Ollama and LM Studio serve the same shape on localhost, so
"nothing leaves the building" is a base URL, not a different code path.
"""

from typing import Any

import httpx

from usali.desktop.ai import reply
from usali.desktop.ai.port import Answer, Adapter, AiError, Provider, Usage

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _usage(body: dict[str, Any]) -> Usage:
    got = body.get("usage") or {}
    prompt = got.get("prompt_tokens")
    completion = got.get("completion_tokens")
    return Usage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
    )


class OpenAiCompatibleAdapter(Adapter):
    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injected in tests, so no test needs a network or a key.
        self._client = client

    def ask(self, *, provider: Provider, key: str, prompt: str, choices: int) -> Answer:
        if not provider.base_url:
            raise AiError("this provider needs a web address to send to")
        url = provider.base_url.rstrip("/") + "/chat/completions"
        request = {
            "model": provider.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        client = self._client or httpx.Client(timeout=TIMEOUT)
        try:
            res = client.post(url, json=request, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            # Deliberately not `from exc` and deliberately not str(exc): an
            # httpx error can carry the full request URL, and the URL can
            # carry a key on some gateways (ADR-D7, AI-1).
            raise AiError(
                "could not reach that provider. Check the web address, and that "
                "you are online — or that your local model is running."
            ) from None
        finally:
            if self._client is None:
                client.close()
        if res.status_code == 401 or res.status_code == 403:
            raise AiError("that provider refused the key. Check it and paste it again.")
        if res.status_code == 429:
            raise AiError("that provider is rate-limiting you. Try again in a minute.")
        if res.status_code >= 400:
            raise AiError(f"that provider answered with an error ({res.status_code}).")
        body = res.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AiError("that provider's answer was not in the shape we expected") from exc
        return reply.parse(str(text), _usage(body), choices=choices)

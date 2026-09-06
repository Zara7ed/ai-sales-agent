"""OpenAI-compatible chat client with ordered provider chain + fallback.

Works with OpenAI, OpenRouter, 9router/OmniRoute local endpoints, or any
OpenAI-compatible HTTP API (POST {base_url}/chat/completions).

Fallback triggers on: transport errors, timeouts, HTTP 429 / 5xx, and
API-level error payloads. Per-provider timeout and retry are configurable.
Usage/cost logging is done via injectable hook callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx


@dataclass
class Provider:
    """One chat-completions endpoint in the failover chain."""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0
    max_retries: int = 1


@dataclass
class ChatResult:
    """Normalised result of a chat completion call."""

    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


# Hook signatures
UsageHook = Callable[[str, str, dict[str, Any]], None]
CostHook = Callable[[str, str, dict[str, Any]], None]
LogHook = Callable[[str], None]

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMRouterError(RuntimeError):
    """Raised when every provider in the chain fails."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class LLMRouter:
    """Chat client that walks an ordered provider chain with fallback."""

    def __init__(
        self,
        providers: list[Provider | dict[str, Any]],
        on_usage: Optional[UsageHook] = None,
        on_cost: Optional[CostHook] = None,
        on_log: Optional[LogHook] = None,
        client: Optional[httpx.Client] = None,
    ):
        if not providers:
            raise ValueError("providers must be a non-empty list")
        self.providers: list[Provider] = [
            p if isinstance(p, Provider) else Provider(**p) for p in providers
        ]
        self.on_usage = on_usage
        self.on_cost = on_cost
        self.on_log = on_log
        self._client = client  # injectable for tests

    def _log(self, msg: str) -> None:
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _headers(self, provider: Provider) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        return headers

    def _extract_text(self, payload: dict[str, Any]) -> str:
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        extra: Optional[dict[str, Any]] = None,
    ) -> ChatResult:
        """Send chat messages, trying each provider in order with fallback."""
        errors: list[str] = []
        for provider in self.providers:
            url = provider.base_url.rstrip("/") + "/chat/completions"
            body: dict[str, Any] = {
                "model": provider.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if extra:
                body.update(extra)
            attempts = max(1, provider.max_retries + 1)
            for attempt in range(attempts):
                try:
                    if self._client is not None:
                        resp = self._client.post(
                            url,
                            json=body,
                            headers=self._headers(provider),
                            timeout=provider.timeout,
                        )
                    else:
                        with httpx.Client(timeout=provider.timeout) as cli:
                            resp = cli.post(
                                url, json=body, headers=self._headers(provider)
                            )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    msg = f"{provider.name}: transport/timeout ({exc})"
                    self._log(msg)
                    errors.append(msg)
                    break  # move to next provider on timeout/transport error
                except Exception as exc:  # defensive: never crash the chain
                    msg = f"{provider.name}: unexpected error ({exc})"
                    self._log(msg)
                    errors.append(msg)
                    break

                status = resp.status_code
                if status == 200:
                    try:
                        payload = resp.json()
                    except Exception as exc:
                        msg = f"{provider.name}: bad JSON ({exc})"
                        errors.append(msg)
                        break
                    if isinstance(payload, dict) and payload.get("error"):
                        msg = f"{provider.name}: api error {payload['error']}"
                        errors.append(msg)
                        break  # API-level error -> try next provider
                    text = self._extract_text(payload)
                    usage = payload.get("usage", {}) or {}
                    if self.on_usage:
                        try:
                            self.on_usage(provider.name, provider.model, usage)
                        except Exception:
                            pass
                    if self.on_cost:
                        try:
                            self.on_cost(provider.name, provider.model, usage)
                        except Exception:
                            pass
                    return ChatResult(
                        text=text,
                        provider=provider.name,
                        model=provider.model,
                        usage=usage,
                        raw=payload,
                    )
                if status in RETRYABLE_STATUS:
                    msg = f"{provider.name}: HTTP {status} (attempt {attempt + 1})"
                    self._log(msg)
                    if attempt < attempts - 1:
                        continue  # retry same provider
                    errors.append(msg)
                    break  # exhausted retries -> next provider
                # Non-retryable 4xx: still fall through to next provider
                # (key may be wrong for this provider but valid for the next).
                msg = f"{provider.name}: HTTP {status}: {resp.text[:300]}"
                errors.append(msg)
                break
        raise LLMRouterError("All LLM providers failed", errors=errors)

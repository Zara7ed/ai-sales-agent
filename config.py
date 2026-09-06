"""Env-based settings for the AI Sales & Customer Support Agent.

All configuration comes from environment variables with sensible defaults
so the engine runs locally with zero setup and in production via env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _getfloat(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _getint(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


@dataclass
class ProviderConfig:
    """Single OpenAI-compatible LLM provider endpoint."""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0
    max_retries: int = 1


@dataclass
class Settings:
    """Runtime settings loaded from environment variables."""

    # Primary LLM provider (e.g. OpenAI, OpenRouter, 9router/OmniRoute, local)
    primary_base_url: str = "https://api.openai.com/v1"
    primary_api_key: str = ""
    primary_model: str = "gpt-4o-mini"
    primary_timeout: float = 30.0
    # Secondary (fallback) LLM provider
    secondary_base_url: str = ""
    secondary_api_key: str = ""
    secondary_model: str = ""
    secondary_timeout: float = 30.0
    # Router behaviour
    max_retries_per_provider: int = 1
    # Company defaults
    company_name: str = "Acme"
    company_tone: str = "friendly, direct, human-like"
    default_language: str = "en"
    max_reply_words: int = 80
    # Paths
    kb_path: str = "kb.json"
    db_path: str = "conversations.db"

    providers: list[ProviderConfig] = field(default_factory=list)

    def ordered_providers(self) -> list[ProviderConfig]:
        """Return the ordered provider chain (primary first, then secondary)."""
        return list(self.providers)


def load() -> Settings:
    """Load settings from environment variables.

    Recognised variables:
      PRIMARY_BASE_URL / PRIMARY_API_KEY / PRIMARY_MODEL / PRIMARY_TIMEOUT
      SECONDARY_BASE_URL / SECONDARY_API_KEY / SECONDARY_MODEL / SECONDARY_TIMEOUT
      LLM_MAX_RETRIES, COMPANY_NAME, COMPANY_TONE, DEFAULT_LANGUAGE,
      MAX_REPLY_WORDS, KB_PATH, DB_PATH
    """
    s = Settings(
        primary_base_url=_getenv("PRIMARY_BASE_URL", "https://api.openai.com/v1"),
        primary_api_key=_getenv("PRIMARY_API_KEY", ""),
        primary_model=_getenv("PRIMARY_MODEL", "gpt-4o-mini"),
        primary_timeout=_getfloat("PRIMARY_TIMEOUT", 30.0),
        secondary_base_url=_getenv("SECONDARY_BASE_URL", ""),
        secondary_api_key=_getenv("SECONDARY_API_KEY", ""),
        secondary_model=_getenv("SECONDARY_MODEL", ""),
        secondary_timeout=_getfloat("SECONDARY_TIMEOUT", 30.0),
        max_retries_per_provider=_getint("LLM_MAX_RETRIES", 1),
        company_name=_getenv("COMPANY_NAME", "Acme"),
        company_tone=_getenv("COMPANY_TONE", "friendly, direct, human-like"),
        default_language=_getenv("DEFAULT_LANGUAGE", "en"),
        max_reply_words=_getint("MAX_REPLY_WORDS", 80),
        kb_path=_getenv("KB_PATH", "kb.json"),
        db_path=_getenv("DB_PATH", "conversations.db"),
    )
    providers: list[ProviderConfig] = [
        ProviderConfig(
            name="primary",
            base_url=s.primary_base_url.rstrip("/"),
            api_key=s.primary_api_key,
            model=s.primary_model,
            timeout=s.primary_timeout,
            max_retries=s.max_retries_per_provider,
        )
    ]
    if s.secondary_base_url or s.secondary_api_key or s.secondary_model:
        providers.append(
            ProviderConfig(
                name="secondary",
                base_url=(s.secondary_base_url or s.primary_base_url).rstrip("/"),
                api_key=s.secondary_api_key,
                model=s.secondary_model or s.primary_model,
                timeout=s.secondary_timeout,
                max_retries=s.max_retries_per_provider,
            )
        )
    s.providers = providers
    return s

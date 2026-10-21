"""Provider-independent requests, replies, and reported token usage."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_MAX_TOKENS = 16_000
DEFAULT_MODELS = {"anthropic": "claude-opus-5", "openai": "gpt-5"}
OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


@dataclass(frozen=True)
class Settings:
    backend: str
    model: str | None = None
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    profile: str | None = None
    api_key_env: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    token_parameter: str = "max_completion_tokens"
    requires_key: bool = True
    isolated: bool = False
    account_id: str | None = None
    cli_home: str | None = None

    @property
    def effective_model(self) -> str | None:
        return self.model or DEFAULT_MODELS.get(self.backend)


@dataclass(frozen=True)
class Request:
    prompt: str
    system: str | None
    timeout: int
    max_tokens: int
    task: str
    request_id: str


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_tokens: int | None = None


@dataclass(frozen=True)
class Completion:
    text: str | None
    reason: str = "ok"
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str | None = None
    provider_request_id: str | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    backend: str | None = None
    profile: str | None = None

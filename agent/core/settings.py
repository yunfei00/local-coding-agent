from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any
from urllib.parse import urlparse

from agent.llm.base import LLMProvider
from agent.llm.factory import normalize_provider_name
from agent.llm.ollama import OllamaProvider
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.persistence.store import SQLiteStore


SETTINGS_PREFIX = "runtime."


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class RuntimeSettings:
    provider: str
    ollama_base_url: str
    ollama_model: str
    ollama_context_window: int
    ollama_temperature: float
    openai_base_url: str
    openai_model: str
    openai_context_window: int
    openai_temperature: float
    context_reserved_output_tokens: int
    max_model_steps: int
    max_tool_calls: int
    max_blocked_repeats: int
    max_consecutive_tool_failures: int
    model_retry_attempts: int

    @classmethod
    def defaults(cls) -> "RuntimeSettings":
        return cls(
            provider=normalize_provider_name(os.getenv("LCA_PROVIDER")),
            ollama_base_url=(
                os.getenv("LCA_OLLAMA_URL")
                or "http://127.0.0.1:11434"
            ).rstrip("/"),
            ollama_model=(
                os.getenv("LCA_OLLAMA_MODEL")
                or "qwen3-coder:30b"
            ).strip(),
            ollama_context_window=_env_int(
                "LCA_OLLAMA_NUM_CTX",
                32768,
            ),
            ollama_temperature=_env_float(
                "LCA_OLLAMA_TEMPERATURE",
                0.2,
            ),
            openai_base_url=(
                os.getenv("LCA_OPENAI_BASE_URL")
                or "http://127.0.0.1:8000/v1"
            ).rstrip("/"),
            openai_model=(
                os.getenv("LCA_OPENAI_MODEL")
                or ""
            ).strip(),
            openai_context_window=_env_int(
                "LCA_OPENAI_CONTEXT_WINDOW",
                32768,
            ),
            openai_temperature=_env_float(
                "LCA_OPENAI_TEMPERATURE",
                0.2,
            ),
            context_reserved_output_tokens=_env_int(
                "LCA_CONTEXT_RESERVED_OUTPUT_TOKENS",
                4096,
            ),
            max_model_steps=_env_int(
                "LCA_MAX_MODEL_STEPS",
                16,
            ),
            max_tool_calls=_env_int(
                "LCA_MAX_TOOL_CALLS",
                40,
            ),
            max_blocked_repeats=_env_int(
                "LCA_MAX_BLOCKED_REPEATS",
                3,
            ),
            max_consecutive_tool_failures=_env_int(
                "LCA_MAX_CONSECUTIVE_TOOL_FAILURES",
                4,
            ),
            model_retry_attempts=_env_int(
                "LCA_MODEL_RETRY_ATTEMPTS",
                2,
            ),
        )

    @classmethod
    def load(cls, store: SQLiteStore) -> "RuntimeSettings":
        defaults = cls.defaults()
        values = asdict(defaults)
        for key, default in list(values.items()):
            stored = store.get_setting(SETTINGS_PREFIX + key)
            if stored is None:
                continue
            try:
                if isinstance(default, int) and not isinstance(default, bool):
                    values[key] = int(stored)
                elif isinstance(default, float):
                    values[key] = float(stored)
                else:
                    values[key] = stored
            except ValueError:
                values[key] = default
        return cls.validate(values)

    @classmethod
    def validate(cls, raw: dict[str, Any]) -> "RuntimeSettings":
        defaults = asdict(cls.defaults())
        values = {**defaults, **raw}
        provider = normalize_provider_name(str(values["provider"]))

        def url(name: str) -> str:
            value = str(values[name] or "").strip().rstrip("/")
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    f"{name} must be an http:// or https:// URL."
                )
            return value

        def text(name: str, *, allow_empty: bool = False) -> str:
            value = str(values[name] or "").strip()
            if not allow_empty and not value:
                raise ValueError(f"{name} cannot be empty.")
            return value

        def integer(
            name: str,
            minimum: int,
            maximum: int,
        ) -> int:
            try:
                value = int(values[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be an integer.") from exc
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}."
                )
            return value

        def number(
            name: str,
            minimum: float,
            maximum: float,
        ) -> float:
            try:
                value = float(values[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a number.") from exc
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}."
                )
            return value

        return cls(
            provider=provider,
            ollama_base_url=url("ollama_base_url"),
            ollama_model=text("ollama_model"),
            ollama_context_window=integer(
                "ollama_context_window",
                1024,
                262144,
            ),
            ollama_temperature=number(
                "ollama_temperature",
                0.0,
                2.0,
            ),
            openai_base_url=url("openai_base_url"),
            openai_model=text(
                "openai_model",
                allow_empty=True,
            ),
            openai_context_window=integer(
                "openai_context_window",
                1024,
                262144,
            ),
            openai_temperature=number(
                "openai_temperature",
                0.0,
                2.0,
            ),
            context_reserved_output_tokens=integer(
                "context_reserved_output_tokens",
                256,
                65536,
            ),
            max_model_steps=integer(
                "max_model_steps",
                1,
                128,
            ),
            max_tool_calls=integer(
                "max_tool_calls",
                1,
                512,
            ),
            max_blocked_repeats=integer(
                "max_blocked_repeats",
                1,
                20,
            ),
            max_consecutive_tool_failures=integer(
                "max_consecutive_tool_failures",
                1,
                50,
            ),
            model_retry_attempts=integer(
                "model_retry_attempts",
                1,
                5,
            ),
        )

    def save(self, store: SQLiteStore) -> None:
        for key, value in asdict(self).items():
            store.set_setting(
                SETTINGS_PREFIX + key,
                str(value),
            )

    def to_public_dict(
        self,
        *,
        api_key_configured: bool,
    ) -> dict[str, Any]:
        return {
            **asdict(self),
            "api_key_configured": api_key_configured,
        }

    def create_provider(
        self,
        *,
        openai_api_key: str | None = None,
    ) -> LLMProvider:
        if self.provider == "openai_compatible":
            return OpenAICompatibleProvider(
                base_url=self.openai_base_url,
                api_key=(
                    openai_api_key
                    if openai_api_key is not None
                    else os.getenv("LCA_OPENAI_API_KEY", "")
                ),
                preferred_model=self.openai_model,
                context_window=self.openai_context_window,
                temperature=self.openai_temperature,
            )
        return OllamaProvider(
            base_url=self.ollama_base_url,
            preferred_model=self.ollama_model,
            context_window=self.ollama_context_window,
            temperature=self.ollama_temperature,
        )

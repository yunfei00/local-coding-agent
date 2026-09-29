from __future__ import annotations

import os

from agent.llm.base import LLMProvider
from agent.llm.ollama import OllamaProvider
from agent.llm.openai_compatible import OpenAICompatibleProvider


def normalize_provider_name(value: str | None) -> str:
    normalized = (value or "ollama").strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_compatible", "compatible"}:
        return "openai_compatible"
    if normalized == "ollama":
        return "ollama"
    raise ValueError(f"Unsupported LCA provider: {value!r}")


def create_provider_from_env() -> LLMProvider:
    provider_name = normalize_provider_name(os.getenv("LCA_PROVIDER"))
    if provider_name == "openai_compatible":
        return OpenAICompatibleProvider()
    return OllamaProvider()

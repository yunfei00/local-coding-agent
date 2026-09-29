from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.transient = transient


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size: int | None = None
    digest: str | None = None
    modified_at: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@dataclass(frozen=True)
class ProviderChunk:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    done: bool = False
    finish_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class LLMProvider(Protocol):
    provider_name: str
    preferred_model: str
    context_window: int

    async def list_models(self) -> list[ModelInfo]:
        ...

    async def get_status(self) -> dict[str, Any]:
        ...

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        ...

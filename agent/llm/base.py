from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
import time


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


def observe_request(provider, stage, **metadata):
    """可选的请求元数据观察，不传入消息、请求正文或凭据。"""
    callback=getattr(provider,'request_observer',None)
    if not callback:return
    current=getattr(provider,'response_metadata',{})
    usage=current.get('reported_usage') or {}
    safe={key:current.get(key) for key in ('http_status','request_sent','network_attempted','response_type','response_complete',
        'stream_events','content_chars','reasoning_chars','tool_argument_chars','first_event_at','last_event_at','finish_reason')}
    safe.update({key:usage.get(key) for key in ('input_tokens','output_tokens','cached_tokens','estimated')})
    if current.get('http_started_at'):safe['duration_ms']=round((time.time()-current['http_started_at'])*1000)
    try:callback(stage,{**safe,**metadata})
    except Exception as exc:
        raise ProviderError('REQUEST_TRACE_FAILED','请求状态无法持久化，已停止；没有忽略诊断存储错误。') from exc


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
    cached_tokens: int | None = None
    actual_cost: float | None = None


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

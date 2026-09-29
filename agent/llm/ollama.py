from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from agent.llm.base import ModelInfo, ProviderChunk, ToolCall


class OllamaProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable


def parse_model_list(payload: dict[str, Any]) -> list[ModelInfo]:
    result: list[ModelInfo] = []

    for item in payload.get("models") or []:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or item.get("model") or "").strip()
        if not name:
            continue

        details = item.get("details")
        if not isinstance(details, dict):
            details = {}

        size = item.get("size")
        if not isinstance(size, int):
            size = None

        result.append(
            ModelInfo(
                name=name,
                size=size,
                digest=_optional_string(item.get("digest")),
                modified_at=_optional_string(item.get("modified_at")),
                family=_optional_string(details.get("family")),
                parameter_size=_optional_string(details.get("parameter_size")),
                quantization_level=_optional_string(details.get("quantization_level")),
            )
        )

    return sorted(result, key=lambda model: model.name.lower())


def choose_default_model(models: list[ModelInfo], preferred: str) -> str | None:
    names = [model.name for model in models]
    if preferred in names:
        return preferred

    preferred_base = preferred.split(":", 1)[0]
    for name in names:
        if name.split(":", 1)[0] == preferred_base:
            return name

    return names[0] if names else None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_tool_calls(message: dict[str, Any]) -> tuple[ToolCall, ...]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ()

    calls: list[ToolCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                parsed = {}
            arguments = parsed
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(name=name, arguments=arguments))
    return tuple(calls)


class OllamaProvider:
    provider_name = "ollama"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        preferred_model: str | None = None,
        context_window: int | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("LCA_OLLAMA_URL")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        self.preferred_model = (
            preferred_model
            or os.getenv("LCA_OLLAMA_MODEL")
            or "qwen3-coder:30b"
        )
        self.context_window = context_window or int(
            os.getenv("LCA_OLLAMA_NUM_CTX", "32768")
        )
        self.temperature = float(os.getenv("LCA_OLLAMA_TEMPERATURE", "0.2"))

    async def list_models(self) -> list[ModelInfo]:
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.base_url + "/api/tags") as response:
                    payload = await self._read_json_response(response)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OllamaProviderError(
                "OLLAMA_UNAVAILABLE",
                "Cannot connect to Ollama at "
                + self.base_url
                + ". Make sure Ollama is running.",
            ) from exc

        return parse_model_list(payload)

    async def get_status(self) -> dict[str, Any]:
        try:
            models = await self.list_models()
        except OllamaProviderError as exc:
            return {
                "provider": self.provider_name,
                "online": False,
                "base_url": self.base_url,
                "models": [],
                "default_model": None,
                "preferred_model": self.preferred_model,
                "context_window": self.context_window,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                },
            }

        default_model = choose_default_model(models, self.preferred_model)
        return {
            "provider": self.provider_name,
            "online": True,
            "base_url": self.base_url,
            "models": [model.to_dict() for model in models],
            "default_model": default_model,
            "preferred_model": self.preferred_model,
            "context_window": self.context_window,
            "error": None,
        }

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=5,
            sock_read=600,
        )
        request_body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": "10m",
            "options": {
                "num_ctx": self.context_window,
                "temperature": self.temperature,
            },
        }
        if tools:
            request_body["tools"] = tools

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.base_url + "/api/chat",
                    json=request_body,
                ) as response:
                    if response.status >= 400:
                        payload = await self._read_json_response(response)
                        raise OllamaProviderError(
                            "OLLAMA_CHAT_FAILED",
                            str(
                                payload.get("error")
                                or f"Ollama returned HTTP {response.status}."
                            ),
                        )

                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue

                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaProviderError(
                                "OLLAMA_INVALID_STREAM",
                                "Ollama returned invalid streaming JSON.",
                            ) from exc

                        if payload.get("error"):
                            raise OllamaProviderError(
                                "OLLAMA_CHAT_FAILED",
                                str(payload["error"]),
                            )

                        message = payload.get("message")
                        content = ""
                        tool_calls: tuple[ToolCall, ...] = ()
                        if isinstance(message, dict):
                            raw_content = message.get("content")
                            if isinstance(raw_content, str):
                                content = raw_content
                            tool_calls = _parse_tool_calls(message)

                        done = bool(payload.get("done"))
                        yield ProviderChunk(
                            content=content,
                            tool_calls=tool_calls,
                            done=done,
                            finish_reason=_optional_string(
                                payload.get("done_reason")
                            ),
                            prompt_eval_count=_optional_int(
                                payload.get("prompt_eval_count")
                            ),
                            eval_count=_optional_int(payload.get("eval_count")),
                        )
        except OllamaProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OllamaProviderError(
                "OLLAMA_STREAM_FAILED",
                "Ollama connection was interrupted while generating.",
            ) from exc

    async def _read_json_response(
        self,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
            raise OllamaProviderError(
                "OLLAMA_INVALID_RESPONSE",
                "Ollama returned a non-JSON response.",
            ) from exc

        if not isinstance(payload, dict):
            raise OllamaProviderError(
                "OLLAMA_INVALID_RESPONSE",
                "Ollama returned an unexpected response shape.",
            )

        if response.status >= 400:
            raise OllamaProviderError(
                "OLLAMA_REQUEST_FAILED",
                str(
                    payload.get("error")
                    or f"Ollama returned HTTP {response.status}."
                ),
            )

        return payload


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None

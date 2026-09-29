from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from agent.llm.base import ModelInfo, ProviderChunk, ProviderError, ToolCall


class OpenAICompatibleProviderError(ProviderError):
    pass


def parse_model_list(payload: dict[str, Any]) -> list[ModelInfo]:
    result: list[ModelInfo] = []
    data = payload.get("data")
    if not isinstance(data, list):
        return result

    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("id")
        if isinstance(name, str) and name.strip():
            result.append(ModelInfo(name=name.strip()))

    return sorted(result, key=lambda model: model.name.lower())


def choose_default_model(models: list[ModelInfo], preferred: str) -> str | None:
    names = [model.name for model in models]
    if preferred and preferred in names:
        return preferred
    return names[0] if names else (preferred or None)


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _error_message(payload: dict[str, Any], fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(error, str) and error:
        return error
    return fallback


def _finalize_tool_calls(
    states: dict[int, dict[str, str]],
) -> tuple[ToolCall, ...]:
    result: list[ToolCall] = []
    for index in sorted(states):
        state = states[index]
        name = state.get("name", "").strip()
        if not name:
            continue

        raw_arguments = state.get("arguments", "")
        arguments: dict[str, Any] = {}
        if raw_arguments:
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                arguments = parsed

        result.append(
            ToolCall(
                id=state.get("id") or None,
                name=name,
                arguments=arguments,
            )
        )
    return tuple(result)


class OpenAICompatibleProvider:
    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        preferred_model: str | None = None,
        context_window: int | None = None,
        temperature: float | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("LCA_OPENAI_BASE_URL")
            or "http://127.0.0.1:8000/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("LCA_OPENAI_API_KEY", "")
        )
        self.preferred_model = (
            preferred_model
            if preferred_model is not None
            else os.getenv("LCA_OPENAI_MODEL", "")
        ).strip()
        self.context_window = context_window or int(
            os.getenv("LCA_OPENAI_CONTEXT_WINDOW", "32768")
        )
        self.temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("LCA_OPENAI_TEMPERATURE", "0.2"))
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    async def list_models(self) -> list[ModelInfo]:
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self._headers(),
            ) as session:
                async with session.get(self.base_url + "/models") as response:
                    payload = await self._read_json_response(response)
        except OpenAICompatibleProviderError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OpenAICompatibleProviderError(
                "OPENAI_COMPATIBLE_UNAVAILABLE",
                "Cannot connect to the OpenAI-compatible provider at "
                + self.base_url
                + ".",
                transient=True,
            ) from exc

        return parse_model_list(payload)

    async def get_status(self) -> dict[str, Any]:
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return {
                "provider": self.provider_name,
                "online": False,
                "base_url": self.base_url,
                "models": [],
                "default_model": None,
                "preferred_model": self.preferred_model or None,
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
            "preferred_model": self.preferred_model or None,
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
            connect=10,
            sock_read=600,
        )
        request_body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
        }
        if tools:
            request_body["tools"] = tools

        finish_reason: str | None = None
        prompt_eval_count: int | None = None
        eval_count: int | None = None
        tool_states: dict[int, dict[str, str]] = {}
        emitted_done = False

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self._headers(),
            ) as session:
                async with session.post(
                    self.base_url + "/chat/completions",
                    json=request_body,
                ) as response:
                    if response.status >= 400:
                        payload = await self._read_json_response(response)
                        raise self._http_error(
                            response.status,
                            payload,
                            "OpenAI-compatible chat request failed.",
                        )

                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue

                        data = line[5:].strip()
                        if data == "[DONE]":
                            yield ProviderChunk(
                                tool_calls=_finalize_tool_calls(tool_states),
                                done=True,
                                finish_reason=finish_reason,
                                prompt_eval_count=prompt_eval_count,
                                eval_count=eval_count,
                            )
                            emitted_done = True
                            break

                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise OpenAICompatibleProviderError(
                                "OPENAI_COMPATIBLE_INVALID_STREAM",
                                "The OpenAI-compatible provider returned invalid SSE JSON.",
                            ) from exc

                        if not isinstance(payload, dict):
                            continue

                        usage = payload.get("usage")
                        if isinstance(usage, dict):
                            prompt_eval_count = _optional_int(
                                usage.get("prompt_tokens")
                            )
                            eval_count = _optional_int(
                                usage.get("completion_tokens")
                            )

                        choices = payload.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            continue

                        raw_finish_reason = choice.get("finish_reason")
                        if isinstance(raw_finish_reason, str):
                            finish_reason = raw_finish_reason

                        delta = choice.get("delta")
                        if not isinstance(delta, dict):
                            delta = {}

                        content = delta.get("content")
                        if not isinstance(content, str):
                            content = ""

                        raw_calls = delta.get("tool_calls")
                        if isinstance(raw_calls, list):
                            for raw_call in raw_calls:
                                if not isinstance(raw_call, dict):
                                    continue
                                index = raw_call.get("index")
                                if not isinstance(index, int):
                                    index = len(tool_states)
                                state = tool_states.setdefault(
                                    index,
                                    {
                                        "id": "",
                                        "name": "",
                                        "arguments": "",
                                    },
                                )
                                call_id = raw_call.get("id")
                                if isinstance(call_id, str) and call_id:
                                    state["id"] = call_id

                                function = raw_call.get("function")
                                if isinstance(function, dict):
                                    name = function.get("name")
                                    if isinstance(name, str):
                                        state["name"] += name
                                    arguments = function.get("arguments")
                                    if isinstance(arguments, str):
                                        state["arguments"] += arguments

                        if content:
                            yield ProviderChunk(content=content)

            if not emitted_done:
                yield ProviderChunk(
                    tool_calls=_finalize_tool_calls(tool_states),
                    done=True,
                    finish_reason=finish_reason,
                    prompt_eval_count=prompt_eval_count,
                    eval_count=eval_count,
                )
        except OpenAICompatibleProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OpenAICompatibleProviderError(
                "OPENAI_COMPATIBLE_STREAM_FAILED",
                "The OpenAI-compatible connection was interrupted while generating.",
                transient=True,
            ) from exc

    async def _read_json_response(
        self,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
            raise OpenAICompatibleProviderError(
                "OPENAI_COMPATIBLE_INVALID_RESPONSE",
                "The OpenAI-compatible provider returned a non-JSON response.",
            ) from exc

        if not isinstance(payload, dict):
            raise OpenAICompatibleProviderError(
                "OPENAI_COMPATIBLE_INVALID_RESPONSE",
                "The OpenAI-compatible provider returned an unexpected response shape.",
            )

        if response.status >= 400:
            raise self._http_error(
                response.status,
                payload,
                "OpenAI-compatible request failed.",
            )

        return payload

    def _http_error(
        self,
        status: int,
        payload: dict[str, Any],
        fallback: str,
    ) -> OpenAICompatibleProviderError:
        if status in (401, 403):
            code = "OPENAI_COMPATIBLE_AUTH_FAILED"
        elif status == 429:
            code = "OPENAI_COMPATIBLE_RATE_LIMITED"
        else:
            code = "OPENAI_COMPATIBLE_REQUEST_FAILED"

        return OpenAICompatibleProviderError(
            code,
            _error_message(payload, fallback + f" HTTP {status}."),
            recoverable=True,
            transient=status == 429 or status >= 500,
        )

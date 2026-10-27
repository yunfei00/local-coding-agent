from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
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
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def request_image_evidence(messages: list[dict]) -> list[dict]:
    """Non-content evidence of the actual wire images, never URLs or pixels."""
    images = []
    for message in messages:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get('type') != 'image_url':
                continue
            reference = part.get('image_url')
            if not isinstance(reference, dict):
                continue
            url = reference.get('url', '')
            if not isinstance(url, str):
                continue
            header, separator, encoded = url.partition(',')
            if separator and header in {'data:image/jpeg;base64','data:image/png;base64','data:image/webp;base64'}:
                try:
                    pixels = base64.b64decode(encoded, validate=True)
                except ValueError:
                    continue
                images.append({'mime_type':header[5:-7], 'bytes':len(pixels),
                               'sha256':hashlib.sha256(pixels).hexdigest()})
    return images


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
    finish_reason: str | None = None,
    diagnostics: dict | None = None,
) -> tuple[ToolCall, ...]:
    result: list[ToolCall] = []
    for index in sorted(states):
        state = states[index]
        name = state.get("name", "").strip()
        if not name:
            if diagnostics is not None:
                diagnostics.update(tool_parse_success=False, tool_json_error={"index":index, "category":"missing_function_name"})
            raise OpenAICompatibleProviderError("MODEL_INVALID_TOOL_CALL", "Tool call has no function name")

        raw_arguments = state.get("arguments", "")
        arguments: dict[str, Any] = {}
        if raw_arguments:
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                if diagnostics is not None:
                    diagnostics.update(tool_parse_success=False, response_form="invalid_tool_calls", tool_json_error={"index":index,
                        "chars":len(raw_arguments), "position":exc.pos, "line":exc.lineno,
                        "column":exc.colno, "category":exc.msg})
                code = "MODEL_TOOL_ARGUMENTS_TRUNCATED" if finish_reason in {"length", "max_tokens"} else "MODEL_REFUSED" if finish_reason == "content_filter" else "MODEL_INVALID_TOOL_CALL"
                message = ("Model output limit truncated tool arguments; no tool was executed. Retry using smaller code edits within the configured per-request output limit."
                           if code == "MODEL_TOOL_ARGUMENTS_TRUNCATED" else "Tool arguments must be valid JSON; no tool was executed")
                raise OpenAICompatibleProviderError(code, message) from exc
            if not isinstance(parsed, dict):
                if diagnostics is not None:
                    diagnostics.update(tool_parse_success=False, tool_json_error={"index":index, "chars":len(raw_arguments), "category":"not_an_object"})
                raise OpenAICompatibleProviderError("MODEL_INVALID_TOOL_CALL", "Tool arguments must be a JSON object; no tool was executed")
            arguments = parsed

        result.append(
            ToolCall(
                id=state.get("id") or None,
                name=name,
                arguments=arguments,
            )
        )
    if diagnostics is not None:
        diagnostics["tool_parse_success"] = True
    if states and finish_reason in {"length", "max_tokens"}:
        raise OpenAICompatibleProviderError("MODEL_TOOL_ARGUMENTS_TRUNCATED", "Model output ended at its output limit; no tool was executed. Use smaller code edits.")
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
            total=getattr(self, "request_timeout", None),
            connect=10,
            sock_read=600,
        )
        request_body: dict[str, Any] = {
            "model": model,
            "messages": self._wire_messages(messages),
            "stream": True,
            "temperature": self.temperature,
        }
        if getattr(self, "max_output_tokens", None):
            request_body["max_tokens"] = self.max_output_tokens
            request_body["stream_options"] = {"include_usage": True}
        if tools:
            request_body["tools"] = tools

        finish_reason: str | None = None
        prompt_eval_count: int | None = None
        eval_count: int | None = None
        cached_tokens: int | None = None
        actual_cost: float | None = None
        tool_states: dict[int, dict[str, str]] = {}
        emitted_done = False
        self.response_metadata = {"http_status":None, "response_type":None, "request_sent":False, "response_complete":False,
                                  "requested_max_tokens":request_body.get('max_tokens'),
                                  "wire_images":request_image_evidence(request_body['messages']),
                                  "tool_schema_count":len(tools or [])}

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self._headers(),
            ) as session:
                self.response_metadata["request_sent"] = True
                self.response_metadata["http_started_at"] = time.time()
                async with session.post(
                    self.base_url + "/chat/completions",
                    json=request_body,
                ) as response:
                    self.response_metadata.update(http_status=response.status,
                        response_type=response.headers.get("Content-Type", "").split(";")[0][:100])
                    if response.status >= 400:
                        payload = await self._read_json_response(response)
                        raise self._http_error(
                            response.status,
                            payload,
                            "OpenAI-compatible chat request failed.",
                        )

                    async for payload in self._chat_payloads(response):
                        if payload is None:
                            self.response_metadata["response_complete"] = True
                            yield ProviderChunk(
                                tool_calls=_finalize_tool_calls(tool_states, finish_reason, self.response_metadata),
                                done=True,
                                finish_reason=finish_reason,
                                prompt_eval_count=prompt_eval_count,
                                eval_count=eval_count,
                                cached_tokens=cached_tokens, actual_cost=actual_cost,
                            )
                            emitted_done = True
                            break

                        if not isinstance(payload, dict):
                            raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_RESPONSE", "Chat event must be an object")
                        self.response_metadata["parse_success"] = True

                        usage = payload.get("usage")
                        if isinstance(usage, dict):
                            prompt_eval_count = _optional_int(
                                usage.get("prompt_tokens")
                            )
                            eval_count = _optional_int(
                                usage.get("completion_tokens")
                            )

                        if isinstance(usage, dict):
                            details = usage.get("prompt_tokens_details") or {}
                            cached_tokens = _optional_int(details.get("cached_tokens")) if isinstance(details, dict) else None
                            raw_cost = usage.get("cost")
                            if isinstance(raw_cost, (int, float)) and 0 <= raw_cost < float("inf"):
                                actual_cost = raw_cost
                            self.response_metadata["reported_usage"] = {"input_tokens":prompt_eval_count,
                                "output_tokens":eval_count, "cached_tokens":cached_tokens, "actual_cost":actual_cost,
                                "estimated":prompt_eval_count is None or eval_count is None}

                        choices = payload.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            continue

                        raw_finish_reason = choice.get("finish_reason")
                        if isinstance(raw_finish_reason, str):
                            finish_reason = raw_finish_reason
                            self.response_metadata["finish_reason"] = finish_reason[:100]

                        delta = choice.get("delta", choice.get("message"))
                        if not isinstance(delta, dict):
                            delta = {}
                        if delta.get("refusal"):
                            raise OpenAICompatibleProviderError("MODEL_REFUSED", "Provider refused the requested response")

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
                if finish_reason is None:
                    raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INCOMPLETE_STREAM", "Stream ended without a completion marker or finish_reason")
                self.response_metadata["response_complete"] = True
                yield ProviderChunk(
                    tool_calls=_finalize_tool_calls(tool_states, finish_reason, self.response_metadata),
                    done=True,
                    finish_reason=finish_reason,
                    prompt_eval_count=prompt_eval_count,
                    eval_count=eval_count,
                                cached_tokens=cached_tokens, actual_cost=actual_cost,
                )
        except OpenAICompatibleProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            raise OpenAICompatibleProviderError("MODEL_TIMEOUT", "OpenAI-compatible request timed out; usage is uncertain", transient=False) from exc
        except aiohttp.ClientError as exc:
            raise OpenAICompatibleProviderError(
                "OPENAI_COMPATIBLE_STREAM_FAILED",
                "The OpenAI-compatible connection was interrupted while generating.",
                transient=True,
            ) from exc
        finally:
            self.response_metadata["http_ended_at"] = time.time()

    @staticmethod
    def _wire_messages(messages):
        """Keep internal/Ollama arguments as objects; OpenAI requires JSON strings."""
        result = []
        for raw in messages:
            message = {k: v for k, v in raw.items() if k != "tool_name"}
            if raw.get("tool_calls"):
                message["tool_calls"] = []
                for call in raw["tool_calls"]:
                    function = dict(call["function"])
                    if isinstance(function.get("arguments"), dict):
                        function["arguments"] = json.dumps(function["arguments"], ensure_ascii=False)
                    message["tool_calls"].append({**call, "function": function})
            result.append(message)
        return result

    async def _chat_payloads(self, response):
        """aiohttp's line reader reassembles TCP/UTF-8 fragments before SSE parsing."""
        if "application/json" in response.headers.get("Content-Type", ""):
            raw = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                raw.extend(chunk)
                if len(raw) > 8 * 1024 * 1024:
                    raise OpenAICompatibleProviderError("MODEL_OUTPUT_LIMIT", "JSON response exceeds 8 MiB")
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_RESPONSE", "Invalid JSON chat response") from exc
            if not isinstance(value, dict) or not isinstance(value.get("choices"), list) or not value["choices"]:
                raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_RESPONSE", "JSON chat response has no choices")
            yield value
            return
        seen = False
        total = 0
        async for raw_line in response.content:
            total += len(raw_line)
            if total > 8 * 1024 * 1024:
                raise OpenAICompatibleProviderError("MODEL_OUTPUT_LIMIT", "SSE response exceeds 8 MiB")
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeError as exc:
                raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_STREAM", "Invalid UTF-8 in stream") from exc
            if not line or line.startswith(":") or line.startswith(("event:", "id:", "retry:")):
                continue
            if not line.startswith("data:"):
                raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_RESPONSE", "Expected SSE data or an application/json chat response")
            seen = True
            data = line[5:].strip()
            if data == "[DONE]":
                yield None
                return
            try:
                yield json.loads(data)
            except ValueError as exc:
                raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_INVALID_STREAM", "Invalid SSE JSON") from exc
        if not seen:
            raise OpenAICompatibleProviderError("OPENAI_COMPATIBLE_EMPTY_RESPONSE", "Provider returned no chat events")

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
            # Gateways may echo the full request in their error message. Keep
            # diagnostics actionable without persisting that sensitive body.
            fallback + f" HTTP {status} ({code}).",
            recoverable=True,
            transient=status == 429 or status >= 500,
        )

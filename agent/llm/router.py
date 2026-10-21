"""Role routing over existing Providers, with per-task immutable configuration."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import math

from agent.core.budget import validate_limits
from agent.llm.base import ProviderChunk, ProviderError, ToolCall

ROLES = ("planner", "executor", "reviewer", "escalation")
STRATEGIES = ("local-first", "local-only", "api-only")


def validate_config(raw: dict | None = None) -> dict:
    raw = raw or {}
    if set(raw) - {"strategy", "roles", "budget", "verification_commands"}:
        raise ValueError("Unknown orchestration configuration")
    strategy = raw.get("strategy", "local-first")
    if strategy not in STRATEGIES:
        raise ValueError("Invalid model strategy")
    roles = {}
    supplied = raw.get("roles") or {}
    if not isinstance(supplied, dict) or set(supplied) - set(ROLES):
        raise ValueError("Invalid model roles")
    for role in ROLES:
        profile = {"route": "api" if role == "escalation" else "local", "model": "",
                   "context_window": None, "output_limit": 1024, "tool_mode": "auto",
                   "input_price": None, "output_price": None, **supplied.get(role, {})}
        if set(profile) != {"route", "model", "context_window", "output_limit", "tool_mode", "input_price", "output_price"}:
            raise ValueError("Unknown role profile field")
        if profile["route"] not in ("local", "api") or profile["tool_mode"] not in ("auto", "native", "json"):
            raise ValueError("Invalid route or tool mode")
        if not isinstance(profile["model"], str) or len(profile["model"]) > 200:
            raise ValueError("Invalid model name")
        for key, minimum, maximum in (("output_limit", 64, 32768), ("context_window", 1024, 262144)):
            value = profile[key]
            if key == "context_window" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"Invalid {key}")
        for key in ("input_price", "output_price"):
            value = profile[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("Price must be a finite nonnegative amount per million Tokens")
        roles[role] = profile
    commands = raw.get("verification_commands", [])
    if not isinstance(commands, list) or len(commands) > 12 or any(not isinstance(c, str) or not c.strip() or len(c) > 2000 for c in commands):
        raise ValueError("Provide up to 12 nonempty verification commands")
    return {"strategy": strategy, "roles": roles, "budget": validate_limits(raw.get("budget")),
            "verification_commands": commands}


def json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ProviderError("MODEL_INVALID_RESULT", "Model did not return the required structured JSON result") from exc
    if not isinstance(value, dict):
        raise ProviderError("MODEL_INVALID_RESULT", "Expected a JSON object")
    return value


class ModelRouter:
    def __init__(self, config: dict, provider_factory, budget, notify):
        self.config, self.factory, self.budget, self.notify = config, provider_factory, budget, notify

    def resolve(self, role: str):
        profile = dict(self.config["roles"][role])
        strategy = self.config["strategy"]
        route = "local" if strategy == "local-only" else "api" if strategy == "api-only" else profile["route"]
        provider = self.factory(route, profile)
        model = profile["model"] or provider.preferred_model
        if not model:
            raise ProviderError("MODEL_NOT_CONFIGURED", f"Configure the {route} model for {role}")
        return RoutedProvider(provider, model, role, route, profile, self)

    async def text(self, role: str, messages: list[dict]) -> str:
        provider = self.resolve(role)
        parts = []
        async for chunk in provider.stream_chat(model=provider.preferred_model, messages=messages):
            parts.append(chunk.content)
        return "".join(parts)


class RoutedProvider:
    def __init__(self, provider, model, role, route, profile, router):
        self.provider, self.preferred_model, self.role, self.route = provider, model, role, route
        self.profile, self.router = profile, router
        self.provider_name = provider.provider_name
        self.context_window = profile["context_window"] or provider.context_window
        self.provider.context_window = self.context_window
        self.provider.max_output_tokens = profile["output_limit"]
        self.provider.request_timeout = router.config["budget"]["request_seconds"]

    async def stream_chat(self, *, model, messages, tools=None):
        mode = self.profile["tool_mode"]
        if tools and mode == "auto" and hasattr(self.provider, "capabilities"):
            capability = await self.provider.capabilities(model)
            mode = "json" if capability.get("tools") is False else "native"
        fallback = bool(tools and mode == "json")
        if fallback:
            messages = [*messages, {"role": "system", "content": (
                "This model uses JSON tool compatibility. Return ONLY a JSON object: "
                '{"tool_calls":[{"name":"tool_name","arguments":{}}],"content":"summary"}. '
                "For final answer use empty tool_calls. Never claim actions without tool results. Available tools: "
                + json.dumps(tools, ensure_ascii=False))}]
            await self.router.notify("model.compatibility", {"model": model, "mode": "json", "message": "Native tools unavailable; using validated JSON tool compatibility."})
        request_id = self.router.budget.reserve(route=self.route, role=self.role, model=model,
            messages=messages, tools=None if fallback else tools, context_window=self.context_window,
            output_limit=self.profile["output_limit"], input_price=self.profile["input_price"], output_price=self.profile["output_price"])
        usage = {"estimated": True, "actual_cost": None}
        status, text = "uncertain", ""
        try:
            await self.router.notify("model.active", {"role": self.role, "route": self.route, "model": model})
            async with asyncio.timeout(self.router.config["budget"]["request_seconds"]):
                async with aclosing(self.provider.stream_chat(model=model, messages=messages, tools=None if fallback else tools)) as stream:
                    async for chunk in stream:
                        text += chunk.content
                        if len(text) > self.profile["output_limit"] * 32 + 65536:
                            raise ProviderError("MODEL_OUTPUT_LIMIT", "Provider exceeded bounded output size")
                        if chunk.done:
                            usage = {"estimated": chunk.prompt_eval_count is None or chunk.eval_count is None,
                                     "input_tokens": chunk.prompt_eval_count, "output_tokens": chunk.eval_count,
                                     "cached_tokens": getattr(chunk, "cached_tokens", None),
                                     "actual_cost": getattr(chunk, "actual_cost", None)}
                            status = "completed"
                        if not fallback:
                            yield chunk
            if fallback:
                result = json_object(text)
                calls = result.get("tool_calls", [])
                if not isinstance(calls, list) or len(calls) > 12 or any(
                    not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("arguments", {}), dict) for c in calls):
                    raise ProviderError("MODEL_INVALID_RESULT", "Invalid JSON tool calls")
                allowed = {t["function"]["name"] for t in tools}
                if any(c["name"] not in allowed for c in calls):
                    raise ProviderError("MODEL_INVALID_RESULT", "Model requested an unavailable tool")
                yield ProviderChunk(content=str(result.get("content", ""))[:16000],
                    tool_calls=tuple(ToolCall(c["name"], c.get("arguments", {})) for c in calls), done=True)
        except TimeoutError as exc:
            raise ProviderError("MODEL_TIMEOUT", "Model request timed out; reservation retained", transient=False) from exc
        finally:
            self.router.budget.finish(request_id, status, usage)
            await self.router.notify("budget.updated", self.router.budget.runtime.usage(self.router.budget.plan_id))

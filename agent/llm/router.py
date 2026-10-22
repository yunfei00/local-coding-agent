"""Role routing over existing Providers, with per-task immutable configuration."""
from __future__ import annotations

import asyncio
from contextlib import aclosing, suppress
import json
import math
import hashlib

from agent.core.budget import validate_limits
from agent.llm.base import ProviderChunk, ProviderError, ToolCall
from agent.llm.planning import PLAN_TOOL, validate_plan

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
        if set(profile) - {"route", "model", "context_window", "output_limit", "tool_mode", "input_price", "output_price", "model_profile_id"}:
            raise ValueError("Unknown role profile field")
        if "model_profile_id" in profile and (not isinstance(profile["model_profile_id"], str) or len(profile["model_profile_id"]) > 100):
            raise ValueError("Invalid model profile binding")
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


def json_object(text: str, *, require_object=True):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        first, separator, rest = text.partition("\n")
        if separator and first.strip().lower() == "json":
            text = rest.strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ProviderError("MODEL_INVALID_RESULT", "Model did not return the required structured JSON result") from exc
    if require_object and not isinstance(value, dict):
        raise ProviderError("MODEL_INVALID_RESULT", "Expected a JSON object")
    return value


class ModelRouter:
    def __init__(self, config: dict, provider_factory, budget, notify, resolved_roles=None):
        self.config, self.factory, self.budget, self.notify = config, provider_factory, budget, notify
        self.resolved_roles = resolved_roles or config["roles"]

    def resolve(self, role: str):
        profile = dict(self.resolved_roles[role])
        strategy = self.config["strategy"]
        if profile.get("_connection"):
            route = "local" if profile["_connection"]["provider_type"] == "ollama" else "api"
            if (strategy == "local-only" and route != "local") or (strategy == "api-only" and route != "api"):
                error = ProviderError("MODEL_POLICY_MISMATCH", f"{role} binding conflicts with {strategy}; select a compatible profile")
                error.role = role
                raise error
        else:
            # Legacy snapshots retain their original strategy semantics.
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

    async def plan(self, messages):
        provider = self.resolve("planner")
        self.last_plan_call_id = None
        text, calls, finish = "", [], None
        metadata = {"parse_success":None, "schema_valid":None, "schema_errors":[], "representation":"empty"}
        try:
            async for chunk in provider.stream_chat(model=provider.preferred_model, messages=messages, tools=[PLAN_TOOL]):
                text += chunk.content
                if chunk.done:
                    calls = list(chunk.tool_calls)
                    finish = chunk.finish_reason
            metadata.update(parse_success=False, response_chars=len(text), response_fingerprint=hashlib.sha256(
                (text + json.dumps([c.to_dict() if hasattr(c, "to_dict") else {"name":c.name,"arguments":c.arguments} for c in calls], sort_keys=True)).encode()).hexdigest(),
                representation="tool_calls" if calls else "content" if text else "empty")
            if finish in {"length", "max_tokens", "content_filter"}:
                raise ProviderError("PLAN_TRUNCATED" if finish != "content_filter" else "MODEL_REFUSED", "Planner response was truncated or filtered; no plan accepted")
            if calls:
                if len(calls) != 1 or calls[0].name != "submit_plan":
                    raise ProviderError("PLAN_UNEXPECTED_TOOL", "Planner may submit one plan only; execution tools are not allowed")
                value = calls[0].arguments
                if "_raw" in value:
                    raise ProviderError("PLAN_JSON_INVALID", "submit_plan arguments are not a JSON object")
            else:
                if not text.strip():
                    raise ProviderError("PLAN_EMPTY", "Planner returned no plan content or submit_plan arguments")
                try:
                    value = json_object(text, require_object=False)
                except ProviderError as exc:
                    raise ProviderError("PLAN_JSON_INVALID", "Planner content is not a JSON object") from exc
            metadata["parse_success"] = True
            steps = validate_plan(value)
            metadata.update(schema_valid=True, expected_next_state="executing")
            return steps
        except ProviderError as exc:
            metadata.update(error_code=exc.code, failure_reason=exc.code, expected_next_state="paused")
            if exc.code == "PLAN_SCHEMA_INVALID":
                metadata["schema_valid"] = False
                metadata["schema_errors"] = [exc.message]
            raise
        finally:
            self.last_plan_call_id = getattr(provider, "request_id", None)
            if self.last_plan_call_id:
                self.budget.annotate(self.last_plan_call_id, metadata)


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
        if hasattr(self.provider, "response_metadata"):
            self.provider.response_metadata = {"request_sent":False}
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
        self.request_id = request_id
        usage = {"estimated": True, "actual_cost": None}
        status, text, dispatched, finish = "uncertain", "", False, None
        try:
            connection = self.profile.get("_connection", {})
            identity = {"connection_id": connection.get("connection_id"), "provider": connection.get("display_name", self.provider_name),
                        "provider_type": connection.get("provider_type", self.provider_name), "model_profile_id": self.profile.get("model_profile_id")}
            # Extend the existing budget journal; do not create a second request ledger.
            self.router.budget.annotate(request_id, identity)
            await self.router.notify("model.active", {"request_id": request_id, "role": self.role, "route": self.route, "model": model, **identity})
            async with asyncio.timeout(self.router.config["budget"]["request_seconds"]):
                dispatched = True
                async with aclosing(self.provider.stream_chat(model=model, messages=messages, tools=None if fallback else tools)) as stream:
                    async for chunk in stream:
                        text += chunk.content
                        if len(text) > self.profile["output_limit"] * 32 + 65536:
                            raise ProviderError("MODEL_OUTPUT_LIMIT", "Provider exceeded bounded output size")
                        if chunk.done:
                            if len(text) + sum(len(json.dumps(c.arguments, ensure_ascii=False)) for c in chunk.tool_calls) > self.profile["output_limit"] * 32 + 65536:
                                raise ProviderError("MODEL_OUTPUT_LIMIT", "Provider exceeded bounded structured output size")
                            finish = chunk.finish_reason
                            self.router.budget.annotate(request_id, {"finish_reason":chunk.finish_reason,
                                "response_form":"tool_calls" if chunk.tool_calls else "content" if text else "empty"})
                            usage = {"estimated": chunk.prompt_eval_count is None or chunk.eval_count is None,
                                     "input_tokens": chunk.prompt_eval_count, "output_tokens": chunk.eval_count,
                                     "cached_tokens": getattr(chunk, "cached_tokens", None),
                                     "actual_cost": getattr(chunk, "actual_cost", None)}
                            status = "completed"
                        if not fallback:
                            yield chunk
            if fallback:
                result = json_object(text)
                if self.role == "planner" and "steps" in result:
                    yield ProviderChunk(content=text, done=True, finish_reason=finish)
                    return
                calls = result.get("tool_calls", [])
                if not isinstance(calls, list) or len(calls) > 12 or any(
                    not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("arguments", {}), dict) for c in calls):
                    raise ProviderError("MODEL_INVALID_RESULT", "Invalid JSON tool calls")
                allowed = {t["function"]["name"] for t in tools}
                if any(c["name"] not in allowed for c in calls):
                    raise ProviderError("MODEL_INVALID_RESULT", "Model requested an unavailable tool")
                yield ProviderChunk(content=str(result.get("content", ""))[:16000],
                    tool_calls=tuple(ToolCall(c["name"], c.get("arguments", {})) for c in calls), done=True, finish_reason=finish)
        except TimeoutError as exc:
            status = "timeout"
            self.router.budget.annotate(request_id, {"error_code":"MODEL_TIMEOUT", "failure_reason":"request_timeout"})
            raise ProviderError("MODEL_TIMEOUT", "Model request timed out; reservation retained", transient=False) from exc
        except asyncio.CancelledError:
            status = "cancelled"
            self.router.budget.annotate(request_id, {"error_code":"MODEL_CANCELLED", "failure_reason":"user_cancelled_or_paused"})
            raise
        except ProviderError as exc:
            status = "timeout" if exc.code == "MODEL_TIMEOUT" else "failed"
            self.router.budget.annotate(request_id, {"error_code":exc.code, "failure_reason":exc.code})
            raise
        except Exception as exc:
            status = "failed"
            self.router.budget.annotate(request_id, {"error_code":"MODEL_CLIENT_ERROR", "failure_reason":type(exc).__name__})
            raise ProviderError("MODEL_CLIENT_ERROR", "Model client failed; inspect the call metadata") from exc
        finally:
            meta = getattr(self.provider, "response_metadata", {})
            self.router.budget.annotate(request_id, {**meta, "request_dispatched":dispatched})
            if not meta.get("request_sent", dispatched):
                status = "not_sent"
            self.router.budget.finish(request_id, status, usage)
            with suppress(Exception):
                await self.router.notify("budget.updated", self.router.budget.runtime.usage(self.router.budget.plan_id))

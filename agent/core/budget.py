"""Request-time budget reservations. Never refund an uncertain external request."""
from __future__ import annotations

import json
import math
import time
import uuid

from agent.llm.base import ProviderError

DEFAULT_LIMITS = {"api_calls": 3, "api_tokens": 30000, "api_cost": None,
                  "local_repairs": 3, "task_seconds": 1800, "request_seconds": 120,
                  "verification_seconds": 120, "global_api_calls": 30,
                  "global_api_tokens": 300000, "global_api_cost": None}


def validate_limits(raw: dict | None) -> dict:
    values = {**DEFAULT_LIMITS, **(raw or {})}
    if set(values) != set(DEFAULT_LIMITS):
        raise ValueError("Unknown budget setting")
    for key, value in values.items():
        if key.endswith("cost"):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError(f"Invalid {key}")
        elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10**9:
            raise ValueError(f"Invalid {key}")
    for key in ("task_seconds", "request_seconds", "verification_seconds"):
        if not 1 <= values[key] <= 86400:
            raise ValueError(f"{key} must be 1..86400")
    if values["local_repairs"] > 20:
        raise ValueError("local_repairs must be 0..20")
    return values


class BudgetExceeded(ProviderError):
    def __init__(self, message: str):
        super().__init__("BUDGET_EXHAUSTED", message)


class BudgetGuard:
    def __init__(self, runtime, plan_id: str, global_limits: dict):
        self.runtime, self.db, self.plan_id = runtime, runtime.db, plan_id
        self.global_limits = global_limits

    def reserve(self, *, route: str, role: str, model: str, messages: list,
                tools: list | None, context_window: int, output_limit: int,
                input_price: float | None = None, output_price: float | None = None) -> str:
        task = self.runtime.get(self.plan_id)
        limits = task["config"]["budget"]
        elapsed = task["elapsed_seconds"] + (max(0, time.time() - task["active_since"]) if task.get("active_since") else 0)
        if elapsed >= limits["task_seconds"]:
            raise BudgetExceeded("Task execution time exhausted")
        # UTF-8 bytes plus framing overhead deliberately over-reserve ordinary tokenizers.
        input_estimate = len(json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False).encode()) + 256
        tokens = input_estimate + output_limit
        # API accounting stays byte-conservative. Local context fitting reuses the
        # v0.3 character estimator; its accuracy is explicitly approximate.
        context_estimate = tokens if route == "api" else (input_estimate + 3) // 4 + output_limit
        if context_estimate > context_window:
            raise ProviderError("MODEL_CONTEXT_LIMIT", "Conservative request estimate exceeds model context. Reduce context or choose a larger configured window.")
        cost = (input_estimate * (input_price or 0) + output_limit * (output_price or 0)) / 1_000_000
        if not math.isfinite(cost):
            raise BudgetExceeded("Configured prices overflow the request cost estimate")
        if route == "api" and (limits["api_cost"] is not None or self.global_limits["global_api_cost"] is not None):
            if input_price is None or output_price is None:
                raise BudgetExceeded("Cost cap requires configured input and output prices")
        request_id = str(uuid.uuid4())
        # No await between BEGIN and COMMIT. SQLite also serializes other processes.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if route == "api":
                for task_id, call_cap, token_cap, cost_cap in (
                    (self.plan_id, limits["api_calls"], limits["api_tokens"], limits["api_cost"]),
                    (None, self.global_limits["global_api_calls"], self.global_limits["global_api_tokens"], self.global_limits["global_api_cost"]),
                ):
                    used = self.runtime.usage(task_id)
                    if used["api_calls"] + 1 > call_cap or used["reserved_tokens"] + tokens > token_cap:
                        raise BudgetExceeded("API call or Token reservation limit reached; choose local-only, pause, or explicitly add budget")
                    if cost_cap is not None and used["reserved_cost"] + cost > cost_cap:
                        raise BudgetExceeded("API cost reservation limit reached")
            self.db.execute("INSERT INTO model_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (request_id, self.plan_id, route, role, model, tokens if route == "api" else 0,
                             cost if route == "api" else 0, "reserved", json.dumps({"estimated": True,
                             "input_tokens": input_estimate, "output_tokens": output_limit}), time.time()))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return request_id

    def finish(self, request_id: str, status: str, usage: dict) -> None:
        # Settlement is idempotent. Reservations remain charged after restart/cancellation.
        with self.db:
            row = self.db.execute("SELECT * FROM model_requests WHERE id=? AND plan_id=? AND status='reserved'", (request_id, self.plan_id)).fetchone()
            if row is None:
                return
            values = {**json.loads(row["usage_json"]), **{k: v for k, v in usage.items() if v is not None}}
            if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
                values["estimated"] = True
            tokens = max(row["reserved_tokens"], (values.get("input_tokens", 0) + values.get("output_tokens", 0)) if row["route"] == "api" else 0)
            cost = max(row["reserved_cost"], values.get("actual_cost", 0) or 0)
            self.db.execute("UPDATE model_requests SET status=?,usage_json=?,reserved_tokens=?,reserved_cost=? WHERE id=? AND plan_id=? AND status='reserved'",
                            (status, json.dumps(values), tokens, cost, request_id, self.plan_id))

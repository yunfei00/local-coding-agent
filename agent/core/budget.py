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
DEFAULT_LIMITS["planning_attempts"] = 4


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
    if not 1 <= values["planning_attempts"] <= 10:
        raise ValueError("planning_attempts must be 1..10")
    return values


class BudgetExceeded(ProviderError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("BUDGET_EXHAUSTED", message)
        self.details = details
        self.role = details.get("role") if details else None


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
                for scope, task_id, caps in (
                    ("task", self.plan_id, limits),
                    ("global", None, self.global_limits),
                ):
                    used = self.runtime.usage(task_id)
                    prefix = "global_" if scope == "global" else ""
                    for field, usage_key, required in (("api_calls", "api_calls", 1),
                            ("api_tokens", "reserved_tokens", tokens), ("api_cost", "reserved_cost", cost)):
                        key = prefix + field
                        cap = caps[key]
                        if cap is not None and used[usage_key] + required > cap:
                            details = {"task_id":self.plan_id, "attempt_id":request_id, "phase":task["status"],
                                "role":role, "model":model, "route":route, "scope":scope, "field":key,
                                "rule":"used_plus_request_exceeds_limit", "limit":cap, "used":used[usage_key],
                                "required":required, "remaining":max(0, cap - used[usage_key]),
                                "api_calls":used["api_calls"], "reserved_tokens":used["reserved_tokens"],
                                "in_flight_tokens":used["in_flight_tokens"], "reserved_cost":used["reserved_cost"],
                                "input_tokens":used["input_tokens"], "output_tokens":used["output_tokens"],
                                "cached_tokens":used["cached_tokens"], "usage_estimated":used["estimated"],
                                "input_token_estimate":input_estimate, "output_limit":output_limit,
                                "request_token_reservation":tokens, "request_cost_reservation":cost,
                                "task_limits":limits, "global_limits":self.global_limits,
                                "request_sent":False, "checked_at":time.time()}
                            raise BudgetExceeded(
                                f"{scope} budget {key}: used/reserved {used[usage_key]} + request {required} > limit {cap}. "
                                "No API request sent. Review Models and budget and the model output limit; "
                                "new tasks use saved Settings, existing tasks retain snapshots. "
                                "For a paused task, explicitly apply the reviewed configuration or continue local-only.", details)
            self.db.execute("INSERT INTO model_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (request_id, self.plan_id, route, role, model, tokens if route == "api" else 0,
                             cost if route == "api" else 0, "reserved", json.dumps({"estimated": True,
                             "input_tokens": input_estimate, "output_tokens": output_limit,
                             "initial_reserved_tokens":tokens if route == "api" else 0,
                             "task_id":self.plan_id, "call_id":request_id, "sequence":self.db.execute("SELECT COUNT(*) FROM model_requests WHERE plan_id=?", (self.plan_id,)).fetchone()[0] + 1,
                             "phase":task["status"], "retry":max(0, task.get("planning_attempts", 1) - 1) if role == "planner" else 0,
                             "started_at":time.time(), "parse_success":None, "schema_valid":None}), time.time()))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return request_id

    def annotate(self, request_id: str, identity: dict) -> None:
        with self.db:
            row = self.db.execute("SELECT usage_json FROM model_requests WHERE id=? AND plan_id=?", (request_id, self.plan_id)).fetchone()
            if row:
                self.db.execute("UPDATE model_requests SET usage_json=? WHERE id=?", (json.dumps({**json.loads(row[0]), **identity}), request_id))

    def finish(self, request_id: str, status: str, usage: dict) -> None:
        # Settlement is idempotent. Only authoritative, complete usage releases excess.
        with self.db:
            row = self.db.execute("SELECT * FROM model_requests WHERE id=? AND plan_id=? AND status IN ('reserved','interrupted')", (request_id, self.plan_id)).fetchone()
            if row is None:
                return
            values = {**json.loads(row["usage_json"]), **{k: v for k, v in usage.items() if v is not None}}
            if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
                values["estimated"] = True
            actual = (values.get("input_tokens", 0) + values.get("output_tokens", 0)) if row["route"] == "api" else 0
            known = status in {"completed", "failed"} and usage.get("estimated") is False and all(
                isinstance(usage.get(k), int) and not isinstance(usage[k], bool) and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
            tokens = actual if known else max(row["reserved_tokens"], actual)
            cost = max(row["reserved_cost"], values.get("actual_cost", 0) or 0)
            if status == "not_sent":
                tokens, cost = 0, 0
                values.update(input_tokens=0, output_tokens=0, estimated=True)
            values.update(ended_at=time.time(), released_tokens=max(0, row["reserved_tokens"] - tokens),
                          settlement="not_sent_released" if status == "not_sent" else "provider_usage" if known else "conservative_retained")
            self.db.execute("UPDATE model_requests SET status=?,usage_json=?,reserved_tokens=?,reserved_cost=? WHERE id=? AND plan_id=? AND status IN ('reserved','interrupted')",
                            (status, json.dumps(values), tokens, cost, request_id, self.plan_id))

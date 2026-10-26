"""Planner contract shared by prompts, native tools and text compatibility."""
from __future__ import annotations

import json
from agent.llm.base import ProviderError

PLAN_SCHEMA = {"type":"object", "required":["steps"], "properties":{"steps":{
    "type":"array", "minItems":1, "maxItems":30, "items":{"type":"object",
    "required":["description"], "properties":{"description":{"type":"string", "minLength":1, "maxLength":4000},
    "verification":{"type":"string", "maxLength":2000,
        "description":"Empty for file inspection/edit evidence; otherwise a concrete validation command expected to succeed in this step, not a prose assertion."}}}}}}
PLAN_TOOL = {"type":"function", "function":{"name":"submit_plan", "description":"Submit a concrete coding plan; does not execute tools.", "parameters":PLAN_SCHEMA}}
PLAN_PROMPT = ('Return a plan using submit_plan, or ONLY a JSON object matching this schema: '
               + json.dumps(PLAN_SCHEMA) + '. Prefer 1-3 cohesive executable steps covering inspection, implementation, tests and Diff review. '
               'Each step must be finishable with real tools. Set verification to an empty string for inspection/edit steps, '
               'or a concrete command expected to succeed for validation steps. Never require a failing test after the fix, '
               'and do not create a separate prose-only final report step. Never create a baseline-only failing-test step: '
               'combine failure investigation and the fix in one implementation step. '
               'Do not perform actions.')


def validate_plan(value):
    steps = value.get("steps") if isinstance(value, dict) else None
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ProviderError("PLAN_SCHEMA_INVALID", "Schema: steps must be an array with 1..30 items")
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("description"), str) or not 1 <= len(step["description"].strip()) <= 4000:
            raise ProviderError("PLAN_SCHEMA_INVALID", f"Schema: steps[{i}].description must be a nonempty string, max 4000 characters")
        if not isinstance(step.get("verification", ""), str) or len(step.get("verification", "")) > 2000:
            raise ProviderError("PLAN_SCHEMA_INVALID", f"Schema: steps[{i}].verification must be a string, max 2000 characters")
    return steps

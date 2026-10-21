"""Step-local runtime evidence gates for persistent task plans."""
from __future__ import annotations

from typing import Any

COMMAND_TOOLS = frozenset({"shell", "shell_exec", "run_command", "run_shell"})


def verification_passed(
    step_id: str,
    verification: str,
    evidence: list[dict[str, Any]],
    *,
    loop_complete: bool,
) -> bool:
    """Require evidence from the current step, not another step or a prior turn.

    A textual verification requirement requires a successful command execution.
    This does not assert that an arbitrary natural-language acceptance criterion
    was met; that still needs actual output review.
    """
    if not loop_complete:
        return False
    local = [item for item in evidence if item.get("step_id") == step_id]
    if not local or not all(item.get("ok") is True for item in local):
        return False
    if verification.strip():
        return any(item.get("tool") in COMMAND_TOOLS for item in local)
    return True

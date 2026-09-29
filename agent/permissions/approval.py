from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from agent.server.protocol import envelope, new_id


APPROVAL_ALLOW_ONCE = "allow_once"
APPROVAL_ALLOW_TURN = "allow_turn"
APPROVAL_DENY = "deny"
VALID_APPROVAL_DECISIONS = {
    APPROVAL_ALLOW_ONCE,
    APPROVAL_ALLOW_TURN,
    APPROVAL_DENY,
}


@dataclass
class PendingApproval:
    id: str
    turn_id: str
    thread_id: str
    approval_key: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    risk: str
    future: asyncio.Future[str]


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._turn_grants: dict[str, set[str]] = {}

    def is_granted_for_turn(self, turn_id: str, approval_key: str) -> bool:
        return approval_key in self._turn_grants.get(turn_id, set())

    async def request(
        self,
        ws: web.WebSocketResponse,
        *,
        turn_id: str,
        thread_id: str,
        approval_key: str,
        tool_name: str,
        arguments: dict[str, Any],
        reason: str,
        risk: str,
    ) -> str:
        if self.is_granted_for_turn(turn_id, approval_key):
            return APPROVAL_ALLOW_TURN

        loop = asyncio.get_running_loop()
        approval_id = new_id("approval")
        future: asyncio.Future[str] = loop.create_future()
        pending = PendingApproval(
            id=approval_id,
            turn_id=turn_id,
            thread_id=thread_id,
            approval_key=approval_key,
            tool_name=tool_name,
            arguments=dict(arguments),
            reason=reason,
            risk=risk,
            future=future,
        )
        self._pending[approval_id] = pending

        await ws.send_json(
            envelope(
                "approval.requested",
                {
                    "approval_id": approval_id,
                    "tool": tool_name,
                    "arguments": arguments,
                    "reason": reason,
                    "risk": risk,
                },
                thread_id=thread_id,
                turn_id=turn_id,
            )
        )

        try:
            decision = await future
        finally:
            self._pending.pop(approval_id, None)

        if decision == APPROVAL_ALLOW_TURN:
            self._turn_grants.setdefault(turn_id, set()).add(approval_key)

        return decision

    def respond(self, approval_id: str, decision: str) -> PendingApproval | None:
        if decision not in VALID_APPROVAL_DECISIONS:
            raise ValueError(f"Invalid approval decision: {decision}")

        pending = self._pending.get(approval_id)
        if not pending:
            return None

        if not pending.future.done():
            pending.future.set_result(decision)
        return pending

    def cancel_turn(self, turn_id: str) -> None:
        self._turn_grants.pop(turn_id, None)
        for pending in list(self._pending.values()):
            if pending.turn_id == turn_id and not pending.future.done():
                pending.future.cancel()

    def finish_turn(self, turn_id: str) -> None:
        self.cancel_turn(turn_id)

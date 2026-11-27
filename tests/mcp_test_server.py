from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.mcpserver import MCPServer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(root: Path, value: str) -> Path:
    target = (root / value).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError(f"path escapes test root: {value}")
    return target


def build_server(root: Path) -> MCPServer:
    root.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    lock = asyncio.Lock()

    async def record(entry: dict[str, Any]) -> None:
        async with lock:
            history.append(entry)

    async def update(request_id: str, **fields: Any) -> None:
        async with lock:
            for item in reversed(history):
                if item.get("request_id") == request_id:
                    item.update(fields)
                    return

    server = MCPServer("lca-mcp-test-server", version="1.0.0")

    @server.tool()
    async def ping() -> dict[str, Any]:
        """Test MCP connectivity."""
        rid = uuid4().hex
        started = time.time()
        entry = {"request_id": rid, "tool": "ping", "called_at": _now(), "started_at": _now(), "status": "running", "side_effects": []}
        await record(entry)
        result = {"ok": True, "pong": True, "server": "lca-mcp-test-server"}
        await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result)
        return result

    @server.tool()
    async def echo(text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Echo arguments back for parameter passing tests."""
        rid = uuid4().hex
        started = time.time()
        await record({"request_id": rid, "tool": "echo", "called_at": _now(), "started_at": _now(), "status": "running", "arguments": {"text": text, "extra": extra}, "side_effects": []})
        result = {"ok": True, "text": text, "extra": extra}
        await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result)
        return result

    @server.tool()
    async def read_file(path: str) -> dict[str, Any]:
        """Read a file inside the isolated test root."""
        rid = uuid4().hex
        started = time.time()
        await record({"request_id": rid, "tool": "read_file", "called_at": _now(), "started_at": _now(), "status": "running", "arguments": {"path": path}, "side_effects": []})
        try:
            target = _safe(root, path)
            content = target.read_text(encoding="utf-8")
            result = {"ok": True, "path": path, "content": content}
            await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result, side_effects=[{"type": "read", "path": str(target)}])
            return result
        except Exception as exc:
            await update(rid, ended_at=_now(), status="failed", duration_ms=int((time.time()-started)*1000), error=str(exc))
            raise

    @server.tool()
    async def write_file(path: str, content: str) -> dict[str, Any]:
        """Write a file inside the isolated test root."""
        rid = uuid4().hex
        started = time.time()
        await record({"request_id": rid, "tool": "write_file", "called_at": _now(), "started_at": _now(), "status": "running", "arguments": {"path": path, "content_len": len(content)}, "side_effects": []})
        try:
            target = _safe(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result = {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}
            await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result, side_effects=[{"type": "write", "path": str(target), "bytes": result["bytes"]}])
            return result
        except Exception as exc:
            await update(rid, ended_at=_now(), status="failed", duration_ms=int((time.time()-started)*1000), error=str(exc))
            raise

    @server.tool()
    async def delete_file(path: str) -> dict[str, Any]:
        """Delete a file inside the isolated test root."""
        rid = uuid4().hex
        started = time.time()
        await record({"request_id": rid, "tool": "delete_file", "called_at": _now(), "started_at": _now(), "status": "running", "arguments": {"path": path}, "side_effects": []})
        try:
            target = _safe(root, path)
            existed = target.exists()
            if existed:
                target.unlink()
            result = {"ok": True, "path": path, "existed": existed}
            await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result, side_effects=[{"type": "delete", "path": str(target), "existed": existed}])
            return result
        except Exception as exc:
            await update(rid, ended_at=_now(), status="failed", duration_ms=int((time.time()-started)*1000), error=str(exc))
            raise

    @server.tool()
    async def long_running(seconds: float = 30.0, tick_ms: int = 200) -> dict[str, Any]:
        """Run for a long time; supports cancellation."""
        rid = uuid4().hex
        started = time.time()
        await record({"request_id": rid, "tool": "long_running", "called_at": _now(), "started_at": _now(), "status": "running", "arguments": {"seconds": seconds, "tick_ms": tick_ms}, "side_effects": []})
        ticks = 0
        try:
            deadline = time.time() + max(0.0, float(seconds))
            interval = max(0.05, tick_ms / 1000.0)
            while time.time() < deadline:
                await asyncio.sleep(interval)
                ticks += 1
            result = {"ok": True, "ticks": ticks, "completed": True}
            await update(rid, ended_at=_now(), status="completed", duration_ms=int((time.time()-started)*1000), result=result)
            return result
        except asyncio.CancelledError:
            await update(rid, ended_at=_now(), cancelled_at=_now(), status="cancelled", duration_ms=int((time.time()-started)*1000), side_effects=[{"type": "cancelled", "ticks": ticks}])
            raise
        except Exception as exc:
            await update(rid, ended_at=_now(), status="failed", duration_ms=int((time.time()-started)*1000), error=str(exc))
            raise

    @server.tool()
    async def get_call_history() -> dict[str, Any]:
        """Return recorded call history for test assertions."""
        async with lock:
            return {"ok": True, "root": str(root), "history": list(history)}

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="LCA MCP test server")
    parser.add_argument("--root", default=os.environ.get("LCA_MCP_TEST_ROOT") or str(Path.cwd() / ".mcp-test-root"))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    server = build_server(root)
    server.run("stdio")


if __name__ == "__main__":
    main()

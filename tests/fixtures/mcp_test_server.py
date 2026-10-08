from __future__ import annotations

import argparse

from mcp.server import MCPServer
from mcp.types import ToolAnnotations


mcp = MCPServer("LCA MCP Test Server")


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def echo(message: str) -> dict[str, str]:
    """Echo a message."""
    return {"message": message}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def large_text(size: int = 10000) -> str:
    """Return deterministic large text for truncation tests."""
    size = max(0, min(int(size), 200000))
    return "x" * size


@mcp.resource("test://local/greeting")
def greeting() -> str:
    """Return a small deterministic resource."""
    return "hello from mcp resource"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    if args.http:
        if args.port <= 0:
            raise SystemExit("--port is required for HTTP mode")
        mcp.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()

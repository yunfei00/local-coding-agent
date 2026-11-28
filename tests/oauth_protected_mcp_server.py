from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer

try:
    from tests.oauth_mcp_fixture import LocalOAuthProvider, OAuthState
except Exception:
    from oauth_mcp_fixture import LocalOAuthProvider, OAuthState


def build_state(path: Path | None) -> OAuthState:
    if path and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = OAuthState()
        state.user = raw.get("user", state.user)
        state.password = raw.get("password", state.password)
        state.revoked_access = set(raw.get("revoked_access", []))
        state.revoked_refresh = set(raw.get("revoked_refresh", []))
        return state
    return OAuthState()


def persist_state(state: OAuthState, path: Path | None) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "user": state.user,
        "password": state.password,
        "revoked_access": sorted(state.revoked_access),
        "revoked_refresh": sorted(state.revoked_refresh),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def create_app(host: str, port: int, state_path: Path | None = None):
    issuer = f"http://{host}:{port}"
    state = build_state(state_path)
    provider = LocalOAuthProvider(issuer=issuer, state=state, persist_cb=lambda: persist_state(state, state_path))

    server = MCPServer(
        "lca-oauth-mcp-test",
        version="1.0.0",
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(f"{issuer}/mcp"),
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp:tools"], default_scopes=["mcp:tools"]),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=["mcp:tools"],
            validate_token_resource=False,
        ),
    )

    @server.tool()
    async def whoami() -> dict:
        """Return the authenticated test user."""
        return {"ok": True, "user": provider.state.user}

    @server.tool()
    async def echo(text: str) -> dict:
        """Echo text back."""
        return {"ok": True, "text": text}

    @server.tool()
    async def ping() -> dict:
        """Ping."""
        return {"ok": True, "pong": True}

    mcp_app = server.streamable_http_app()
    # Add custom login routes to the MCP app's router
    for route in provider.login_routes():
        mcp_app.routes.append(route)

    mcp_app.state.oauth_provider = provider
    mcp_app.state.oauth_state_path = state_path
    mcp_app.state.persist_oauth_state = lambda: persist_state(provider.state, state_path)

    old_lifespan = mcp_app.router.lifespan_context
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        async with old_lifespan(app):
            yield
        persist_state(provider.state, state_path)

    mcp_app.router.lifespan_context = lifespan
    return mcp_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-file", default="")
    args = parser.parse_args()
    state_path = Path(args.state_file).resolve() if args.state_file else None
    app = create_app(args.host, args.port, state_path)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

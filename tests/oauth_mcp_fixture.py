from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from pydantic import AnyHttpUrl, AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    OAuthClientInformationFull,
    OAuthToken,
    RefreshToken,
    TokenVerifier,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions


def _now() -> int:
    return int(time.time())


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class OAuthState:
    clients: dict[str, OAuthClientInformationFull] = field(default_factory=dict)
    codes: dict[str, AuthorizationCode] = field(default_factory=dict)
    access_tokens: dict[str, AccessToken] = field(default_factory=dict)
    refresh_tokens: dict[str, RefreshToken] = field(default_factory=dict)
    revoked_access: set[str] = field(default_factory=set)
    revoked_refresh: set[str] = field(default_factory=set)
    user: str = "test-user"
    password: str = "test-password"


class LocalOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken], TokenVerifier):
    def __init__(self, issuer: str, secret: str = "lca-oauth-test-secret-secret-32bytes!", state: OAuthState | None = None, persist_cb=None):
        self.issuer = issuer.rstrip("/")
        self.secret = secret
        self.state = state or OAuthState()
        self.persist_cb = persist_cb

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.state.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.state.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # Real authorization endpoint is mounted separately; return URL to it.
        q = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "state": params.state or "",
            "scope": " ".join(params.scopes or []),
            "resource": params.resource or "",
            "redirect_uri_provided_explicitly": "1" if params.redirect_uri_provided_explicitly else "0",
        }
        return self.issuer + "/oauth/login?" + urlencode(q)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        code = self.state.codes.get(authorization_code)
        if not code or code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            self.state.codes.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        self.state.codes.pop(authorization_code.code, None)
        return self._issue_tokens(client.client_id, authorization_code.scopes, authorization_code.resource, authorization_code.subject)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        rt = self.state.refresh_tokens.get(refresh_token)
        if not rt or rt.client_id != client.client_id:
            return None
        if refresh_token in self.state.revoked_refresh:
            return None
        if rt.expires_at and rt.expires_at < _now():
            return None
        return rt

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        self.state.revoked_refresh.add(refresh_token.token)
        self.state.refresh_tokens.pop(refresh_token.token, None)
        use_scopes = scopes or refresh_token.scopes
        return self._issue_tokens(client.client_id, use_scopes, refresh_token.resource, refresh_token.subject)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.state.revoked_access.add(token.token)
            self.state.access_tokens.pop(token.token, None)
        else:
            self.state.revoked_refresh.add(token.token)
            self.state.refresh_tokens.pop(token.token, None)
        if self.persist_cb:
            try:
                self.persist_cb()
            except Exception:
                pass

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self.verify_token(token)

    async def verify_token(self, token: str) -> AccessToken | None:
        if token in self.state.revoked_access:
            return None
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        except Exception:
            return None
        if payload.get("iss") != self.issuer:
            return None
        at = AccessToken(
            token=token,
            client_id=str(payload.get("client_id") or ""),
            scopes=list((payload.get("scope") or "").split()),
            expires_at=int(payload.get("exp")) if payload.get("exp") else None,
            resource=payload.get("resource"),
            subject=str(payload.get("sub") or ""),
            claims=payload,
        )
        self.state.access_tokens[token] = at
        return at

    def _issue_tokens(self, client_id: str, scopes: list[str], resource: str | None, subject: str | None) -> OAuthToken:
        sub = subject or self.state.user
        now = _now()
        access_claims = {
            "iss": self.issuer,
            "sub": sub,
            "client_id": client_id,
            "scope": " ".join(scopes),
            "iat": now,
            "exp": now + 300,
            "jti": secrets.token_urlsafe(16),
        }
        if resource:
            access_claims["resource"] = resource
        access = jwt.encode(access_claims, self.secret, algorithm="HS256")
        refresh = "rt_" + secrets.token_urlsafe(32)
        self.state.access_tokens[access] = AccessToken(token=access, client_id=client_id, scopes=scopes, expires_at=now + 300, resource=resource, subject=sub)
        self.state.refresh_tokens[refresh] = RefreshToken(token=refresh, client_id=client_id, scopes=scopes, expires_at=now + 3600, resource=resource, subject=sub)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=300, scope=" ".join(scopes), refresh_token=refresh)

    def login_routes(self) -> list[Route]:
        provider = self

        async def login_get(request: Request) -> Response:
            q = dict(request.query_params)
            return HTMLResponse(
                "<html><body><form method='post' action='/oauth/login/callback'>"
                + "".join(f"<input type='hidden' name='{k}' value='{v}'/>" for k, v in q.items())
                + "user:<input name='username'/>pass:<input name='password' type='password'/>"
                + "<button type='submit'>Login</button></form></body></html>"
            )

        async def login_post(request: Request) -> Response:
            form = await request.form()
            q = {k: str(v) for k, v in form.items()}
            if q.get("username") != provider.state.user or q.get("password") != provider.state.password:
                return HTMLResponse("unauthorized", status_code=401)
            client_id = q.get("client_id", "")
            client = provider.state.clients.get(client_id)
            if not client:
                return HTMLResponse("unknown client", status_code=400)
            code = "ac_" + secrets.token_urlsafe(24)
            redirect_uri = q.get("redirect_uri", "")
            scopes = [s for s in (q.get("scope", "").split()) if s]
            ac = AuthorizationCode(
                code=code,
                scopes=scopes,
                expires_at=time.time() + 300,
                client_id=client_id,
                code_challenge=q.get("code_challenge", ""),
                redirect_uri=AnyUrl(redirect_uri),
                redirect_uri_provided_explicitly=q.get("redirect_uri_provided_explicitly") == "1",
                resource=q.get("resource") or None,
                subject=provider.state.user,
            )
            provider.state.codes[code] = ac
            redirect = construct_redirect_uri(redirect_uri, code=code, state=q.get("state") or None)
            return RedirectResponse(redirect, status_code=302)

        return [Route("/oauth/login", login_get, methods=["GET"]), Route("/oauth/login/callback", login_post, methods=["POST"])]

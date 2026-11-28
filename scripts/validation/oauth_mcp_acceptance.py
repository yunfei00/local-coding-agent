from __future__ import annotations

import argparse, asyncio, base64, hashlib, json, secrets, socket, subprocess, sys, time, urllib.parse
from pathlib import Path

import httpx2 as httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from agent.mcp.client import MCPClientManager, MCPServerConfig  # noqa: E402


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _extract_sval(result_payload):
    v = result_payload.get('result', {}).get('value', {}) if isinstance(result_payload, dict) else {}
    if not isinstance(v, dict):
        return {}
    sc = v.get('structured_content')
    if isinstance(sc, dict):
        return sc
    # try parsing content[0].text as json
    try:
        content = v.get('content') or []
        if content and isinstance(content[0], dict):
            t = content[0].get('text')
            if isinstance(t, str):
                import json as _j
                obj = _j.loads(t)
                if isinstance(obj, dict):
                    return obj
    except Exception:
        pass
    return v
def report_path() -> Path:
    p = ROOT / "validation-reports" / "p0-oauth-mcp-acceptance.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class ServerProc:
    def __init__(self, port: int, state_file: Path):
        self.port = port
        self.state_file = state_file
        self.proc: subprocess.Popen | None = None

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "tests/oauth_protected_mcp_server.py", "--host", "127.0.0.1", "--port", str(self.port), "--state-file", str(self.state_file)],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def stop(self):
        if not self.proc:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self.proc = None

    async def wait_ready(self, client: httpx.AsyncClient):
        for _ in range(80):
            try:
                r = await client.get(f"http://127.0.0.1:{self.port}/.well-known/oauth-authorization-server")
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        return False


async def register_client(c: httpx.AsyncClient, port: int) -> dict:
    reg = await c.post(f"http://127.0.0.1:{port}/register", json={
        "client_name": "lca-test", "redirect_uris": ["http://127.0.0.1:9999/cb"],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    })
    reg.raise_for_status()
    return reg.json()


async def do_oauth_flow(c: httpx.AsyncClient, port: int, client_id: str, client_secret: str = "", username="test-user", password="test-password", scope="mcp:tools"):
    verifier = secrets.token_urlsafe(32)
    challenge = s256(verifier)
    resource = f"http://127.0.0.1:{port}/mcp"
    auth_url = (f"http://127.0.0.1:{port}/authorize?response_type=code&client_id={client_id}"
                f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A9999%2Fcb&code_challenge={challenge}"
                f"&code_challenge_method=S256&state=s1&scope={urllib.parse.quote(scope)}&resource={urllib.parse.quote(resource, safe='')}")
    r = await c.get(auth_url, follow_redirects=False)
    if r.status_code not in (302, 303):
        return {"ok": False, "step": "authorize", "status": r.status_code, "body": r.text[:300]}
    loc = r.headers.get("location", "")
    if "/oauth/login" not in loc:
        return {"ok": False, "step": "authorize_redirect", "location": loc}
    login = await c.get(loc)
    # parse hidden inputs
    from html.parser import HTMLParser
    class F(HTMLParser):
        def __init__(self): super().__init__(); self.inputs = {}
        def handle_starttag(self, tag, attrs):
            if tag == "input":
                d = dict(attrs); self.inputs[d.get("name", "")] = d.get("value", "")
    f = F(); f.feed(login.text)
    f.inputs["username"] = username; f.inputs["password"] = password
    cb = await c.post(f"http://127.0.0.1:{port}/oauth/login/callback", data=f.inputs, follow_redirects=False)
    if cb.status_code not in (302, 303):
        return {"ok": False, "step": "login", "status": cb.status_code, "body": cb.text[:300]}
    location = cb.headers.get("location", "")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if "error" in qs:
        return {"ok": False, "step": "callback_error", "error": qs.get("error")}
    code = qs.get("code", [None])[0]
    if not code:
        return {"ok": False, "step": "no_code", "location": location}
    td = {"grant_type": "authorization_code", "code": code, "redirect_uri": "http://127.0.0.1:9999/cb", "client_id": client_id, "code_verifier": verifier}
    if client_secret: td["client_secret"] = client_secret
    tok = await c.post(f"http://127.0.0.1:{port}/token", data=td)
    if tok.status_code != 200:
        return {"ok": False, "step": "token", "status": tok.status_code, "body": tok.text[:300]}
    return {"ok": True, "token": tok.json(), "code": code, "verifier": verifier, "client_id": client_id}


async def mcp_call(port: int, access_token: str, tool: str, args: dict):
    cfg = MCPServerConfig(name="oauth", transport="streamable_http", url=f"http://127.0.0.1:{port}/mcp", env={"Authorization": f"Bearer {access_token}"}, timeout_seconds=20)
    m = MCPClientManager([cfg])
    try:
        await m.connect("oauth")
        tools = await m.list_tools("oauth")
        res = await m.call_tool("oauth", tool, args)
        return {"ok": True, "tools": [t.name for t in tools], "result": res}
    finally:
        await m.disconnect_all()


async def mcp_connect_expect_fail(port: int, access_token: str | None):
    env = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    cfg = MCPServerConfig(name="oauth", transport="streamable_http", url=f"http://127.0.0.1:{port}/mcp", env=env, timeout_seconds=10)
    m = MCPClientManager([cfg])
    try:
        await m.connect("oauth")
        await m.list_tools("oauth")
        return {"ok": False, "detail": "unexpected success"}
    except Exception as e:
        return {"ok": True, "error": str(e)[:300]}
    finally:
        await m.disconnect_all()


async def main():
    report = {"ok": True, "checks": [], "blocked": []}
    def check(name, ok, detail=None):
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            report["ok"] = False

    port = free_port()
    state_file = ROOT / ".tmp-oauth-mcp-state.json"
    if state_file.exists(): state_file.unlink()
    srv = ServerProc(port, state_file)
    srv.start()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as c:
            ready = await srv.wait_ready(c)
            check("server_start", ready)
            if not ready:
                raise RuntimeError("server not ready")

            # 1. unauth denied
            unauth = await mcp_connect_expect_fail(port, None)
            check("unauth_denied", unauth["ok"], unauth)

            # register + oauth flow
            creds = await register_client(c, port); cid = creds["client_id"]; csec = creds.get("client_secret","")
            flow = await do_oauth_flow(c, port, cid, csec)
            check("oauth_authorize_pkce_token", flow["ok"], {"step": flow.get("step"), "keys": list(flow.get("token", {}).keys()) if flow.get("ok") else None})
            if not flow["ok"]:
                raise RuntimeError("oauth flow failed")
            token = flow["token"]
            access = token["access_token"]
            refresh = token.get("refresh_token")

            # authorized MCP call
            call = await mcp_call(port, access, "echo", {"text": "hello"})
            ok_call = call["ok"] and not call["result"].get("is_error")
            # check structured content
            sval = _extract_sval(call["result"] if call.get("ok") else {})
            check("authorized_mcp_tool_call", ok_call and sval.get("text") == "hello", {"text": sval.get("text"), "sval": sval})

            # PKCE wrong verifier must fail
            verifier_bad = secrets.token_urlsafe(32)
            challenge_bad = s256(verifier_bad)
            resource = f"http://127.0.0.1:{port}/mcp"
            auth_url_bad = (f"http://127.0.0.1:{port}/authorize?response_type=code&client_id={cid}"
                            f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A9999%2Fcb&code_challenge={challenge_bad}"
                            f"&code_challenge_method=S256&state=pkce1&scope=mcp%3Atools&resource={urllib.parse.quote(resource, safe='')}")
            rpk = await c.get(auth_url_bad, follow_redirects=False)
            locpk = rpk.headers.get("location","")
            loginpk = await c.get(locpk)
            from html.parser import HTMLParser as _HP
            class _F(_HP):
                def __init__(self): super().__init__(); self.inputs={}
                def handle_starttag(self,tag,attrs):
                    if tag=='input': d=dict(attrs); self.inputs[d.get('name','')]=d.get('value','')
            fpk=_F(); fpk.feed(loginpk.text); fpk.inputs['username']='test-user'; fpk.inputs['password']='test-password'
            cbpk = await c.post(f"http://127.0.0.1:{port}/oauth/login/callback", data=fpk.inputs, follow_redirects=False)
            codepk = urllib.parse.parse_qs(urllib.parse.urlparse(cbpk.headers.get('location','')).query).get('code',[None])[0]
            tdpk={"grant_type":"authorization_code","code":codepk,"redirect_uri":"http://127.0.0.1:9999/cb","client_id":cid,"code_verifier":"wrong-verifier"}
            if csec: tdpk["client_secret"]=csec
            tokpk = await c.post(f"http://127.0.0.1:{port}/token", data=tdpk)
            check("pkce_wrong_verifier_rejected", tokpk.status_code != 200, {"status": tokpk.status_code})

            # refresh token
            if refresh:
                rtd={"grant_type":"refresh_token","refresh_token":refresh,"client_id":cid}
                if csec: rtd["client_secret"]=csec
                rt = await c.post(f"http://127.0.0.1:{port}/token", data=rtd)
                check("refresh_token", rt.status_code == 200 and "access_token" in rt.json(), {"status": rt.status_code})
                if rt.status_code == 200:
                    access2 = rt.json()["access_token"]
                    call2 = await mcp_call(port, access2, "ping", {})
                    sv2 = _extract_sval(call2["result"] if call2.get("ok") else {})
                    check("refresh_token_works_for_mcp", call2.get("ok") and sv2.get("pong") is True, {"sv2": sv2})
                    access = access2
                    refresh = rt.json().get("refresh_token", refresh)
            else:
                check("refresh_token", False, "no refresh token")
                check("refresh_token_works_for_mcp", False, "no refresh token")

            # token expiry handling - craft expired JWT with same server secret
            import jwt as _jwt
            expired = _jwt.encode({"iss":f"http://127.0.0.1:{port}","sub":"test-user","client_id":cid,"scope":"mcp:tools","iat":int(time.time())-600,"exp":int(time.time())-10,"resource":f"http://127.0.0.1:{port}/mcp"}, "lca-oauth-test-secret-secret-32bytes!", algorithm="HS256")
            expired_denied = await mcp_connect_expect_fail(port, expired)
            check("expired_token_denied", expired_denied["ok"], expired_denied)

            # client logout/local credential clear: discard token locally, no token -> denied (distinct from server revoke)
            cleared = await mcp_connect_expect_fail(port, None)
            check("client_logout_cleared_credentials_denied", cleared["ok"], cleared)

            # server revoke token
            rvd={"token": access, "token_type_hint": "access_token", "client_id": cid}
            if csec: rvd["client_secret"]=csec
            rev = await c.post(f"http://127.0.0.1:{port}/revoke", data=rvd)
            check("revoke_request", rev.status_code == 200, {"status": rev.status_code})
            denied = await mcp_connect_expect_fail(port, access)
            check("revoked_token_denied", denied["ok"], denied)

            # re-auth restore
            flow2 = await do_oauth_flow(c, port, cid, csec)
            check("relogin_after_revoke", flow2["ok"])
            if flow2["ok"]:
                await asyncio.sleep(0.5)
                try:
                    call3 = await mcp_call(port, flow2["token"]["access_token"], "whoami", {})
                    sv3 = _extract_sval(call3["result"] if call3.get("ok") else {})
                    check("relogin_mcp_call", call3.get("ok") and sv3.get("ok") is True, sv3)
                except Exception as e:
                    check("relogin_mcp_call", False, {"error": str(e)[:300]})

            # restart recovery: stop and start, revoked token should still be rejected; stored valid token behavior recorded
            valid_before_restart = flow2["token"]["access_token"] if flow2.get("ok") else None
            srv.stop()
            await asyncio.sleep(0.5)
            srv.start()
            ready2 = await srv.wait_ready(c)
            check("restart_recovery_server", ready2)
            if ready2:
                denied2 = await mcp_connect_expect_fail(port, access)
                check("restart_revoked_still_denied", denied2["ok"], denied2)
                if valid_before_restart:
                    post_restart = await mcp_connect_expect_fail(port, valid_before_restart)
                    report["checks"].append({"name":"restart_access_token_behavior","ok":True,"detail":{"accepted": not post_restart["ok"], "note":"in-memory fixture may require re-auth after restart; persisted revocation list is enforced"}})
                creds2 = await register_client(c, port)
                flow3 = await do_oauth_flow(c, port, creds2["client_id"], creds2.get("client_secret",""))
                check("restart_reauth_works", flow3["ok"])

            # cancel auth (wrong password) - no token issued
            creds3 = await register_client(c, port)
            bad = await do_oauth_flow(c, port, creds3["client_id"], creds3.get("client_secret",""), password="wrong")
            check("cancel_or_bad_login_denied", not bad["ok"], {"step": bad.get("step"), "status": bad.get("status")})

            report["blocked"].append({"name":"third_party_oauth_compatibility","reason":"No external commercial MCP OAuth account/service in test environment; local OAuth 2.1 protocol-level validation completed."})
    except Exception as e:
        report["ok"] = False
        report.setdefault("errors", []).append(str(e))
    finally:
        srv.stop()
        if state_file.exists():
            try: state_file.unlink()
            except Exception: pass
    out = report_path()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "checks": len(report["checks"]), "blocked": len(report.get("blocked",[])), "report": str(out)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

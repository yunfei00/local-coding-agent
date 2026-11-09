"""Restricted Playwright browser sessions for interactive public web workflows.

Each session owns a browser process. All requests are restricted to the original
public hostname, and DNS is checked on each request. Page text is untrusted.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import secrets
from urllib.parse import urlparse
from agent.browser.engine import validate_url

MAX_TEXT = 50000
MAX_SESSIONS = 3

@dataclass
class Session:
    browser: object
    context: object
    page: object
    hostname: str

class BrowserSessions:
    def __init__(self):
        self._sessions: dict[str,Session] = {}
        self._lock = asyncio.Lock()

    async def open(self, url: str) -> dict:
        validate_url(url)
        from playwright.async_api import async_playwright
        async with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise ValueError("Too many browser sessions")
            # Start the Playwright driver for the entire lifetime of this session.
            driver = await async_playwright().start()
            browser = None
            try:
                browser = await driver.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=False, service_workers="block")
                page = await context.new_page()
                hostname = urlparse(url).hostname
                async def guard(route):
                    request_url = route.request.url
                    if urlparse(request_url).hostname != hostname:
                        await route.abort()
                        return
                    try:
                        validate_url(request_url)
                    except (OSError, ValueError):
                        await route.abort()
                        return
                    await route.continue_()
                await context.route("**/*", guard)
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                session_id = secrets.token_hex(12)
                session = Session(browser,context,page,hostname)
                session.driver = driver
                self._sessions[session_id] = session
                return {"session_id":session_id, **await self.snapshot(session_id)}
            except BaseException:
                if browser:
                    await browser.close()
                await driver.stop()
                raise

    def _get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise ValueError("Unknown or closed browser session")
        return self._sessions[session_id]

    async def snapshot(self, session_id: str) -> dict:
        s = self._get(session_id)
        page = s.page
        if urlparse(page.url).hostname != s.hostname:
            raise ValueError("Browser navigated outside the approved hostname")
        return {
            "url":page.url,
            "title":await page.title(),
            "text":(await page.locator("body").inner_text(timeout=10000))[:MAX_TEXT],
            "elements":await page.locator("a,button,input,textarea,select").evaluate_all(
                """nodes => nodes.slice(0,100).map((n,i)=>({
                  index:i,tag:n.tagName.toLowerCase(),text:(n.innerText||n.value||'').slice(0,160),
                  role:n.getAttribute('role'),aria_label:n.getAttribute('aria-label'),
                  placeholder:n.getAttribute('placeholder'),type:n.getAttribute('type')
                }))"""
            )
        }

    async def action(self, session_id: str, operation: str, *, selector: str="", value: str="") -> dict:
        s = self._get(session_id)
        if operation not in {"click","fill","select","check","uncheck","press","navigate","wait"}:
            raise ValueError("Unsupported browser action")
        if operation == "navigate":
            validate_url(value)
            if urlparse(value).hostname != s.hostname:
                raise ValueError("Cross-host navigation is blocked")
            await s.page.goto(value,wait_until="domcontentloaded",timeout=15000)
        elif operation == "wait":
            await s.page.wait_for_load_state("domcontentloaded",timeout=10000)
        else:
            if not selector or len(selector)>1000 or len(value)>10000:
                raise ValueError("Invalid selector or value")
            locator=s.page.locator(selector)
            if await locator.count()!=1:
                raise ValueError("Selector must match exactly one element")
            if operation == "click":
                await locator.click(timeout=10000)
            elif operation == "fill":
                await locator.fill(value,timeout=10000)
            elif operation == "select":
                await locator.select_option(value,timeout=10000)
            elif operation == "check":
                await locator.check(timeout=10000)
            elif operation == "uncheck":
                await locator.uncheck(timeout=10000)
            elif operation == "press":
                await locator.press(value,timeout=10000)
        return await self.snapshot(session_id)

    async def close(self, session_id: str) -> dict:
        async with self._lock:
            s = self._sessions.pop(session_id,None)
        if s is None:
            return {"closed":False}
        try:
            await s.browser.close()
        finally:
            await s.driver.stop()
        return {"closed":True}

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self.close(session_id)

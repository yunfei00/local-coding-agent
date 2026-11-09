"""Local browser automation; callers must authorize destinations and downloads."""
from __future__ import annotations
from urllib.parse import urlparse
import ipaddress
import socket

def validate_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only http(s) URLs without credentials are supported")
    if not allow_private:
        for family, _, _, _, address in socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM):
            ip = ipaddress.ip_address(address[0])
            if not ip.is_global:
                raise ValueError("Private, local or non-global destination blocked")
    return url

async def browser_snapshot(url: str, *, timeout_ms: int = 15000) -> dict:
    from playwright.async_api import async_playwright
    validate_url(url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(accept_downloads=False)
            await page.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).hostname == urlparse(url).hostname else route.abort())
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return {"url": page.url, "title": await page.title(), "text": (await page.locator("body").inner_text(timeout=timeout_ms))[:50000]}
        finally:
            await browser.close()

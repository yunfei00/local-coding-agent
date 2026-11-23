"""Constrained, read-only browser snapshots for public websites."""
from __future__ import annotations
from urllib.parse import urlparse
import ipaddress
import socket

def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only http(s) URLs without credentials are supported")
    for _, _, _, _, address in socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(address[0]).is_global:
            raise ValueError("Private, local or non-global destination blocked")
    return url

async def browser_snapshot(url: str, *, timeout_ms: int = 15000) -> dict:
    from playwright.async_api import async_playwright
    validate_url(url)
    original = urlparse(url).hostname
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(accept_downloads=False, service_workers="block")
            async def route_handler(route):
                candidate = route.request.url
                if urlparse(candidate).scheme not in ("https", "http") or urlparse(candidate).hostname != original:
                    await route.abort()
                    return
                try:
                    validate_url(candidate)
                except (OSError, ValueError):
                    await route.abort()
                    return
                await route.continue_()
            await page.route("**/*", route_handler)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if urlparse(page.url).hostname != original:
                raise ValueError("Redirected outside allowed host")
            return {"url": page.url, "title": await page.title(), "text": (await page.locator("body").inner_text(timeout=timeout_ms))[:50000]}
        finally:
            await browser.close()

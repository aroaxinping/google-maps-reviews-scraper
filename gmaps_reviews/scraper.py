"""
Core scraper: intercepts the real batchexecute request from Google Maps,
then paginates via in-page XHR with cursor substitution.

No external APIs. No proxies. Uses the real Chrome session.
"""

from __future__ import annotations
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from playwright.async_api import BrowserContext, Page, async_playwright

from .parser import parse_batch

PROFILE_DIR = Path.home() / ".playwright-google-profile"

_CHROME_CANDIDATES = {
    "linux": [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}


def _find_chrome() -> str | None:
    override = os.environ.get("CHROME_PATH")
    if override:
        return override
    platform = sys.platform
    for candidate in _CHROME_CANDIDATES.get(platform, _CHROME_CANDIDATES["linux"]):
        if Path(candidate).exists():
            return candidate
    return None


SKIP_HEADERS = {
    "host", "content-length", "connection", "accept-encoding",
    "accept-language", "accept", "user-agent", "sec-fetch-dest",
    "sec-fetch-mode", "sec-fetch-site", "sec-ch-ua",
    "sec-ch-ua-mobile", "sec-ch-ua-platform", "upgrade-insecure-requests",
}

_XHR_JS = """
async ([url, postData, headersList]) => {
    return new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        for (const [k, v] of headersList) {
            try { xhr.setRequestHeader(k, v); } catch(e) {}
        }
        xhr.withCredentials = true;
        xhr.onload  = () => resolve(xhr.responseText);
        xhr.onerror = () => resolve(null);
        xhr.ontimeout = () => resolve(null);
        xhr.timeout = 30000;
        xhr.send(postData);
    });
}
"""


def _substitute_cursor(template_body: str, cursor: str | None) -> str:
    params = parse_qs(template_body, keep_blank_values=True)
    if "f.req" not in params:
        return template_body
    outer = json.loads(params["f.req"][0])
    inner_obj = json.loads(outer[0][0][1])

    placed = False
    if (
        isinstance(inner_obj, list) and len(inner_obj) >= 2
        and isinstance(inner_obj[1], list) and len(inner_obj[1]) >= 2
        and isinstance(inner_obj[1][0], int)
    ):
        inner_obj[1][1] = cursor
        placed = True

    if not placed:
        inner_obj[0][1] = cursor

    outer[0][0][1] = json.dumps(inner_obj, separators=(",", ":"), ensure_ascii=False)
    params["f.req"] = [json.dumps(outer, separators=(",", ":"), ensure_ascii=False)]
    return urlencode(params, doseq=True)


async def _open_reviews_tab(page: Page) -> None:
    try:
        tab = page.get_by_role("tab", name=re.compile(r"Reviews|Reseñas", re.I))
        await tab.wait_for(timeout=10000)
        await tab.click()
        await page.wait_for_timeout(2500)
    except Exception:
        pass


async def _apply_sort(page: Page, sort: str) -> None:
    if sort == "relevant":
        return
    _SORT_LABELS = {
        "newest":  re.compile(r"Newest|Más reciente", re.I),
        "highest": re.compile(r"Highest|Más valorad", re.I),
        "lowest":  re.compile(r"Lowest|Más baja", re.I),
    }
    label = _SORT_LABELS.get(sort)
    if not label:
        return
    try:
        btn = page.get_by_role("button", name=re.compile(r"Sort|Ordenar", re.I))
        await btn.wait_for(timeout=8000)
        await btn.click()
        await page.wait_for_timeout(800)
        item = page.get_by_role("menuitem", name=label)
        await item.wait_for(timeout=5000)
        await item.click()
        await page.wait_for_timeout(2000)
    except Exception:
        pass  # sort button not found; continue with default order


async def _warmup(page: Page) -> dict:
    """Scroll once to trigger the first real batchexecute and capture its metadata."""
    warmup: dict = {"url": None, "post_data": None, "headers": None, "done": asyncio.Event()}

    def on_request(req):
        if "batchexecute" in req.url and "qv9Egd" in req.url and warmup["url"] is None:
            warmup["url"] = req.url
            warmup["post_data"] = req.post_data or ""
            warmup["headers"] = dict(req.headers)
            warmup["done"].set()

    page.on("request", on_request)

    container = await page.query_selector(
        ".m6QErb.DxyBCb, div[aria-label*='Reviews'], div[aria-label*='Reseñas']"
    )
    if container:
        await page.evaluate("el => { el.scrollTop += 5000; }", container)
    else:
        await page.keyboard.press("End")

    try:
        await asyncio.wait_for(warmup["done"].wait(), timeout=15.0)
    except asyncio.TimeoutError:
        raise RuntimeError("No batchexecute request captured after warmup scroll.")

    page.remove_listener("request", on_request)
    return warmup


async def scrape(
    maps_url: str,
    place_id: str,
    on_batch,           # async callback(reviews, next_cursor, raw) -> None
    limit: int = 0,     # 0 = all
    sort: str = "relevant",
    progress=None,      # rich Progress or None
) -> int:
    """
    Open Chrome, navigate to maps_url, capture all reviews via batchexecute.
    Calls on_batch for each page. Returns total reviews seen.
    """
    chrome_path = _find_chrome()
    if not chrome_path:
        raise RuntimeError(
            "Chrome not found. Install Google Chrome or set the CHROME_PATH "
            "environment variable to the path of your Chrome executable."
        )

    total_seen = 0

    async with async_playwright() as pw:
        try:
            context: BrowserContext = await pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                executable_path=chrome_path,
                headless=False,
                args=["--lang=en-US", "--disable-blink-features=AutomationControlled"],
                locale="en-US",
                ignore_https_errors=True,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "executable" in msg or "chrome" in msg or "not found" in msg:
                raise RuntimeError(
                    f"Chrome could not be launched at '{chrome_path}'. "
                    "Install Google Chrome or set CHROME_PATH to the correct path."
                ) from exc
            raise

        page: Page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(maps_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        if "accounts.google.com" in page.url:
            if progress:
                progress.log("[yellow]Waiting for Google login (up to 3 min)…")
            await page.wait_for_function(
                "() => !window.location.href.includes('accounts.google.com')",
                timeout=180000,
            )
            await page.wait_for_timeout(3000)

        await _open_reviews_tab(page)
        await _apply_sort(page, sort)

        warmup = await _warmup(page)
        real_url = warmup["url"]
        template_body = warmup["post_data"]
        send_headers = {
            k: v for k, v in warmup["headers"].items()
            if k.lower() not in SKIP_HEADERS
        }
        send_headers_list = list(send_headers.items())

        current_cursor: str | None = None
        consecutive_errors = 0
        captured_at = datetime.now(tz=timezone.utc)

        while True:
            modified_post = _substitute_cursor(template_body, current_cursor)
            try:
                raw = await page.evaluate(_XHR_JS, [real_url, modified_post, send_headers_list])
            except Exception:
                raw = None

            if raw is None:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    break
                await asyncio.sleep(3)
                continue
            consecutive_errors = 0

            reviews, next_cursor = parse_batch(raw, captured_at)
            await on_batch(reviews, next_cursor, raw)
            total_seen += len(reviews)

            if next_cursor is None:
                break
            if limit and total_seen >= limit:
                break

            current_cursor = next_cursor
            await asyncio.sleep(0.3)

        await page.wait_for_timeout(1500)
        await context.close()

    return total_seen

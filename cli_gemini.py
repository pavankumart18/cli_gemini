import sys
import os
import asyncio
import time
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


CDP_DEFAULT_URL = os.getenv("CDP_URL", "ws://127.0.0.1:9222")
GEMINI_URL = "https://gemini.google.com/app"


async def _find_input_locator(page):
    candidates = [
        'div[contenteditable="true"][role="textbox"]',
        'div[role="textbox"]',
        'div[contenteditable="true"]',
    ]
    for sel in candidates:
        loc = page.locator(sel)
        try:
            if await loc.count() > 0:
                # Prefer a visible one
                first_visible = loc.filter(has_text="").first
                try:
                    await first_visible.wait_for(state="visible", timeout=5000)
                    return first_visible
                except PlaywrightTimeoutError:
                    pass
        except PlaywrightTimeoutError:
            continue
    # Fallback to body if nothing else – keystrokes will still go somewhere
    return page.locator('body')


async def _wait_for_response_and_get_text(page, stable_ms: int = 1800, timeout_ms: int = 120_000) -> Optional[str]:
    # Union of likely response containers on Gemini
    response_selector = (
        'div.model-response div.markdown, '
        'div.model-response, '
        'main div.markdown, '
        'div[role="listitem"] div.markdown, '
        'div.markdown'
    )

    stop_btn = page.locator(
        'button:has-text("Stop"), '
        'button:has-text("Stop responding"), '
        'button:has-text("Stop generating"), '
        'button[aria-label*="Stop" i], '
        'button[aria-label*="respond" i]'
    )

    start = time.monotonic()
    stable_since = None
    last_text = None

    # Give some time for a streaming phase to kick in (if any)
    try:
        await stop_btn.first.wait_for(state="visible", timeout=7000)
    except PlaywrightTimeoutError:
        pass

    # Wait loop for stable last response text
    while (time.monotonic() - start) * 1000 < timeout_ms:
        try:
            count = await page.locator(response_selector).count()
            if count == 0:
                await asyncio.sleep(0.25)
                continue

            last = page.locator(response_selector).nth(count - 1)
            # Ensure element is attached/visible before reading
            try:
                await last.wait_for(state="attached", timeout=3000)
            except PlaywrightTimeoutError:
                await asyncio.sleep(0.2)
                continue

            text = (await last.inner_text()).strip()

            if text and text != last_text:
                last_text = text
                stable_since = time.monotonic()
            else:
                if text and stable_since and (time.monotonic() - stable_since) * 1000 >= stable_ms:
                    # Try to ensure streaming has stopped
                    try:
                        await stop_btn.first.wait_for(state="hidden", timeout=2000)
                    except PlaywrightTimeoutError:
                        # If stop button is still visible but content is stable for long enough, accept
                        pass
                    return text

            await asyncio.sleep(0.3)
        except PlaywrightTimeoutError:
            await asyncio.sleep(0.25)

    return last_text


async def run(question: str) -> int:
    async with async_playwright() as p:
        # Resolve and connect to an already-running Chrome via CDP
        async def resolve_cdp_endpoint(endpoint: str) -> str:
            u = urlparse(endpoint)
            # If ws and already points to a devtools browser endpoint, use it
            if u.scheme in ("ws", "wss"):
                if "/devtools/" in (u.path or ""):
                    return endpoint
                # Otherwise, fetch the proper WebSocketDebuggerUrl from /json/version
                http_scheme = "https" if u.scheme == "wss" else "http"
                host = u.hostname or "127.0.0.1"
                port = f":{u.port}" if u.port else ""
                http_base = f"{http_scheme}://{host}{port}"
                req = await p.request.new_context()
                resp = await req.get(f"{http_base}/json/version")
                if not resp.ok:
                    raise RuntimeError(f"CDP endpoint not reachable at {http_base} (/json/version)")
                data = await resp.json()
                ws_url = data.get("webSocketDebuggerUrl")
                if not ws_url:
                    raise RuntimeError("webSocketDebuggerUrl missing in /json/version response")
                return ws_url
            elif u.scheme in ("http", "https"):
                # Playwright can consume the HTTP DevTools endpoint directly
                return endpoint
            else:
                # Bare host:port -> assume http
                return f"http://{endpoint}"

        try:
            endpoint = await resolve_cdp_endpoint(CDP_DEFAULT_URL)
        except Exception as e:
            print(
                (
                    "Could not reach Chrome CDP endpoint. Ensure Chrome is started "
                    "with --remote-debugging-port=9222 and that http://127.0.0.1:9222/json/version is reachable.\n"
                    f"Detail: {e}"
                ),
                file=sys.stderr,
            )
            return 3

        try:
            browser = await p.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            print(
                (
                    "Failed to connect over CDP. Verify Chrome was launched with remote debugging "
                    "enabled on the same endpoint and try again.\n"
                    f"Endpoint: {endpoint}\nDetail: {e}"
                ),
                file=sys.stderr,
            )
            return 3

        # Reuse the existing (persistent) context when available
        context = browser.contexts[0] if browser.contexts else None
        if context is None:
            # Some remote instances allow creating a fresh context
            context = await browser.new_context()

        page = await context.new_page()
        page.set_default_timeout(60_000)
        page.set_default_navigation_timeout(60_000)

        await page.goto(GEMINI_URL, wait_until="domcontentloaded")

        # Focus input and send the message
        input_box = await _find_input_locator(page)
        await input_box.click()
        # Clear possible placeholder selection and type
        try:
            await input_box.fill("")  # works for contenteditable in Playwright
        except Exception:
            pass
        await input_box.type(question)
        await input_box.press("Enter")

        # Wait for final response and print
        text = await _wait_for_response_and_get_text(page)
        if text:
            print(text.strip())
            return 0
        else:
            # No content found – keep stdout clean, report on stderr
            print("No response captured from Gemini.", file=sys.stderr)
            return 2


def main():
    if len(sys.argv) < 2:
        print("Usage: python cli_gemini.py \"Your question...\"", file=sys.stderr)
        sys.exit(1)
    question = sys.argv[1]
    try:
        code = asyncio.run(run(question))
        sys.exit(code)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

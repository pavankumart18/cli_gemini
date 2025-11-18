import sys
import os
import asyncio
import time
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


CDP_DEFAULT_URL = os.getenv("CDP_URL", "ws://127.0.0.1:9222")
GEMINI_URL = "https://gemini.google.com/app"


async def _resolve_cdp_endpoint(p, endpoint: str) -> str:
    u = urlparse(endpoint)
    if u.scheme in ("ws", "wss"):
        if "/devtools/" in (u.path or ""):
            return endpoint
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
    if u.scheme in ("http", "https"):
        return endpoint
    return f"http://{endpoint}"


async def _find_input_locator(page):
    # Broad but ordered by likelihood
    candidates = [
        'div[aria-label*="Message Gemini" i][contenteditable="true"]',
        'div[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][aria-label*="Message" i]',
        'div[contenteditable="true"][aria-label*="Prompt" i]',
        'div[contenteditable="true"]',
        'div[role="textbox"]',
    ]
    for sel in candidates:
        loc = page.locator(sel)
        try:
            c = await loc.count()
        except PlaywrightTimeoutError:
            c = 0
        if c > 0:
            target = loc.nth(c - 1)
            try:
                await target.wait_for(state="visible", timeout=6000)
                return target
            except PlaywrightTimeoutError:
                # try any visible in this set
                try:
                    any_vis = loc.first
                    await any_vis.wait_for(state="visible", timeout=2000)
                    return any_vis
                except PlaywrightTimeoutError:
                    continue
    # Last resort
    return page.locator('body')


async def _dom_insert_fallback(page, question: str) -> bool:
    try:
        return await page.evaluate(
            """
(() => {
  function findPromptEl() {
    const sels = [
      'div[aria-label*="Message Gemini" i][contenteditable="true"]',
      'div[role="textbox"][contenteditable="true"]',
      'div[contenteditable="true"][aria-label*="Message" i]',
      'div[contenteditable="true"][aria-label*="Prompt" i]',
      'div[contenteditable="true"]'
    ];
    let cands = [];
    for (const s of sels) cands = cands.concat(Array.from(document.querySelectorAll(s)));
    if (!cands.length) return null;
    let best = null, bestScore = -1;
    for (const el of cands) {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const r = el.getBoundingClientRect();
      if (!r || r.width < 150 || r.height < 20) continue;
      const area = r.width * r.height;
      const bottomness = Math.max(0, (window.innerHeight - r.top) / window.innerHeight);
      const score = area + bottomness * 10000;
      if (score > bestScore) { bestScore = score; best = el; }
    }
    return best;
  }
  const el = findPromptEl();
  if (!el) return false;
  try { el.focus(); } catch {}
  try { document.execCommand('selectAll', false, null); } catch {}
  try { document.execCommand('insertText', false, %s); } catch {}
  try { el.dispatchEvent(new InputEvent('input', { bubbles: true })); } catch {}
  return true;
})()
            """ % (repr(question)),
        )
    except Exception:
        return False


async def _type_and_send(page, question: str):
    input_box = await _find_input_locator(page)
    await input_box.click()
    # Clear and type
    try:
        await page.keyboard.press('Control+A')
        await page.keyboard.press('Backspace')
    except Exception:
        pass
    typed = False
    try:
        await input_box.type(question, delay=10)
        try:
            v = (await input_box.inner_text()).strip()
        except Exception:
            v = ''
        if v:
            typed = True
    except Exception:
        pass
    if not typed:
        inserted = await _dom_insert_fallback(page, question)
        if not inserted:
            try:
                await page.keyboard.type(question, delay=10)
            except Exception:
                pass
    # Send
    try:
        await input_box.press('Enter')
    except Exception:
        await page.keyboard.press('Enter')


async def _wait_for_response_and_get_text(page, stable_ms: int = 1800, timeout_ms: int = 120_000, min_new: int = 1) -> Optional[str]:
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
    try:
        baseline_count = await page.locator(response_selector).count()
    except Exception:
        baseline_count = 0

    try:
        await stop_btn.first.wait_for(state="visible", timeout=7000)
    except PlaywrightTimeoutError:
        pass

    while (time.monotonic() - start) * 1000 < timeout_ms:
        try:
            count = await page.locator(response_selector).count()
            if count < max(1, baseline_count + min_new):
                await asyncio.sleep(0.25)
                continue

            last = page.locator(response_selector).nth(count - 1)
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
                    try:
                        await stop_btn.first.wait_for(state="hidden", timeout=2000)
                    except PlaywrightTimeoutError:
                        pass
                    return text

            await asyncio.sleep(0.3)
        except PlaywrightTimeoutError:
            await asyncio.sleep(0.25)

    return last_text


async def _minimize_window_if_possible(page) -> bool:
    try:
        client = await page.context.new_cdp_session(page)
        info = await client.send('Browser.getWindowForTarget')
        window_id = info.get('windowId')
        if window_id is not None:
            await client.send('Browser.setWindowBounds', {
                'windowId': window_id,
                'bounds': {'windowState': 'minimized'}
            })
            return True
    except Exception:
        pass
    return False


async def run(question: str) -> int:
    async with async_playwright() as p:
        try:
            endpoint = await _resolve_cdp_endpoint(p, CDP_DEFAULT_URL)
        except Exception as e:
            print(
                (
                    "Could not reach Chrome CDP endpoint. Ensure Chrome is started "
                    "with --remote-debugging-port and that /json/version is reachable.\n"
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
                    "Failed to connect over CDP. Verify Chrome has remote debugging enabled on this endpoint.\n"
                    f"Endpoint: {endpoint}\nDetail: {e}"
                ),
                file=sys.stderr,
            )
            return 3

        # Prefer reusing an existing persistent context/page
        if browser.contexts:
            context = browser.contexts[0]
            page = await context.new_page()
        else:
            page = await browser.new_page()
        page.set_default_timeout(60_000)
        page.set_default_navigation_timeout(60_000)

        await page.goto(GEMINI_URL, wait_until="domcontentloaded")
        # Non-fatal wait for an input candidate
        try:
            await page.wait_for_selector('div[contenteditable="true"], div[role="textbox"]', state='visible', timeout=10_000)
        except Exception:
            pass

        # Type and send with robust fallbacks
        await _type_and_send(page, question)

        # Wait for final response and print
        text = await _wait_for_response_and_get_text(page)
        if text:
            print(text.strip())
            # Try to minimize the Chrome window after capturing output
            try:
                await _minimize_window_if_possible(page)
            except Exception:
                pass
            return 0
        else:
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

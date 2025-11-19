import os
import sys
import asyncio
from playwright.async_api import async_playwright

CDP = os.getenv("CDP_URL", "http://127.0.0.1:9222")
SITES = {
    "gemini": (
        "https://gemini.google.com/app",
        'css=textarea:visible, div[role="textbox"]:not([aria-hidden="true"]):visible, div[contenteditable="true"]:not(.ql-clipboard):not([aria-hidden="true"]):visible',
        "div.markdown",
    ),
    "chatgpt": (
        "https://chatgpt.com",
        'css=textarea:visible, div[contenteditable="true"]:not([aria-hidden="true"]):visible',
        ".markdown, [data-message-author-role=assistant]",
    ),
    "claude": (
        "https://claude.ai/new",
        'css=textarea:visible, div[contenteditable="true"]:not([aria-hidden="true"]):visible',
        ".prose, .markdown, [data-testid=chat-message]",
    ),
}

async def ask(site, question):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        page = await (browser.contexts[0].new_page() if browser.contexts else browser.new_page())
        url, input_sel, resp_sel = SITES[site]
        await page.goto(url)
        await page.wait_for_load_state("domcontentloaded")
        box = page.locator(input_sel).first
        await box.wait_for(state="visible")
        await box.fill(question)
        await box.press("Enter")
        await page.wait_for_selector(resp_sel)
        txt = await page.locator(resp_sel).last.inner_text()
        print(txt.strip())
        try:
            c = await page.context.new_cdp_session(page)
            w = await c.send('Browser.getWindowForTarget')
            await c.send('Browser.setWindowBounds', {'windowId': w['windowId'], 'bounds': {'windowState': 'minimized'}})
        except Exception:
            pass

def main():
    args = sys.argv[1:]
    site = "gemini"
    if args and args[0] in SITES:
        site, args = args[0], args[1:]
    question = " ".join(args) if args else ""
    asyncio.run(ask(site, question))

if __name__ == "__main__":
    main()

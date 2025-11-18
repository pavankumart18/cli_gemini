# Gemini CLI (cli_gemini.py)

Automate the Gemini web app from the command line using a real Chrome session via Playwright + Chrome DevTools Protocol (CDP). The script opens Gemini, sends your prompt, prints the model response to stdout, and then attempts to minimize the Chrome window.

## Features

- Connects to an existing Chrome instance over CDP (no API keys).
- Reuses your signed-in Chrome profile (persistent context).
- Robust prompt entry with fallbacks if selectors change.
- Waits for the response to stabilize before printing.
- Minimizes the Chrome window after output (best-effort).

## Requirements

- Python 3.8+
- Google Chrome installed
- Playwright for Python

Install dependencies:

```bash
python -m venv .venv
. .venv/Scripts/Activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install playwright
# Optional but recommended; not strictly required for CDP attach
python -m playwright install
```

## Start Chrome with remote debugging

You must run Chrome with a remote debugging port open so Playwright can attach.

- Windows (PowerShell):

```powershell
$chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
& $chrome --remote-debugging-port=9222 --user-data-dir="C:\\temp\\chrome-gemini"
```

- Verify CDP endpoint is reachable by visiting in a browser:

```
http://127.0.0.1:9222/json/version
```

If you use a different host/port or a wss proxy, set `CDP_URL` accordingly (see below).

Sign in to your Google account in that Chrome window and ensure `https://gemini.google.com/app` works there.

## Usage

```bash
python cli_gemini.py "Your question here"
```

- The script navigates to Gemini, enters your question, and prints the model response to stdout.
- After printing, it tries to minimize the Chrome window (no-op in headless or if unsupported).

### Environment variables

- `CDP_URL` (optional): CDP endpoint. Defaults to `ws://127.0.0.1:9222`.
  - Accepts either a full websocket URL (e.g., `ws://127.0.0.1:9222/devtools/browser/...`) or an HTTP base (e.g., `http://127.0.0.1:9222`). When HTTP is provided, the script auto-discovers the websocket URL from `/json/version`.

### Examples

- Default port/host:

```powershell
python cli_gemini.py "Summarize the key ideas of reinforcement learning"
```

- Custom CDP endpoint (different port):

```powershell
$env:CDP_URL = "http://127.0.0.1:9223"
python cli_gemini.py "Give me 3 bullet points about rust lifetimes"
```

## Exit codes

- `0`: Success; response printed
- `2`: No response captured or runtime error
- `3`: Could not connect to Chrome CDP endpoint
- `130`: Keyboard interrupt (Ctrl+C)

## Troubleshooting

- "Could not reach Chrome CDP endpoint": Ensure Chrome is launched with `--remote-debugging-port`, and `http://127.0.0.1:9222/json/version` is reachable. Check firewalls/port conflicts.
- "Failed to connect over CDP": Confirm the `CDP_URL` is correct and your Chrome instance is running with remote debugging enabled.
- Stuck on sign-in or blank page: Open the attached Chrome window and sign in to your Google account. The script reuses that profile.
- No output or partial output: The script waits for text to stabilize; UI changes can affect selectors. Re-run and/or increase stability timeouts in the code if needed.
- Window did not minimize: This is a best-effort call and may be ignored in headless mode or by the OS/window manager.

## Notes

- This script drives the public web UI. Use it responsibly and in accordance with Google’s terms.
- It does not store credentials; authentication persists in your Chrome profile.
- No Gemini API key is used; all interaction is via your browser session.

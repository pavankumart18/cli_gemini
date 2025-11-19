# Quick Start

Assumes Chrome remote debugging (CDP) is already running.

```bash
# Gemini (default)
uv run cli_gemini.py "Your question"

# ChatGPT
uv run cli_gemini.py chatgpt "Your question"

# Claude
uv run cli_gemini.py claude "Your question"

# Optional: change CDP endpoint
CDP_URL=http://127.0.0.1:9223 uv run cli_gemini.py "Your question"
```

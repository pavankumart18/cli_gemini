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

## Examples

```powershell
# Example 1
uv run .\cli_gemini.py "who is Prime Minister of India?"

Output (example):
The current Prime Minister of India is Narendra Modi.
He is serving his third consecutive term (sworn in June 9, 2024)...

# Example 2
uv run .\cli_gemini.py "who first developed a llm?"

Output (example):
The answer depends on definition and history...
1. The modern definition: Google & OpenAI (2017–2018)...
```

Note: After printing the response, the Chrome window is minimized automatically (best‑effort).

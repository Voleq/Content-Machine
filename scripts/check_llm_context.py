#!/usr/bin/env python3
"""Prove `OLLAMA_NUM_CTX` is actually taking effect (K6).

Ollama does not error on an overflowing prompt. It drops the overflow from
the FRONT and summarises what remains, so a filing brief built from half a
section is indistinguishable from one built from all of it — a plausible,
confident answer with nothing anywhere indicating what happened. That is
the same failure as the synthetic price chart (B1): fabricated output no
surface in the product can reveal.

So this sends `filings_llm_max_chars` worth of text with a marker at the
very start and asks for the marker back. The marker returning means the
whole section is reaching the model. Anything else means it is not, and
every brief the feature produces is fiction.

NOT A UNIT TEST, deliberately: it needs a live Ollama, and the suite is
offline. Run it after any model, Ollama or budget change:

    python scripts/check_llm_context.py

Per X1 this is the shape the rest of the suite aspires to — it asserts on
what came out, not on what was sent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARKER = "MARKER-ALPHA-7"


def main() -> int:
    import httpx

    from config import get_settings

    s = get_settings()
    filler = "The company faces competitive risks. "
    body = f"{MARKER}. " + filler * (
        max(s.filings_llm_max_chars - len(MARKER) - 2, 0) // len(filler))
    url = s.ollama_base_url.rstrip("/") + "/api/chat"
    print(f"model      {s.ollama_model}")
    print(f"num_ctx    {s.ollama_num_ctx} tokens")
    print(f"sending    {len(body):,} chars "
          f"(filings_llm_max_chars = {s.filings_llm_max_chars:,})")
    try:
        r = httpx.post(url, timeout=s.ollama_timeout_s, json={
            "model": s.ollama_model,
            "messages": [
                {"role": "system", "content": "Answer in five words or fewer."},
                {"role": "user", "content": body +
                 "\n\nWhat is the marker at the very start of the text above?"},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": s.ollama_num_ctx},
        })
        r.raise_for_status()
        answer = (r.json().get("message") or {}).get("content", "").strip()
    except Exception as e:  # noqa: BLE001 — this script IS the diagnostic
        print(f"\nFAILED to reach Ollama at {url}: {type(e).__name__}: {e}")
        print("Nothing is proven either way. Start Ollama and re-run.")
        return 2

    print(f"answer     {answer!r}")
    if MARKER.lower() in answer.lower():
        print(f"\nOK — the marker came back, so all {len(body):,} characters "
              f"are reaching the model.")
        return 0
    print(f"\nTRUNCATED — the marker did NOT come back. The front of the "
          f"prompt is being dropped, so every filing brief this box "
          f"produces is built from partial text.\n"
          f"Raise OLLAMA_NUM_CTX (it is {s.ollama_num_ctx}) or lower "
          f"FILINGS_LLM_MAX_CHARS (it is {s.filings_llm_max_chars}), and "
          f"confirm the model's own context length with "
          f"`ollama show {s.ollama_model}`.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

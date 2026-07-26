"""LLM routing — local first, hosted as the fallback.

The cheap passes (fact-check assistance, the skeptic read, the filings
smoking-gun flagger) all want a small model and run often. With a 12GB GPU
in the render box, a local Ollama model is the better default: no rate
limits, no network dependency, no quota anxiety, and still $0. GitHub Models
becomes the fallback rather than the primary.

Providers are tried in order and the first that answers wins, so a machine
with no Ollama running degrades to the hosted tier without configuration,
and a machine with no token at all degrades to None — which every caller
treats as "this pass did not run", never as an error.

MOCK_MODE never touches the network. That is the same hard rule the rest of
the pipeline follows, and it is what keeps the suite offline.
"""

from __future__ import annotations

import json
import logging

from config import Settings

log = logging.getLogger(__name__)

OLLAMA = "ollama"
GITHUB = "github"
OPENAI = "openai"


def provider_order(settings: Settings) -> list[str]:
    """Providers to try, in order. `llm_provider_order` overrides."""
    configured = [p.strip().lower() for p in
                  (settings.llm_provider_order or "").split(",") if p.strip()]
    return configured or [OLLAMA, GITHUB, OPENAI]


def _post(url: str, payload: dict, headers: dict, timeout: float):
    import httpx

    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _try_ollama(prompt: str, system: str, settings: Settings) -> str | None:
    """A local Ollama daemon. Absent one, this fails fast and we move on."""
    try:
        data = _post(
            settings.ollama_base_url.rstrip("/") + "/api/chat",
            {
                "model": settings.ollama_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            {"Content-Type": "application/json"},
            settings.ollama_timeout_s,
        )
        return (data.get("message") or {}).get("content") or None
    except Exception as e:  # noqa: BLE001 — absence is the normal case
        log.debug("ollama unavailable (%s)", e)
        return None


def _try_openai_compatible(prompt: str, system: str, settings: Settings,
                           base: str, token: str, model: str,
                           path: str) -> str | None:
    if not token:
        return None
    try:
        data = _post(
            base.rstrip("/") + path,
            {"model": model,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
             "temperature": 0.2},
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            45.0,
        )
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.debug("hosted LLM call failed (%s)", e)
        return None


def chat(prompt: str, settings: Settings, *, system: str = "",
         purpose: str = "llm") -> str | None:
    """One completion from the first provider that answers, or None.

    None is a normal outcome, not an error: every gate that uses this
    degrades to "did not run" rather than blocking a render.
    """
    if settings.mock_mode:
        log.info("%s: MOCK_MODE — LLM pass skipped", purpose)
        return None
    try:
        import httpx  # noqa: F401
    except ImportError:
        return None

    for provider in provider_order(settings):
        if provider == OLLAMA:
            out = _try_ollama(prompt, system, settings)
        elif provider == GITHUB:
            out = _try_openai_compatible(
                prompt, system, settings, settings.github_models_endpoint,
                settings.github_models_token, settings.filings_llm_model,
                "/chat/completions")
        elif provider == OPENAI:
            out = _try_openai_compatible(
                prompt, system, settings, settings.openai_base_url,
                settings.openai_api_key, settings.filings_llm_model,
                "/v1/chat/completions")
        else:
            log.warning("%s: unknown LLM provider %r — skipped", purpose, provider)
            continue
        if out:
            log.info("%s: answered by %s", purpose, provider)
            return out
    log.info("%s: no LLM provider answered — pass skipped", purpose)
    return None


def chat_json(prompt: str, settings: Settings, *, system: str = "",
              purpose: str = "llm") -> dict | list | None:
    """`chat`, parsed as JSON. Models fence their output often enough that
    stripping a ``` wrapper is worth doing here rather than in every caller."""
    raw = chat(prompt, settings, system=system, purpose=purpose)
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except ValueError:
        start = min((i for i in (text.find("["), text.find("{")) if i >= 0),
                    default=-1)
        end = max(text.rfind("]"), text.rfind("}"))
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
        log.warning("%s: response was not JSON", purpose)
        return None

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
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass

from config import Settings

log = logging.getLogger(__name__)

OLLAMA = "ollama"
GITHUB = "github"
OPENAI = "openai"

# WHAT EACH PASS IS FOR, keyed by the `purpose` its caller passes. The
# journal records every call under this name, and `/ask` hands the list to
# the model so it can say what it does inside the bot. A purpose used in the
# code and missing here fails `tests/test_recall.py`, so the model's picture
# of its own job cannot fall behind the code.
PURPOSES: dict[str, str] = {
    "filing-brief-section": "reads one section of a 10-K or 10-Q and notes "
                            "its specific risks, numbers and wording changes",
    "filing-brief-condense": "turns those section notes into the filing "
                             "brief shown before a LONG's angle is picked",
    "filing-brief-crosscheck": "lists where the filing and the workbook "
                               "numbers disagree",
    "filing-brief-grade": "grades what the last video claimed against the "
                          "new filings, for /update",
    "filings": "picks verbatim quotes from a 10-K to screenshot, and "
               "summarises news articles",
    "skeptic": "reads a script as a hostile investor and names its weakest "
               "claims (advisory, never blocks)",
    "broll query": "turns a visual cue in a script into a stock-footage "
                   "search",
    "ask-expand": "widens an /ask question into the words the bot's records "
                  "would use",
    "ask": "answers an /ask question from the bot's own records",
    "llm": "an unnamed pass",
}


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


# Why a completion did not happen, when it did not (N2b).
#
# `chat()` collapsed every failure into `None`, so no caller could tell a
# daemon that is not running from a request that timed out, a model that
# returned empty, a JSON parse failure, or MOCK_MODE. The docstring was
# explicit that this was deliberate — "None is a normal outcome, not an
# error" — and for graceful degradation that instinct is right. But it meant
# no gate, no brief and no provenance line could ever explain itself, which
# is exactly what N2 needs them to do: `skeptic_notes` returning `[]` for a
# clean script and `[]` for a dead daemon are not the same event.
OK = "ok"
NO_DAEMON = "no_daemon"
TIMEOUT = "timeout"
EMPTY = "empty"
PARSE_ERROR = "parse_error"
MOCK = "mock"
NO_PROVIDER = "no_provider"


@dataclass(frozen=True)
class LLMResult:
    """A completion, or the reason there is not one.

    Falsy when there is no text, so every existing `if out:` call site is
    unchanged — and the ones that care can read `reason`, `provider` and
    `model`.
    """

    text: str = ""
    provider: str = ""
    model: str = ""
    reason: str = NO_PROVIDER

    def __bool__(self) -> bool:
        return bool(self.text)

    def __str__(self) -> str:
        return self.text


def _try_ollama(prompt: str, system: str, settings: Settings) -> LLMResult:
    """A local Ollama daemon. Absent one, this fails fast and we move on."""
    model = settings.ollama_model
    try:
        data = _post(
            settings.ollama_base_url.rstrip("/") + "/api/chat",
            {
                "model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "stream": False,
                # `num_ctx` IS PASSED (K2). Ollama's default context has
                # historically been 2048-4096 tokens, the per-section filing
                # budget is `filings_llm_max_chars = 24000` (~6,000 tokens),
                # and Ollama does not error on an overflowing prompt — it
                # drops the front and summarises what remains. The result is
                # a plausible, confident brief built from partial text, with
                # nothing anywhere indicating it happened: B1's failure mode
                # in a new place.
                #
                # In config.py rather than an Ollama Modelfile. A Modelfile
                # works and hides a load-bearing value somewhere the
                # repository cannot see, audit or test — and the whole reason
                # this defect existed is that the budget lived in one place
                # and the context limit in another.
                "options": {"temperature": 0.2,
                            "num_ctx": settings.ollama_num_ctx},
            },
            {"Content-Type": "application/json"},
            settings.ollama_timeout_s,
        )
    except Exception as e:  # noqa: BLE001 — absence is the normal case
        # A TIMEOUT AND A MISSING DAEMON ARE DIFFERENT INFORMATION (K2).
        # Both were caught here as "unavailable" at debug level, so a pass
        # that nearly worked looked identical to one that never started.
        if _looks_like_timeout(e):
            log.warning("ollama timed out after %.0fs (%s) — the pass did "
                        "not run", settings.ollama_timeout_s, e)
            return LLMResult(provider=OLLAMA, model=model, reason=TIMEOUT)
        log.debug("ollama unavailable (%s)", e)
        return LLMResult(provider=OLLAMA, model=model, reason=NO_DAEMON)
    text = (data.get("message") or {}).get("content") or ""
    return LLMResult(text=text, provider=OLLAMA, model=model,
                     reason=OK if text else EMPTY)


def _looks_like_timeout(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timeout" in str(exc).lower()


def _try_openai_compatible(prompt: str, system: str, settings: Settings,
                           base: str, token: str, model: str,
                           path: str, provider: str = "") -> LLMResult:
    if not token:
        return LLMResult(provider=provider, model=model, reason=NO_DAEMON)
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
    except Exception as e:  # noqa: BLE001
        log.debug("hosted LLM call failed (%s)", e)
        return LLMResult(provider=provider, model=model,
                         reason=TIMEOUT if _looks_like_timeout(e) else NO_DAEMON)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        log.warning("hosted LLM returned an unreadable body (%s)", e)
        return LLMResult(provider=provider, model=model, reason=PARSE_ERROR)
    return LLMResult(text=text, provider=provider, model=model,
                     reason=OK if text else EMPTY)


def chat_result(prompt: str, settings: Settings, *, system: str = "",
                purpose: str = "llm",
                providers: list[str] | None = None) -> LLMResult:
    """One completion from the first provider that answers, with its reason.

    `chat` is this, narrowed to the text — every existing caller keeps
    working. Callers that have to EXPLAIN an absence use this one (N2b):
    which provider answered, which model, and why there is no text.

    That last part matters beyond curiosity. `llm_provider_order` defaults
    to `ollama,github,openai`, so **a local failure silently becomes hosted
    spend** — a brief generated on your own GPU and one that quietly cost
    money were indistinguishable in every output the product produced. The
    provider is carried out now and the provenance record counts hosted
    fallbacks per render.

    An empty result is a normal outcome, not an error: every gate that uses
    this degrades to "did not run" rather than blocking a render.

    `providers` narrows the routing for one caller. `/ask` passes its own
    order, local-only by default, so a question typed in passing never
    becomes hosted spend.
    """
    if settings.mock_mode:
        log.info("%s: MOCK_MODE — LLM pass skipped", purpose)
        out = LLMResult(reason=MOCK)
        record_llm_call(settings, out, purpose=purpose)
        return out
    try:
        import httpx  # noqa: F401
    except ImportError:
        out = LLMResult(reason=NO_DAEMON)
        record_llm_call(settings, out, purpose=purpose)
        return out

    last = LLMResult(reason=NO_PROVIDER)
    for provider in (providers if providers is not None
                     else provider_order(settings)):
        if provider == OLLAMA:
            out = _try_ollama(prompt, system, settings)
        elif provider == GITHUB:
            out = _try_openai_compatible(
                prompt, system, settings, settings.github_models_endpoint,
                settings.github_models_token, settings.filings_llm_model,
                "/chat/completions", provider=GITHUB)
        elif provider == OPENAI:
            out = _try_openai_compatible(
                prompt, system, settings, settings.openai_base_url,
                settings.openai_api_key, settings.filings_llm_model,
                "/v1/chat/completions", provider=OPENAI)
        else:
            log.warning("%s: unknown LLM provider %r — skipped", purpose, provider)
            continue
        if out:
            log.info("%s: answered by %s", purpose, provider)
            record_llm_call(settings, out, purpose=purpose)
            return out
        last = out
    log.info("%s: no LLM provider answered — pass skipped", purpose)
    record_llm_call(settings, last, purpose=purpose)
    return last


def chat(prompt: str, settings: Settings, *, system: str = "",
         purpose: str = "llm") -> str | None:
    """One completion from the first provider that answers, or None.

    None is a normal outcome, not an error: every gate that uses this
    degrades to "did not run" rather than blocking a render. Use
    `chat_result` where the REASON matters.
    """
    out = chat_result(prompt, settings, system=system, purpose=purpose)
    return out.text or None


# --------------------------------------------------------------------------
# What the LLM layer did this run.
# --------------------------------------------------------------------------
#
# `chat()` already logged the provider that answered — `log.info("%s:
# answered by %s", ...)` — but a log line is not a surface: the caller never
# saw it and neither did the operator (N2b). So every call is tallied here
# and the provenance record reads it.
#
# Process-local rather than persisted: the question is "what happened in THIS
# video", and a file would answer a different one.
#
# KEYED BY SCOPE, and that is the whole point. This was one flat list with a
# `reset_llm_calls()` that nothing outside the tests ever called, so every
# render's provenance block reported every LLM call since the bot booted:
# `provider` and `model` came from the first call the PROCESS made, and
# `hosted_fallbacks` — the one figure here that is about money — carried a
# hosted call from three videos ago into a video that made none. A record
# whose whole purpose is honesty about what happened cannot be a running
# total presented as a per-render one.
#
# Resetting at the render was not the fix either: the LLM work all happens at
# INTAKE — the filing brief at `/long`, the flagger at the angle pick, the
# skeptic in `run_gates` — hours before the render job runs, so a reset there
# would make almost every record read "0 calls". The scope is therefore the
# WORKSPACE, which is what "this video" actually means, and the bot opens one
# around each entry point that can reach an LLM.
#
# Thread-local, because the filing reading runs on its own thread (K3) while
# the bot goes on handling messages, and a plain global would tally an AAPL
# brief against whatever workspace the operator happened to be pasting into.

_CALLS: "OrderedDict[str, list[dict]]" = OrderedDict()
_SCOPE = threading.local()
# The filing reader writes from its own thread while the bot writes from the
# main one, so the tally itself is shared state even though the SCOPE is not.
_TALLY_LOCK = threading.Lock()

# A bound, so a bot that runs for months does not accumulate one bucket per
# video it ever made. Far more than anything reads back.
_MAX_SCOPES = 64


def current_scope() -> str:
    """The scope LLM calls on this thread are tallied against."""
    return getattr(_SCOPE, "key", "")


@contextmanager
def llm_scope(key: str):
    """Tally every LLM call made on this thread, in here, against `key`.

    Nests and restores, so a caller that already opened one is not clobbered
    by an inner one — and an empty key means "unscoped", which is what a
    script or a test that never opens a scope gets.
    """
    previous = getattr(_SCOPE, "key", "")
    _SCOPE.key = key
    try:
        yield key
    finally:
        _SCOPE.key = previous


def record_llm_call(settings: Settings, result: LLMResult, *,
                    purpose: str = "") -> None:
    scope = current_scope()
    with _TALLY_LOCK:
        _CALLS.setdefault(scope, []).append(
            {"purpose": purpose, "provider": result.provider,
             "model": result.model, "reason": result.reason})
        _CALLS.move_to_end(scope)
        while len(_CALLS) > _MAX_SCOPES:
            _CALLS.popitem(last=False)
    # The tally above is per process and per video on purpose; the journal
    # is the copy that survives a restart, so "what did the model work on
    # yesterday" has an answer.
    from pipeline import journal

    ticker, _, workdate = scope.partition("/")
    journal.note(settings, "ai", f"{purpose or 'llm'}: {_outcome(result)}",
                 ticker=ticker, workdate=workdate, purpose=purpose,
                 provider=result.provider, model=result.model,
                 reason=result.reason)


_OUTCOME_WORDS = {
    OK: "answered",
    NO_DAEMON: "no model answered",
    TIMEOUT: "timed out",
    EMPTY: "came back empty",
    PARSE_ERROR: "came back unreadable",
    MOCK: "skipped (MOCK_MODE)",
    NO_PROVIDER: "no model configured",
}


def _outcome(result: LLMResult) -> str:
    words = _OUTCOME_WORDS.get(result.reason, result.reason or "unknown")
    if result.reason == OK:
        where = "locally" if result.provider == OLLAMA else "HOSTED"
        return f"{words} {where} ({result.provider}/{result.model})"
    return words


def reset_llm_calls(scope: str | None = None) -> None:
    """Drop one scope's tally, or every scope when none is named."""
    with _TALLY_LOCK:
        if scope is None:
            _CALLS.clear()
        else:
            _CALLS.pop(scope, None)


def llm_calls(scope: str | None = None) -> list[dict]:
    return list(_CALLS.get(current_scope() if scope is None else scope, []))


def llm_summary(settings: Settings, scope: str | None = None) -> dict:
    """`{provider, model, calls, hosted_fallbacks, skipped}` for one scope.

    The scope is the workspace this video belongs to; `None` reads the one
    open on this thread, which is what `provenance.build` wants — it runs
    inside the render, under the scope the bot opened.

    `hosted_fallbacks` is the number that matters on a box configured
    local-first: `llm_provider_order` defaults to `ollama,github,openai`, so
    a local failure becomes hosted spend, and a non-zero count is a thing to
    SEE rather than discover on a bill. It is only that if it counts THIS
    video's calls, which is what the keyed tally above is for.
    """
    tally = _CALLS.get(current_scope() if scope is None else scope, [])
    calls = [c for c in tally if c["reason"] == OK]
    hosted = [c for c in calls if c["provider"] in (GITHUB, OPENAI)]
    order = provider_order(settings)
    local_first = bool(order) and order[0] == OLLAMA
    answered = calls[0] if calls else None
    return {
        "provider": (answered or {}).get("provider", ""),
        "model": (answered or {}).get("model", ""),
        "calls": len(calls),
        "hosted_fallbacks": len(hosted) if local_first else 0,
        "skipped": [c["reason"] for c in tally if c["reason"] != OK],
    }


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

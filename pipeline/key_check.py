"""Do the keys in .env actually work? One free call per service.

The Settings page's health rows say whether a key is FILLED IN; a pasted key
with a character missing, a revoked one or a voice id from another account
passes that and fails at the render, after the writing and the approval. So
`/admin keys` (and the page's "Test the keys") asks each service once, with a
call that costs nothing:

* ElevenLabs — the account's subscription (characters left), then each voice
  id. A key scoped not to read the account still works for the voice.
* Pexels — a one-result search. It is counted in the month's Pexels calls
  like any other, because Pexels counts it.
* Giphy, Tenor — a one-result search.
* FRED — one series' description.
* Telegram — the bot's own name.
* OpenAI — the model list. GitHub Models — the token's own account.
* SEC — the ticker list, with SEC_USER_AGENT, which is what the SEC refuses.
* YouTube — the channel the credentials upload to (one unit of the day's
  10,000).

A key's text never reaches a result: every detail is scrubbed of it before it
is returned, and requests go through httpx, whose request log `main` keeps at
WARNING.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import SEC_AGENT_PLACEHOLDERS, Settings

log = logging.getLogger(__name__)

OK, BAD, SKIP = "ok", "bad", "skip"
TIMEOUT_S = 12.0
TELEGRAM_API = "https://api.telegram.org"
GITHUB_API = "https://api.github.com"
# Not his address and not SEC_USER_AGENT: the services below need no contact.
USER_AGENT = "dennis-content-machine/1.0 (key check)"


@dataclass
class KeyResult:
    name: str
    state: str          # ok | bad | skip
    detail: str


Get = Callable[..., object]


def _get(url: str, **kw):
    import httpx

    headers = {"User-Agent": USER_AGENT, **(kw.pop("headers", None) or {})}
    return httpx.get(url, headers=headers, timeout=TIMEOUT_S,
                     follow_redirects=True, **kw)


def _json(resp) -> dict:
    try:
        got = resp.json()
    except Exception:                                  # noqa: BLE001
        return {}
    return got if isinstance(got, dict) else {}


def _refused(service: str, resp) -> KeyResult:
    return KeyResult(service, BAD, f"refused the key ({resp.status_code})")


def _eleven(s: Settings, get: Get) -> list[KeyResult]:
    if not s.elevenlabs_api_key:
        return [KeyResult("ElevenLabs", SKIP, "ELEVENLABS_API_KEY is not set")]
    head = {"xi-api-key": s.elevenlabs_api_key}
    resp = get(f"{s.eleven_base_url}/v1/user/subscription", headers=head)
    detail = _json(resp).get("detail")
    status = detail.get("status", "") if isinstance(detail, dict) else ""
    if resp.status_code == 200:
        sub = _json(resp)
        used, limit = sub.get("character_count"), sub.get("character_limit")
        if isinstance(used, int) and isinstance(limit, int):
            left = f"{max(limit - used, 0):,} of {limit:,} characters left"
            reset = sub.get("next_character_count_reset_unix")
            if isinstance(reset, (int, float)) and reset > 0:
                day = datetime.fromtimestamp(reset, timezone.utc).strftime("%d %b")
                left += f", resets {day}"
            out = [KeyResult("ElevenLabs", OK, left)]
        else:
            out = [KeyResult("ElevenLabs", OK, "the key works")]
    elif resp.status_code == 401 and status == "missing_permissions":
        out = [KeyResult("ElevenLabs", OK, "the key works; it may not read the "
                         "account, so the characters left cannot be shown")]
    else:
        return [_refused("ElevenLabs", resp)]
    ids = {}
    for lane, vid in (("short", s.eleven_voice_id_short), ("long", s.eleven_voice_id_long)):
        ids.setdefault(vid, []).append(lane)
    for vid, lanes in ids.items():
        label = f"ElevenLabs {' and '.join(lanes)} voice"
        if not vid:
            out.append(KeyResult(label, BAD, "no voice id set (ELEVEN_VOICE_ID_"
                                 + "/".join(l.upper() for l in lanes) + ")"))
            continue
        resp = get(f"{s.eleven_base_url}/v1/voices/{vid}", headers=head)
        detail = _json(resp).get("detail")
        status = detail.get("status", "") if isinstance(detail, dict) else ""
        if resp.status_code == 200:
            out.append(KeyResult(label, OK, str(_json(resp).get("name") or vid)))
        elif resp.status_code == 401 and status == "missing_permissions":
            out.append(KeyResult(label, SKIP, "the key may not read voices, so "
                                 "this one cannot be checked"))
        else:
            out.append(KeyResult(label, BAD, f"{vid} is not a voice this "
                                 f"account can use ({resp.status_code})"))
    return out


def _pexels(s: Settings, get: Get) -> list[KeyResult]:
    if not s.pexels_api_key:
        return [KeyResult("Pexels", SKIP, "PEXELS_API_KEY is not set")]
    from pipeline.cost import SpendLedger

    try:
        SpendLedger(s).record_pexels_call()
    except Exception as e:                             # noqa: BLE001
        log.warning("the Pexels call could not be counted: %s", e)
    resp = get(f"{s.pexels_base_url}/v1/search",
               params={"query": "office", "per_page": 1},
               headers={"Authorization": s.pexels_api_key})
    if resp.status_code != 200:
        return [_refused("Pexels", resp)]
    left = (getattr(resp, "headers", None) or {}).get("X-Ratelimit-Remaining")
    return [KeyResult("Pexels", OK, f"{int(left):,} calls left this month"
                      if str(left or "").isdigit() else "the key works")]


def _search(name: str, key: str, url: str, params: dict, get: Get) -> list[KeyResult]:
    if not key:
        return [KeyResult(name, SKIP, f"{name.upper()}_API_KEY is not set")]
    resp = get(url, params=params)
    return [KeyResult(name, OK, "the key works") if resp.status_code == 200
            else _refused(name, resp)]


def _giphy(s: Settings, get: Get) -> list[KeyResult]:
    return _search("Giphy", s.giphy_api_key, f"{s.giphy_base_url}/v1/gifs/search",
                   {"api_key": s.giphy_api_key, "q": "coffee", "limit": 1}, get)


def _tenor(s: Settings, get: Get) -> list[KeyResult]:
    return _search("Tenor", s.tenor_api_key, f"{s.tenor_base_url}/v2/search",
                   {"key": s.tenor_api_key, "q": "coffee", "limit": 1}, get)


def _fred(s: Settings, get: Get) -> list[KeyResult]:
    return _search("FRED", s.fred_api_key, f"{s.fred_base_url}/fred/series",
                   {"series_id": "CPIAUCSL", "api_key": s.fred_api_key,
                    "file_type": "json"}, get)


def _telegram(s: Settings, get: Get) -> list[KeyResult]:
    if not s.telegram_bot_token:
        return [KeyResult("Telegram", SKIP, "TELEGRAM_BOT_TOKEN is not set")]
    resp = get(f"{TELEGRAM_API}/bot{s.telegram_bot_token}/getMe")
    me = _json(resp).get("result") or {}
    if resp.status_code == 200 and isinstance(me, dict):
        return [KeyResult("Telegram", OK, f"@{me.get('username') or 'the bot'}")]
    return [_refused("Telegram", resp)]


def _openai(s: Settings, get: Get) -> list[KeyResult]:
    if not s.openai_api_key:
        return [KeyResult("OpenAI", SKIP, "OPENAI_API_KEY is not set (only the "
                          "paid fallback for the writing checks uses it)")]
    resp = get(f"{s.openai_base_url}/v1/models",
               headers={"Authorization": f"Bearer {s.openai_api_key}"})
    return [KeyResult("OpenAI", OK, "the key works") if resp.status_code == 200
            else _refused("OpenAI", resp)]


def _github(s: Settings, get: Get) -> list[KeyResult]:
    if not s.github_models_token:
        return [KeyResult("GitHub Models", SKIP, "GITHUB_MODELS_TOKEN is not set")]
    resp = get(f"{GITHUB_API}/user",
               headers={"Authorization": f"Bearer {s.github_models_token}"})
    if resp.status_code == 200:
        login = _json(resp).get("login")
        return [KeyResult("GitHub Models", OK, f"a token for {login}" if login
                          else "the token works")]
    return [_refused("GitHub Models", resp)]


def _sec(s: Settings, get: Get) -> list[KeyResult]:
    agent = s.sec_user_agent.strip()
    if not agent or agent in SEC_AGENT_PLACEHOLDERS:
        return [KeyResult("SEC", SKIP, "SEC_USER_AGENT is not set")]
    resp = get(f"{s.sec_base_url}/files/company_tickers.json",
               headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"})
    if resp.status_code == 200:
        return [KeyResult("SEC", OK, "accepts SEC_USER_AGENT")]
    return [KeyResult("SEC", BAD, f"refused SEC_USER_AGENT ({resp.status_code}); "
                      f"it wants a name and a contact address")]


def _youtube(s: Settings, get: Get) -> list[KeyResult]:
    path = Path(s.youtube_credentials or "")
    if not s.youtube_credentials or not path.exists():
        return [KeyResult("YouTube", SKIP, "no credentials file (YOUTUBE_CREDENTIALS)")]
    from pipeline.youtube import YouTubeClient, YouTubeUnavailable

    try:
        yt = YouTubeClient(s)._build("youtube", "v3")
        got = yt.channels().list(part="snippet", mine=True).execute()
    except YouTubeUnavailable as e:
        return [KeyResult("YouTube", BAD, str(e)[:200])]
    except Exception as e:                             # noqa: BLE001
        return [KeyResult("YouTube", BAD, f"the credentials did not sign in: "
                          f"{type(e).__name__}")]
    items = got.get("items") or []
    if not items:
        return [KeyResult("YouTube", BAD, "signed in, but the account has no channel")]
    title = (items[0].get("snippet") or {}).get("title") or "a channel"
    return [KeyResult("YouTube", OK, f"uploads to {title}")]


CHECKS = (("ElevenLabs", _eleven), ("Pexels", _pexels), ("Giphy", _giphy),
          ("Tenor", _tenor), ("FRED", _fred), ("Telegram", _telegram),
          ("OpenAI", _openai), ("GitHub Models", _github), ("SEC", _sec),
          ("YouTube", _youtube))


def _secrets(s: Settings) -> list[str]:
    return [v for v in (s.elevenlabs_api_key, s.pexels_api_key, s.giphy_api_key,
                        s.tenor_api_key, s.fred_api_key, s.telegram_bot_token,
                        s.openai_api_key, s.github_models_token) if v]


def check_keys(settings: Settings, *, get: Get | None = None) -> list[KeyResult]:
    """Every service's answer, in a fixed order. Never raises: a service that
    cannot be reached is a `bad` row saying so."""
    get = get or _get

    def one(named) -> list[KeyResult]:
        name, check = named
        try:
            return check(settings, get)
        except Exception as e:                         # noqa: BLE001
            return [KeyResult(name, BAD, f"could not be reached ({type(e).__name__})")]

    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        rows = [r for got in pool.map(one, CHECKS) for r in got]
    secrets = _secrets(settings)
    for r in rows:
        for secret in secrets:
            r.detail = r.detail.replace(secret, "…")
    return rows


_MARK = {OK: "✅", BAD: "❌", SKIP: "·"}


def keys_text(settings: Settings, *, get: Get | None = None) -> str:
    rows = check_keys(settings, get=get)
    bad = sum(r.state == BAD for r in rows)
    head = (f"🔑 {bad} key(s) to fix before a real video." if bad else
            "🔑 every key that is set works.")
    return "\n".join([head, ""] + [f"{_MARK[r.state]} {r.name}: {r.detail}"
                                   for r in rows])

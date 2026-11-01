"""[WEB: address] — a screenshot of a real web page, taken by the bot.

Valentin, 1 Nov 2026: "can't playwright take those pictures?" It can, for
most of the web, and the tag is built around where it can't:

* GOOGLE, REDDIT AND THE SOCIAL SITES ARE NOT TRIED. From his box a headless
  browser gets Google's EU consent page and then, often, an "unusual traffic"
  check; Reddit answers "blocked by network security"; X, Facebook, Instagram,
  TikTok and LinkedIn put a log-in wall in front of the page. The bot does not
  try to get past any of those checks. It asks him for the shot instead, with
  the link to open, and the beat plays a stock clip until he drops it.
* ANY OTHER SITE MAY STILL REFUSE. The shot is checked before it is kept: the
  status the site answered, the phrases a block or a wall is written in, a
  page that came back nearly empty, a picture that came out blank. A refused
  shot is never kept, and the report says what the site did.
* A PAGE CHANGES. The shot is taken once and kept under its slug, with the
  address and the date beside it (state/web_shots.json); the description
  credits the site. Writing a different address is a new shot.
* ONLY THE PUBLIC WEB. http(s) only, and never an address on the box's own
  network: the writer's text decides what the bot's browser opens.

The bot does not pass itself off as anything: Chromium's own headless user
agent, and English asked for in the ordinary way (`Accept-Language`).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from config import Settings

log = logging.getLogger(__name__)

# Sites that wall or block a headless browser on sight. Matched on the host
# and its parents, so `old.reddit.com` and `news.google.co.uk` are in.
WALLED_SITES: dict[str, str] = {
    "google": "Google",          # any google.<tld>
    "reddit.com": "Reddit", "redd.it": "Reddit",
    "x.com": "X", "twitter.com": "X",
    "facebook.com": "Facebook", "instagram.com": "Instagram",
    "threads.net": "Threads", "tiktok.com": "TikTok",
    "linkedin.com": "LinkedIn", "youtube.com": "YouTube",
}

# A block, a wall or a paywall, as the page words it. Matched on the title,
# and on the page's text only when that text is short: a real article can
# say "protected by reCAPTCHA" in its footer, a block page says little else.
_BLOCK_WORDS = (
    "access denied", "verify you are human", "verify you are a human",
    "are you a robot", "not a robot", "unusual traffic", "captcha",
    "just a moment", "attention required", "blocked by network security",
    "request blocked", "you have been blocked", "you've been blocked",
    "pardon our interruption", "enable javascript and cookies",
    "403 forbidden", "access to this page has been denied",
    "before you continue", "sign in to continue", "log in to continue",
    "subscribe to continue", "to continue reading", "already a subscriber",
)
_SHORT_PAGE = 2500   # characters of text under which a block word counts
_EMPTY_PAGE = 150    # characters of text under which the page is empty

# The shot: a 1280 x 720 window, the width most sites are laid out for,
# drawn at 1.5x so the file is the long's 1920 x 1080 frame.
VIEW_W, VIEW_H, SCALE = 1280, 720, 1.5
GOTO_TIMEOUT_MS = 20000
SETTLE_TIMEOUT_MS = 6000
# A failed address is not tried again on every paste of the script.
RETRY_AFTER_S = 6 * 3600
MAX_SHOTS = 8        # per script: each can take twenty seconds
STOCK_CLIP = "scrolling a website on a laptop"

_CONSENT_REJECT = re.compile(
    r"^\s*(reject all|reject|decline all|decline|only necessary|"
    r"necessary only|use necessary cookies only)\s*$", re.I)
_CONSENT_ACCEPT = re.compile(
    r"^\s*(accept all|accept all cookies|accept|accept cookies|i agree|agree|"
    r"allow all|got it|ok|okay)\s*$", re.I)
_CONSENT_CLOSE = re.compile(
    r"^\s*(close|dismiss|no,? thanks|not now|continue without accepting|"
    r"close this (?:banner|notice|message)|×|✕)\s*$", re.I)


@dataclass
class WebAsk:
    url: str
    find: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return web_slug(self.url, self.find)


def parse_web(payload: str) -> WebAsk:
    """`"sec.gov/... | find=the exact words"` -> WebAsk. An address written
    without a scheme gets https."""
    from pipeline.tagging import split_payload_fields

    head, fields, warnings = split_payload_fields(payload or "")
    url = head.strip().strip("<>").strip()
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    find = " ".join(fields.pop("find", "").split()).strip("\"“”")
    for name in fields:
        warnings.append(f"[WEB] has no `{name}` field — ignored (only find=)")
    return WebAsk(url=url, find=find, warnings=warnings)


def web_slug(url: str, find: str = "") -> str:
    """The file name the shot is kept under, readable and unique:
    `https://investor.redditinc.com/news` -> `web-investor-redditinc-com-news-1a2b3c`."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    words = re.findall(r"[a-z0-9]+", f"{host} {parts.path}".lower())
    stem = "-".join(words)[:44].strip("-") or "page"
    tag = hashlib.sha1(f"{url}|{find}".encode()).hexdigest()[:6]
    return f"web-{stem}-{tag}"


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def walled_site(url: str) -> str:
    """The site's name when it walls or blocks a headless browser, else ""."""
    host = host_of(url)
    labels = host.split(".")
    for i in range(len(labels)):
        tail = ".".join(labels[i:])
        if tail in WALLED_SITES:
            return WALLED_SITES[tail]
    # google.com, google.ro, google.co.uk, news.google.com
    if "google" in labels[:-1]:
        return WALLED_SITES["google"]
    return ""


def _private_ip(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def unsafe_reason(url: str, *, resolve: bool = False) -> str:
    """Why the bot's browser must not open this address, or "".

    `resolve` also looks the host up, so a public-looking name that points
    into the box's own network is refused too (done before a shot, never at
    parse time, which must not touch the network)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "it is not a web address (http or https)"
    host = (parts.hostname or "").lower()
    if not host or "." not in host and not _private_ip(host):
        return "it has no site in it"
    if host == "localhost" or host.endswith((".local", ".internal", ".lan",
                                             ".home", ".localhost")):
        return "it points at a machine on your own network"
    if _private_ip(host):
        return "it points at a machine on your own network"
    if resolve:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return "the site's name does not exist"
        if any(_private_ip(i[4][0]) for i in infos):
            return "it points at a machine on your own network"
    return ""


# ------------------------------------------------------------------ record
def _record_path(settings: Settings) -> Path:
    return settings.state_dir / "web_shots.json"


def load_record(settings: Settings) -> dict[str, dict]:
    try:
        data = json.loads(_record_path(settings).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_record(settings: Settings, slug: str, entry: dict) -> None:
    data = load_record(settings)
    data[slug] = entry
    path = _record_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def note_ask(settings: Settings, ask: WebAsk, status: str, why: str = "",
             *, at: float | None = None) -> None:
    """Remember what became of an address: "ok", "walled", "refused"."""
    _save_record(settings, ask.slug, {
        "url": ask.url, "find": ask.find, "status": status, "why": why,
        "at": time.time() if at is None else at})


def shot_file(settings: Settings, slug: str) -> Path | None:
    custom = settings.custom_assets_dir
    if not custom.is_dir():
        return None
    for p in sorted(custom.glob(f"{slug}.*")):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            return p
    return None


def credit(settings: Settings, slug: str) -> str:
    """The description's credit for a kept shot, "" when it is not a page."""
    entry = load_record(settings).get(slug) or {}
    url = entry.get("url") or ""
    if not url:
        return ""
    when = time.strftime("%d %b %Y", time.gmtime(entry.get("at") or time.time()))
    return f"Screenshot of {host_of(url)} ({url}), {when}"


# ------------------------------------------------------------------ shoot
def _looks_refused(title: str, text: str) -> str:
    low_title = (title or "").lower()
    body = " ".join((text or "").split())
    low = body.lower()
    for w in _BLOCK_WORDS:
        if w in low_title or (len(body) < _SHORT_PAGE and w in low):
            return f"the site showed “{w}” instead of the page"
    if len(body) < _EMPTY_PAGE:
        return "the page came back almost empty"
    return ""


def _blank_picture(path: Path) -> bool:
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        return ImageStat.Stat(im.convert("L")).stddev[0] < 6.0


def _dismiss_consent(page) -> None:
    """Answer a cookie banner the way a reader would: "Reject all" when it
    offers that, else its accept button, else its close button. Then hide
    what is left of one: a large fixed panel about cookies or privacy, or a
    consent platform's frame. Best effort, about a second a frame."""
    for frame in page.frames[:6]:
        done = False
        for rx in (_CONSENT_REJECT, _CONSENT_ACCEPT, _CONSENT_CLOSE):
            try:
                btn = frame.get_by_role("button", name=rx).first
                if btn.count() and btn.is_visible(timeout=400):
                    btn.click(timeout=1000)
                    page.wait_for_timeout(600)
                    done = True
                    break
            except Exception:  # noqa: BLE001 — a banner is never a failure
                continue
        if done:
            break
    try:
        page.evaluate(_HIDE_CONSENT_JS)
    except Exception:  # noqa: BLE001
        pass


# A cookie or privacy panel still on screen after the buttons: hidden for the
# shot, and the page's scroll lock taken off with it.
_HIDE_CONSENT_JS = r"""() => {
    const vw = innerWidth, vh = innerHeight, big = vw * vh * 0.12;
    const named = /consent|cookie|gdpr|cmp|sp_message|onetrust|didomi|truste|privacy-?banner/i;
    const words = /cookie|privacy|consent|personal information|gdpr/i;
    let n = 0;
    for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
        const r = el.getBoundingClientRect();
        if (r.width * r.height < big) continue;
        const ident = `${el.id} ${el.className && el.className.baseVal === undefined ? el.className : ''}`;
        const frame = el.tagName === 'IFRAME' ? `${el.id} ${el.name} ${el.src}` : '';
        const text = el.innerText || '';
        const aboutCookies = r.width * r.height >= big * 1.7 && text.length < 1500 && words.test(text);
        if (named.test(ident) || named.test(frame) || aboutCookies) {
            el.style.setProperty('display', 'none', 'important');
            n++;
        }
    }
    if (n) for (const el of [document.documentElement, document.body])
        if (el) el.style.setProperty('overflow', 'auto', 'important');
    return n;
}"""

# The writer's words, marked across however many elements they run over (a
# link in the middle of a sentence is three), and brought to the middle.
_MARK_JS = r"""(quote) => {
    const sel = window.getSelection();
    const tries = [quote, quote.replace(/'/g, '’'), quote.replace(/’/g, "'")];
    let found = false;
    for (const q of tries) {
        sel.removeAllRanges();
        window.scrollTo(0, 0);
        if (window.find(q, false, false, true, false, false, false)) { found = true; break; }
    }
    if (!found || !sel.rangeCount) return false;
    const range = sel.getRangeAt(0);
    const sc = range.startContainer, so = range.startOffset;
    const ec = range.endContainer, eo = range.endOffset;
    let root = range.commonAncestorContainer;
    if (root.nodeType === 3) root = root.parentNode;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let t;
    while ((t = w.nextNode())) if (range.intersectsNode(t)) nodes.push(t);
    sel.removeAllRanges();
    let first = null;
    for (const node of nodes) {
        const s = node === sc ? so : 0;
        const e = node === ec ? eo : node.textContent.length;
        if (e <= s || !node.textContent.slice(s, e).trim()) continue;
        const r = document.createRange();
        r.setStart(node, s);
        r.setEnd(node, e);
        const m = document.createElement('mark');
        m.dataset.dennis = '1';
        m.style.background = '#ffe27a';
        m.style.color = 'inherit';
        r.surroundContents(m);
        first = first || m;
    }
    if (first) first.scrollIntoView({block: 'center', inline: 'nearest'});
    return !!first;
}"""


def _point_at(page, find: str) -> bool:
    """Mark the writer's words and bring them to the middle of the window."""
    try:
        return bool(page.evaluate(_MARK_JS, find))
    except Exception:  # noqa: BLE001
        return False


def _shoot_one(browser, ask: WebAsk, dest: Path) -> tuple[bool, str]:
    """(kept, why). `why` is the refusal, or a note on a kept shot."""
    ctx = browser.new_context(
        viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE,
        locale="en-US", extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
    try:
        page = ctx.new_page()
        try:
            resp = page.goto(ask.url, wait_until="domcontentloaded",
                             timeout=GOTO_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:120]
            return False, ("the page took too long to open" if "Timeout" in msg
                           else f"the page would not open ({msg})")
        status = resp.status if resp is not None else 0
        # Where it ended up after its redirects, held to the rule the asked
        # address was held to by the caller.
        bad = unsafe_reason(page.url)
        if bad and not unsafe_reason(ask.url):
            return False, f"the page sent the browser elsewhere: {bad}"
        if status == 404 or status == 410:
            return False, f"the site answered {status}: there is no page at that address"
        if status >= 400:
            return False, f"the site answered {status} (it refuses the bot's browser)"
        try:
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 — a page that keeps polling is fine
            pass
        _dismiss_consent(page)
        try:
            title = page.title()
            text = page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:  # noqa: BLE001
            title, text = "", ""
        refused = _looks_refused(title, text[:20000])
        if refused:
            return False, refused
        note = ""
        if ask.find and not _point_at(page, ask.find):
            note = "the words in find= are not on the page, so the top of the page was shot"
        page.wait_for_timeout(500)
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), timeout=8000)
        if _blank_picture(dest):
            dest.unlink(missing_ok=True)
            return False, "the shot came out blank"
        return True, note
    finally:
        ctx.close()


def pending_asks(raw: str) -> list[WebAsk]:
    """Every [WEB] in a script, in order, one per address."""
    from pipeline.models import TagType
    from pipeline.tagging import tokenize_tags

    _clean, tags, _w = tokenize_tags(raw or "")
    out: list[WebAsk] = []
    seen: set[str] = set()
    for t in tags:
        if t.type is TagType.WEB:
            ask = parse_web(t.payload)
            if ask.url and ask.slug not in seen:
                seen.add(ask.slug)
                out.append(ask)
    return out


def take_shots(raw: str, settings: Settings, *, now: float | None = None) -> list[str]:
    """Take the shots a script's [WEB] tags ask for and do not have yet.

    Called when a long script comes in, before it is parsed, so the parse
    finds the shots and shows them. Returns one line per shot taken or
    refused, for the log. Never raises: a shot is a help, never a failure.
    """
    if settings.mock_mode or not settings.web_shots:
        return []
    now = time.time() if now is None else now
    record = load_record(settings)
    todo: list[WebAsk] = []
    for ask in pending_asks(raw):
        if shot_file(settings, ask.slug) is not None:
            continue
        site = walled_site(ask.url)
        if site:
            if (record.get(ask.slug) or {}).get("status") != "walled":
                note_ask(settings, ask, "walled", site, at=now)
            continue
        if unsafe_reason(ask.url):
            continue
        last = record.get(ask.slug) or {}
        if last.get("status") == "refused" and now - float(last.get("at") or 0) < RETRY_AFTER_S:
            continue
        todo.append(ask)
    if not todo:
        return []
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        log.warning("web shots: playwright not installed")
        return []
    # Playwright's sync API refuses to run on a thread with a running asyncio
    # loop (the bot's), so it always runs on a worker thread of its own.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_shoot_all, todo[:MAX_SHOTS], settings, now).result()


def _shoot_all(todo: list[WebAsk], settings: Settings, now: float) -> list[str]:
    from playwright.sync_api import sync_playwright

    from pipeline.filings import _chromium_executable

    lines: list[str] = []
    custom = settings.custom_assets_dir
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,
                                        executable_path=_chromium_executable(settings))
            try:
                for ask in todo:
                    why = unsafe_reason(ask.url, resolve=True)
                    if why:
                        note_ask(settings, ask, "refused", why, at=now)
                        lines.append(f"{ask.url}: not opened, {why}")
                        continue
                    dest = custom / f"{ask.slug}.png"
                    try:
                        kept, why = _shoot_one(browser, ask, dest)
                    except Exception as e:  # noqa: BLE001
                        kept, why = False, f"the browser failed ({str(e).splitlines()[0][:100]})"
                    note_ask(settings, ask, "ok" if kept else "refused", why, at=now)
                    lines.append(f"{ask.url}: {'shot' if kept else 'refused'}"
                                 + (f", {why}" if why else ""))
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        log.warning("web shots: browser would not start (%s)", e)
    for line in lines:
        log.info("web shot %s", line)
    return lines


def web_tag_outcome(ask: WebAsk, settings: Settings) -> tuple[str, str]:
    """(state, sentence) for the report: state is "shot", "yours",
    "refused", "unsafe" or "waiting"."""
    slug = ask.slug
    if shot_file(settings, slug) is not None:
        return "shot", ""
    why = unsafe_reason(ask.url)
    if why:
        return "unsafe", (
            f"[WEB: {ask.url}] is not opened: {why}. Give the address of a "
            f"public web page. It plays a stock clip.")
    site = walled_site(ask.url)
    drop = f"drop it on the page as {slug}.png (the Check step has a box for it)"
    if site:
        return "yours", (
            f"[WEB: {ask.url}] — {site} blocks the bot's browser, so this one "
            f"is yours: open {ask.url} in your browser, take a screenshot and "
            f"{drop}. Until then it plays a stock clip.")
    entry = load_record(settings).get(slug) or {}
    if entry.get("status") == "refused":
        return "refused", (
            f"[WEB: {ask.url}] — the bot could not take this shot: "
            f"{entry.get('why') or 'the site refused it'}. It plays a stock "
            f"clip. Take the screenshot yourself and {drop}, or give "
            f"another address.")
    off = ("mock mode is on" if settings.mock_mode
           else "web shots are switched off (WEB_SHOTS=false)" if not settings.web_shots
           else "it has not been taken yet")
    return "waiting", (
        f"[WEB: {ask.url}] has no shot: {off}. It plays a stock clip until "
        f"there is one; or {drop}.")


def page_screens(script, settings: Settings) -> list[dict]:
    """The Check step's list of screens: every [WEB] and every [IMG] of a
    screen in the saved script, with what became of it and the file name a
    screenshot of his goes under. Shots already in are listed too, so a bad
    one can be replaced."""
    from pipeline.models import TagType

    record = load_record(settings)
    out: list[dict] = []
    seen: set[str] = set()
    for e in getattr(script, "events", []) or []:
        values = e.values or {}
        if e.type in (TagType.CLIP, TagType.BROLL) and values.get("screen"):
            slug, url = values["screen"], values.get("url", "")
        elif e.type is TagType.SCREENGRAB and e.payload in record:
            slug, url = e.payload, (record[e.payload] or {}).get("url", "")
        else:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        entry = record.get(slug) or {}
        have = shot_file(settings, slug) is not None
        if have:
            state = "shot" if entry.get("status") == "ok" else "yours-in"
            why = entry.get("why", "") if state == "shot" else ""
        elif not url:
            state, why = "yours", "a picture of a website or app screen: the bot has no address to open"
        else:
            site, bad = walled_site(url), unsafe_reason(url)
            if bad:
                state, why = "unsafe", bad
            elif site:
                state, why = "yours", f"{site} blocks the bot's browser, so this shot is yours"
            elif entry.get("status") == "refused":
                state, why = "refused", entry.get("why") or "the site refused the bot"
            else:
                state, why = "waiting", (
                    "mock mode is on" if settings.mock_mode
                    else "web shots are off (WEB_SHOTS=false)" if not settings.web_shots
                    else "not taken yet")
        out.append({"slug": slug, "url": url, "site": walled_site(url) if url else "",
                    "host": host_of(url) if url else "", "state": state,
                    "why": why, "file": f"{slug}.png"})
    return out


def mark_his(settings: Settings, slug: str) -> None:
    """His own screenshot is in for this slug (it replaces the bot's)."""
    entry = load_record(settings).get(slug)
    if entry:
        _save_record(settings, slug, dict(entry, status="his", why="",
                                          at=time.time()))

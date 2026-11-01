"""[WEB: address] — a real web page, screenshot by the bot (1 Nov 2026).

Valentin: "can't playwright take those pictures of google or reddit?" It can
for most of the web. Google and Reddit (and the social sites) block a
headless browser, so those are never tried and are asked of him; every other
shot is checked before it is kept; the beat plays a stock clip until a shot
exists and nothing blocks.
"""

from __future__ import annotations

import http.server
import io
import threading

import pytest
from PIL import Image

from pipeline import web_shots as W
from pipeline.models import TagType
from pipeline.parser_long import _SLUG_RE, parse_long_script

BODY = ("Reddit is a community of communities. It is built on the shared "
        "interests, passion and trust of its users, and it is home to the "
        "most open and authentic conversations on the internet. Every day, "
        "people come to Reddit to find community and belonging. ") * 3


def _script(tag: str) -> str:
    return ("The company says it is the front page of the internet, which is "
            "the kind of thing a front page would say about itself. "
            f"{tag} Here is the page, in its own words. That part is real. "
            "I checked it at three in the morning, which tells you about me. "
            "Revenue went from four hundred million to four ninety six over "
            "five years, which is technically growth in the way a coma is "
            "technically rest, and the share price has done the same thing "
            "in the other direction. See you at the next filing.")


# ----------------------------------------------------------------- the tag
def test_an_address_and_its_words_are_read_from_the_tag():
    ask = W.parse_web("investor.redditinc.com/overview | find=a community of communities")
    assert ask.url == "https://investor.redditinc.com/overview"
    assert ask.find == "a community of communities"
    assert ask.slug.startswith("web-investor-redditinc-com-overview-")
    assert _SLUG_RE.match(ask.slug)
    # the same page with other words marked is another shot
    assert W.parse_web("investor.redditinc.com/overview").slug != ask.slug
    assert W.parse_web("https://a.example/x | size=big").warnings


def test_google_reddit_and_the_social_sites_are_never_tried():
    for url, site in (("https://www.google.com/search?q=reddit", "Google"),
                      ("https://www.google.ro/search?q=x", "Google"),
                      ("https://news.google.co.uk/", "Google"),
                      ("https://old.reddit.com/r/stocks", "Reddit"),
                      ("https://www.reddit.com/r/RDDT/", "Reddit"),
                      ("https://x.com/reddit", "X"),
                      ("https://m.facebook.com/reddit", "Facebook"),
                      ("https://www.youtube.com/watch?v=1", "YouTube")):
        assert W.walled_site(url) == site, url
    for url in ("https://investor.redditinc.com/", "https://notgoogle.com/",
                "https://www.sec.gov/edgar", "https://apps.apple.com/app/reddit"):
        assert W.walled_site(url) == "", url


def test_only_the_public_web_is_opened():
    for url in ("file:///etc/passwd", "http://localhost:8080/admin",
                "http://192.168.1.1/", "http://10.0.0.5/x", "http://[::1]/",
                "https://router.lan/", "ftp://example.com/file", "https://intranet"):
        assert W.unsafe_reason(url), url
    assert W.unsafe_reason("https://www.example.com/page") == ""


def test_a_page_with_no_shot_plays_a_clip_and_names_the_box(settings):
    script, warnings = parse_long_script(
        _script("[WEB: https://www.reddit.com/r/RDDT/ | find=front page]"),
        "EXMPL", settings)
    assert not script.events_of(TagType.SCREENGRAB)
    clips = script.events_of(TagType.CLIP)
    slug = W.parse_web("https://www.reddit.com/r/RDDT/ | find=front page").slug
    assert [c.values.get("screen") for c in clips] == [slug]
    assert clips[0].values["url"] == "https://www.reddit.com/r/RDDT/"
    assert script.screen_slugs() == [slug]
    said = " ".join(warnings)
    assert "Reddit blocks the bot's browser" in said and f"{slug}.png" in said
    # the stand-in clip is not also reported as off the palette
    assert "not in the vetted palette" not in said


def test_a_shot_that_exists_is_shown_and_credited(settings):
    ask = W.parse_web("https://investor.redditinc.com/overview")
    custom = settings.custom_assets_dir
    custom.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1920, 1080), (240, 240, 240)).save(custom / f"{ask.slug}.png")
    W.note_ask(settings, ask, "ok")
    script, _w = parse_long_script(_script(f"[WEB: {ask.url}]"), "EXMPL", settings)
    assert [e.payload for e in script.events_of(TagType.SCREENGRAB)] == [ask.slug]
    assert not script.events_of(TagType.CLIP)
    assert W.credit(settings, ask.slug).startswith(
        "Screenshot of investor.redditinc.com (https://investor.redditinc.com/overview), ")
    (screen,) = W.page_screens(script, settings)
    assert screen["state"] == "shot" and screen["file"] == f"{ask.slug}.png"
    W.mark_his(settings, ask.slug)
    assert W.page_screens(script, settings)[0]["state"] == "yours-in"


def test_the_check_step_lists_each_screen_and_what_it_needs(settings):
    raw = _script("[WEB: https://www.google.com/search?q=reddit+stock] and "
                  "[WEB: http://192.168.1.1/] and [WEB: https://www.example.com/a] "
                  "[IMG: Reddit app home feed on a phone screen]")
    script, _w = parse_long_script(raw, "EXMPL", settings)
    states = {s["host"] or s["slug"]: s["state"] for s in W.page_screens(script, settings)}
    assert states == {"google.com": "yours", "192.168.1.1": "unsafe",
                      "example.com": "waiting", "reddit-app-home-feed-phone": "yours"}


# ---------------------------------------------------------- taking shots
def test_no_shot_is_taken_in_mock_mode(settings, monkeypatch):
    monkeypatch.setattr(W, "_shoot_one", lambda *a, **k: pytest.fail("shot in mock mode"))
    assert W.take_shots(_script("[WEB: https://www.example.com/]"), settings) == []


def test_walled_sites_are_recorded_not_tried_and_a_refusal_is_not_retried(settings, monkeypatch):
    live = settings.model_copy(update={"mock_mode": False})
    tries: list[str] = []

    class _Browser:
        def close(self):
            pass

    class _PW:
        def __enter__(self):
            class _C:
                launch = staticmethod(lambda **k: _Browser())
            return type("P", (), {"chromium": _C})()

        def __exit__(self, *a):
            return False

    import playwright.sync_api as sync_api

    monkeypatch.setattr(sync_api, "sync_playwright", lambda: _PW())
    monkeypatch.setattr(W, "unsafe_reason", lambda url, resolve=False: "")

    def _fake(browser, ask, dest):
        tries.append(ask.url)
        return False, "the site answered 403 (it refuses the bot's browser)"

    monkeypatch.setattr(W, "_shoot_one", _fake)
    raw = _script("[WEB: https://www.reddit.com/r/RDDT/] [WEB: https://www.example.com/a]")
    lines = W.take_shots(raw, live, now=1000.0)
    assert tries == ["https://www.example.com/a"]
    assert lines and "refused" in lines[0]
    record = W.load_record(live)
    assert {v["status"] for v in record.values()} == {"walled", "refused"}
    # pasted again within the hour: not tried again
    W.take_shots(raw, live, now=1000.0 + 60)
    assert tries == ["https://www.example.com/a"]
    # and again much later: tried once more
    W.take_shots(raw, live, now=1000.0 + W.RETRY_AFTER_S + 1)
    assert len(tries) == 2


# --------------------------------------------------- the real browser here
class _Pages(http.server.BaseHTTPRequestHandler):
    PAGES = {
        "/ok": (200, f"<html><head><title>About</title></head><body><h1>About us</h1>"
                     f"<p>{BODY}</p><p>We report <a href='#'>daily active</a> uniques every quarter.</p></body></html>"),
        "/consent": (200, "<html><body><div id=b style='position:fixed;inset:0;background:#fff'>"
                          "We use cookies <button onclick=\"document.getElementById('b').remove()\">"
                          f"Reject all</button></div><p>{BODY}</p></body></html>"),
        "/privacy-panel": (200, "<html><body><div id=p style='position:fixed;left:0;right:0;bottom:0;"
                                "height:60%;background:#123'>Your privacy. We and our partners use "
                                "cookies. <button>Do not sell my personal information</button></div>"
                                f"<p>{BODY}</p></body></html>"),
        "/forbidden": (403, "<html><body>Forbidden</body></html>"),
        "/cf": (200, "<html><head><title>Just a moment...</title></head><body>"
                     "Checking your browser before accessing the site.</body></html>"),
        "/empty": (200, "<html><body><div></div></body></html>"),
    }

    def do_GET(self):  # noqa: N802
        status, html = self.PAGES.get(self.path, (404, "<html><body>nope</body></html>"))
        data = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture()
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def browser(settings):
    sync_api = pytest.importorskip("playwright.sync_api")
    from pipeline.filings import _chromium_executable

    try:
        pw = sync_api.sync_playwright().start()
        b = pw.chromium.launch(headless=True, executable_path=_chromium_executable(settings))
    except Exception:  # noqa: BLE001
        pytest.skip("headless chromium unavailable in this environment")
    yield b
    b.close()
    pw.stop()


def test_a_real_page_is_shot_at_the_long_s_size_with_its_words_marked(browser, site, tmp_path):
    """The words are found even where a link runs through them."""
    dest = tmp_path / "ok.png"
    kept, why = W._shoot_one(browser, W.WebAsk(url=f"{site}/ok", find="daily active uniques"), dest)
    assert kept and why == ""
    with Image.open(dest) as im:
        assert im.size == (1920, 1080)
    # words that are not on the page: kept, and said
    kept, why = W._shoot_one(browser, W.WebAsk(url=f"{site}/ok", find="not on this page at all"),
                             tmp_path / "ok2.png")
    assert kept and "not on the page" in why


def test_a_cookie_banner_is_answered(browser, site, tmp_path):
    kept, _why = W._shoot_one(browser, W.WebAsk(url=f"{site}/consent"), tmp_path / "c.png")
    assert kept
    page = browser.new_page()
    try:
        page.goto(f"{site}/consent")
        W._dismiss_consent(page)
        assert page.evaluate("() => !document.getElementById('b')")
        # a panel with no button the bot knows is hidden instead
        page.goto(f"{site}/privacy-panel")
        W._dismiss_consent(page)
        assert page.evaluate("() => getComputedStyle(document.getElementById('p')).display") == "none"
    finally:
        page.close()


def test_a_block_a_check_page_or_an_empty_page_is_refused(browser, site, tmp_path):
    for path, says in (("/forbidden", "answered 403"), ("/missing", "no page at that address"),
                       ("/cf", "just a moment"), ("/empty", "almost empty")):
        dest = tmp_path / f"{path.strip('/')}.png"
        kept, why = W._shoot_one(browser, W.WebAsk(url=f"{site}{path}"), dest)
        assert not kept and says in why, (path, why)
        assert not dest.exists()


def test_the_bot_s_shot_can_be_replaced_by_his(settings):
    """A shot already in is listed with a box, and an upload under its name
    is taken (handlers: a known screen slug is accepted even with a file)."""
    ask = W.parse_web("https://www.example.com/pricing")
    custom = settings.custom_assets_dir
    custom.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), (200, 210, 220)).save(buf, format="PNG")
    (custom / f"{ask.slug}.png").write_bytes(buf.getvalue())
    W.note_ask(settings, ask, "ok")
    script, _w = parse_long_script(_script(f"[WEB: {ask.url}]"), "EXMPL", settings)
    assert [s["slug"] for s in W.page_screens(script, settings)] == [ask.slug]

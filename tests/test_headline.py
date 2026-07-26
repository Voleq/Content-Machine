"""/headline — a SHORT built around a specific news item (not a screener
mover), in three framings: company news (A), an earnings print (B), and a
macro release (C). A/B are ticker-anchored and use the Excel data; C is
index-anchored and needs no company data at all. Everything runs offline in
MOCK_MODE through the existing short renderer + JSON schema.
"""

import json
from pathlib import Path

import pytest

from bot.handlers import (
    BotCore,
    _macro_index_for,
    _strip_mode_tag,
    detect_headline_mode,
)
from pipeline.parser_short import parse_short_script
from pipeline.workspace import Workspace

CHAT = 4242
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def core(settings):
    small = settings.model_copy(update={"short_width": 540, "short_height": 960})
    return BotCore(small)


@pytest.fixture()
def xlsx_bytes() -> bytes:
    return (FIXTURES / "company_data" / "dennis_data.xlsx").read_bytes()


def _headlines() -> dict:
    return json.loads((FIXTURES / "headlines" / "headlines.json").read_text())


# ------------------------------------------------------------ mode detection

def test_mode_detection_and_tag():
    # symbol drives macro; keywords decide the rest; default is company news
    assert detect_headline_mode("AAPL", "Apple signs AI partnership with Foo") == "company"
    assert detect_headline_mode("AAPL", "Apple beats Q3 EPS, raises guidance") == "earnings"
    assert detect_headline_mode("AAPL", "CPI comes in at 3.4% vs 3.1% expected") == "macro"
    assert detect_headline_mode("macro", "stocks slip on rate fears") == "macro"
    assert detect_headline_mode("SPY", "markets mixed today") == "macro"
    # an explicit leading tag forces the framing
    assert _strip_mode_tag("[earnings] Apple tops estimates") == ("earnings", "Apple tops estimates")
    assert _strip_mode_tag("[macro] CPI hot") == ("macro", "CPI hot")
    assert _strip_mode_tag("plain headline, no tag")[0] is None
    # macro proxy: a named index passes through, plain 'macro' → broad market
    assert _macro_index_for("macro") == "SPY"
    assert _macro_index_for("QQQ") == "QQQ"


def test_usage_when_too_few_args(core):
    assert "Usage" in core.headline_command(CHAT, ["AAPL"]).text
    assert "Usage" in core.headline_command(CHAT, []).text


# ------------------------------------------------------------ C: macro mode

def _unfilled(text: str):
    import re
    return re.findall(r"\{\{(?!placeholder\}\})[a-z_]+\}\}", text)


def test_macro_produces_prompt_without_company_data(core):
    h = _headlines()["macro"]
    reply = core.headline_command(CHAT, [h["symbol"], *h["headline"].split()])
    assert reply.files and reply.files[0].name == "prompt_headline.md"
    assert "macro" in reply.text.lower() and "SPY" in reply.text
    prompt = reply.files[0].read_text()
    assert _unfilled(prompt) == [], "every placeholder filled"
    assert "## ACTIVE MODE — macro" in prompt
    assert "no single-company" in prompt and "index" in prompt.lower()
    assert h["headline"] in prompt
    # a news source is fine; a data terminal is never named
    low = prompt.lower()
    assert "refinitiv" not in low and "lseg" not in low and "capital iq" not in low
    # macro workspace is the index proxy; no company data required
    ws = Workspace.latest_for(core.settings, "SPY")
    assert ws is not None and core._company_data(ws) is None


def test_macro_intake_is_approvable_without_company_data(core):
    h = _headlines()["macro"]
    core.headline_command(CHAT, [h["symbol"], *h["headline"].split()])
    macro_json = (FIXTURES / "scripts" / "headline_macro.json").read_text()
    reply = core.intake_script(CHAT, macro_json)
    assert "SPY — SHORT — ready to render" in reply.text  # approvable, no company data
    assert reply.keyboard is not None
    ws = Workspace.latest_for(core.settings, "SPY")
    assert ws.load_short() is not None and not (ws.path / "dennis_data.xlsx").exists()


# ------------------------------------------------------- A/B: company modes

def test_company_asks_for_data_then_hands_prompt(core, xlsx_bytes):
    h = _headlines()["company"]
    reply = core.headline_command(CHAT, [h["symbol"], *h["headline"].split()])
    assert "upload dennis_data.xlsx" in reply.text.lower()  # needs the numbers
    assert not any(f.name == "prompt_headline.md" for f in reply.files)
    # uploading the data now yields the headline prompt (not the short/long pair)
    reply2 = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    assert any(f.name == "prompt_headline.md" for f in reply2.files)
    prompt = next(f for f in reply2.files if f.name == "prompt_headline.md").read_text()
    assert _unfilled(prompt) == []
    assert "## ACTIVE MODE — company" in prompt
    assert "ps_ttm" in prompt, "the ticker's numbers are injected"
    assert h["headline"] in prompt


def test_earnings_framing_with_data(core, xlsx_bytes):
    # seed the workspace with data first, then the earnings headline
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    h = _headlines()["earnings"]
    reply = core.headline_command(CHAT, [h["symbol"], *h["headline"].split()])
    assert any(f.name == "prompt_headline.md" for f in reply.files)
    prompt = next(f for f in reply.files if f.name == "prompt_headline.md").read_text()
    assert "## ACTIVE MODE — earnings" in prompt
    assert "beat" in prompt.lower() and "guidance" in prompt.lower()


def test_url_headline_is_offline_and_used_verbatim(core):
    # a URL in MOCK_MODE is never fetched (offline) — it's used as the headline
    reply = core.headline_command(CHAT, ["SPY", "https://example.com/news/cpi-hot"])
    prompt = reply.files[0].read_text()
    assert "https://example.com/news/cpi-hot" in prompt
    # The URL itself is still never fetched. Since P3.4 a MACRO headline is
    # grounded in the actual FRED series instead of an empty summary — read
    # from a fixture offline, like every other MOCK_MODE source.
    assert "THE ACTUAL SERIES" in prompt
    assert "CPIAUCSL" in prompt


def test_a_company_url_headline_still_has_no_summary_offline(core):
    """Only macro gets grounded from a free series; a company URL has nothing
    to ground it with while offline."""
    import shutil

    core.headline_command(CHAT, ["EXMPL", "https://example.com/news/x"])
    ws = core.context.get(CHAT)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    reply = core.headline_command(CHAT, ["EXMPL", "https://example.com/news/x"])
    prompt = next(f for f in reply.files if f.suffix == ".md").read_text()
    assert "no article summary" in prompt
    assert "THE ACTUAL SERIES" not in prompt


# ------------------------------------- the three framings → valid short JSON

@pytest.mark.parametrize("mode,ticker", [
    ("company", "EXMPL"), ("earnings", "EXMPL"), ("macro", "SPY"),
])
def test_framing_produces_valid_short_json(settings, mode, ticker):
    raw = (FIXTURES / "scripts" / f"headline_{mode}.json").read_text()
    script, warnings = parse_short_script(raw, settings)
    assert script.ticker == ticker
    assert script.format == "short"
    assert script.char_count <= settings.short_max_chars
    assert script.audio_script.rstrip().endswith(script.conclusion)
    assert script.missing_anchor_words() == []
    assert not any("words" in w for w in warnings)  # in the 180–210 band


# ------------------------------------- macro renders through the short kit

def test_macro_renders_without_company_data(settings, tmp_path):
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    s = settings.model_copy(update={"short_width": 540, "short_height": 960})
    s.ensure_runtime_dirs()
    raw = (FIXTURES / "scripts" / "headline_macro.json").read_text()
    script, _ = parse_short_script(raw, s)
    assert script.ticker == "SPY"
    tts = TTSEngine(s).synthesize(script.audio_script, "short")
    ws = s.workspace_dir / "SPY" / "test"
    ws.mkdir(parents=True)
    # deliberately NO dennis_data.xlsx — macro anchors on the index chart
    out, manifest = render_short(script, tts, ws, s)
    assert out.exists() and out.stat().st_size > 0
    assert json.loads(Path(manifest).read_text())["ticker"] == "SPY"

"""A6 and A5 from the chat: the voice as it lands, /voice, /voice say."""

from types import SimpleNamespace

import pytest

from bot.handlers import BotCore
from pipeline.models import WordTimestamp
from pipeline.pronounce import load_rules
from pipeline.voice_redo import sentences

CHAT = 6161


@pytest.fixture()
def core(settings):
    return BotCore(settings)


@pytest.fixture()
def short_ready(core, fixtures_dir, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx",
                       (fixtures_dir / "company_data" / "dennis_data.xlsx")
                       .read_bytes())
    core.intake_script(CHAT, short_valid_json)
    return core


def test_sentences_are_timed_by_their_words():
    text = "One two. Three four five? Six."
    words = [WordTimestamp(word=w, start=i, end=i + 0.5, char_start=a,
                           char_end=a + len(w))
             for i, (w, a) in enumerate([("One", 0), ("two.", 4),
                                         ("Three", 9), ("four", 15),
                                         ("five?", 20), ("Six.", 26)])]
    rows = sentences(words, text)
    assert [(r.index, r.text, r.start, r.end) for r in rows] == [
        (1, "One two.", 0, 1.5), (2, "Three four five?", 2, 4.5),
        (3, "Six.", 5, 5.5)]


def test_no_voice_yet(short_ready):
    reply = short_ready.voice_listing(CHAT)
    assert "No voice yet" in reply.text and "Nothing has been spent" in reply.text


def test_listing_numbers_sentences_with_times(short_ready):
    ws = short_ready.context.get(CHAT)
    script = ws.load_short()
    short_ready.tts.synthesize(script.audio_script, "short",
                               events=script.inline_events)
    reply = short_ready.voice_listing(CHAT)
    assert reply.files and reply.files[0].name == "audio.m4a"
    assert "\n1 · 0:" in reply.text
    assert "/voice redo N" in reply.text


def test_say_adds_and_names_sentences(short_ready):
    ws = short_ready.context.get(CHAT)
    script = ws.load_short()
    short_ready.tts.synthesize(script.audio_script, "short",
                               events=script.inline_events)
    first = script.audio_script.split()[0].strip(".,")
    reply = short_ready.say_command(CHAT, f"{first} => fixed")
    assert f"✅ {first} is said “fixed”" in reply.text
    assert "sentence" in reply.text and "/voice redo 1" in reply.text
    assert any(r.word == first for r in load_rules(short_ready.settings))
    assert "• EBITDA → ee-bit-dah" in short_ready.say_command(CHAT).text


def test_unsay(core):
    core.say_command(CHAT, "EXMPL => example")
    assert "said as written" in core.unsay_command(["EXMPL"]).text
    assert "No rule" in core.unsay_command(["EXMPL"]).text


def test_voice_pushed_once_when_fresh(core, tmp_path):
    pushed = []
    core.file_pusher = lambda path, caption="": pushed.append((path, caption))
    job = SimpleNamespace(ticker="EXMPL")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"x")
    core._announce_voice(job, SimpleNamespace(cached=False, tier="paid",
                                              audio_path=audio), "long")
    core._announce_voice(job, SimpleNamespace(cached=True, tier="paid",
                                              audio_path=audio), "long")
    core._announce_voice(job, SimpleNamespace(cached=False, tier="local",
                                              audio_path=audio), "long")
    assert len(pushed) == 1
    assert "/cancel EXMPL" in pushed[0][1]

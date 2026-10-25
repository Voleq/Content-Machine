"""`/admin keys`: one free call per service, and what each one answered."""

import json

from pipeline.cost import SpendLedger
from pipeline.key_check import BAD, OK, SKIP, check_keys, keys_text

KEYS = {"elevenlabs_api_key": "el-SECRET-1", "eleven_voice_id_short": "vShort",
        "eleven_voice_id_long": "vLong", "pexels_api_key": "px-SECRET-2",
        "giphy_api_key": "gi-SECRET-3", "tenor_api_key": "te-SECRET-4",
        "fred_api_key": "fr-SECRET-5", "telegram_bot_token": "123:tg-SECRET-6",
        "openai_api_key": "oa-SECRET-7", "github_models_token": "gh-SECRET-8",
        "sec_user_agent": "Dennis Reads research@channel.example"}


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


def _with(settings, **over):
    return settings.model_copy(update={**KEYS, **over})


def _fake(answers, calls=None):
    """`answers`: url fragment -> Resp, first match wins."""
    def get(url, **kw):
        if calls is not None:
            calls.append((url, kw))
        for frag, resp in answers.items():
            if frag in url:
                return resp
        return Resp(200)
    return get


def _rows(settings, answers, calls=None):
    return {r.name: r for r in check_keys(settings, get=_fake(answers, calls))}


def test_every_set_key_that_works_is_ok_and_says_what_it_found(settings):
    s = _with(settings)
    rows = _rows(s, {
        "/v1/user/subscription": Resp(200, {"character_count": 18800,
                                            "character_limit": 100000,
                                            "next_character_count_reset_unix": 1798761600}),
        "/v1/voices/vShort": Resp(200, {"name": "Dennis short"}),
        "/v1/voices/vLong": Resp(200, {"name": "Dennis long"}),
        "pexels": Resp(200, {}, {"X-Ratelimit-Remaining": "19950"}),
        "getMe": Resp(200, {"ok": True, "result": {"username": "dennis_bot"}}),
        "api.github.com/user": Resp(200, {"login": "someone"}),
    })
    assert rows["ElevenLabs"].state == OK
    assert rows["ElevenLabs"].detail.startswith("81,200 of 100,000 characters left")
    assert rows["ElevenLabs short voice"].detail == "Dennis short"
    assert rows["ElevenLabs long voice"].detail == "Dennis long"
    assert rows["Pexels"].detail == "19,950 calls left this month"
    assert rows["Telegram"].detail == "@dennis_bot"
    assert rows["GitHub Models"].detail == "a token for someone"
    for name in ("Giphy", "Tenor", "FRED", "OpenAI", "SEC"):
        assert rows[name].state == OK, name
    assert rows["YouTube"].state == SKIP
    assert rows["Google Drive"].state == SKIP


def test_a_refused_key_and_a_foreign_voice_are_bad(settings):
    s = _with(settings, eleven_voice_id_long="vShort")
    rows = _rows(s, {
        "/v1/voices/": Resp(400, {"detail": {"status": "voice_not_found"}}),
        "giphy": Resp(401), "tenor": Resp(400), "stlouisfed": Resp(400),
        "sec.gov": Resp(403), "openai": Resp(401),
    })
    assert rows["ElevenLabs"].state == OK
    # One id for both lanes is asked about once.
    voice = rows["ElevenLabs short and long voice"]
    assert voice.state == BAD and "not a voice this account can use" in voice.detail
    for name in ("Giphy", "Tenor", "FRED", "OpenAI"):
        assert rows[name].state == BAD and "refused the key" in rows[name].detail
    assert rows["SEC"].state == BAD and "SEC_USER_AGENT" in rows["SEC"].detail


def test_a_key_scoped_not_to_read_the_account_still_counts_as_working(settings):
    scoped = Resp(401, {"detail": {"status": "missing_permissions"}})
    rows = _rows(_with(settings), {"/v1/user/subscription": scoped,
                                   "/v1/voices/": scoped})
    assert rows["ElevenLabs"].state == OK
    assert "cannot be shown" in rows["ElevenLabs"].detail
    assert rows["ElevenLabs short voice"].state == SKIP


def test_a_wrong_eleven_key_stops_before_the_voices(settings):
    calls = []
    rows = _rows(_with(settings), {"/v1/user/subscription": Resp(
        401, {"detail": {"status": "invalid_api_key"}})}, calls)
    assert rows["ElevenLabs"].state == BAD
    assert not any("/v1/voices/" in url for url, _ in calls)


def test_an_unset_key_is_skipped_and_nothing_is_asked(settings):
    calls = []
    rows = _rows(settings, {}, calls)
    assert calls == []
    assert {r.state for r in rows.values()} == {SKIP}
    assert "ELEVENLABS_API_KEY is not set" in rows["ElevenLabs"].detail


def test_an_unreachable_service_is_bad_and_the_rest_still_answer(settings):
    def get(url, **kw):
        if "giphy" in url:
            raise ConnectionError(f"could not reach {url}")
        return Resp(200)
    rows = {r.name: r for r in check_keys(_with(settings), get=get)}
    assert rows["Giphy"].state == BAD
    assert rows["Giphy"].detail == "could not be reached (ConnectionError)"
    assert rows["Tenor"].state == OK


def test_no_key_ever_reaches_the_text(settings):
    """Telegram's key is in its URL, and a service may echo a key back."""
    s = _with(settings)

    def get(url, **kw):
        if "getMe" in url:
            return Resp(200, {"result": {"username": s.telegram_bot_token}})
        return Resp(500)
    text = keys_text(s, get=get)
    for key in ("el-SECRET-1", "px-SECRET-2", "gi-SECRET-3", "te-SECRET-4",
                "fr-SECRET-5", "tg-SECRET-6", "oa-SECRET-7", "gh-SECRET-8"):
        assert key not in text


def test_the_pexels_call_is_counted_like_any_other(settings):
    s = _with(settings)
    before = SpendLedger(s).pexels_calls_this_month()
    check_keys(s, get=_fake({}))
    assert SpendLedger(s).pexels_calls_this_month() == before + 1


def test_the_reply_leads_with_what_needs_fixing(settings):
    text = keys_text(_with(settings), get=_fake({"giphy": Resp(401)}))
    assert text.splitlines()[0] == "🔑 1 key(s) to fix before a real video."
    assert "❌ Giphy: refused the key (401)" in text
    ok = keys_text(_with(settings), get=_fake({}))
    assert ok.splitlines()[0] == "🔑 every key that is set works."


def test_a_self_hosted_telegram_server_is_the_one_asked(settings):
    """After the bot logs out of the cloud server, asking the cloud for
    getMe either reports a refused key or logs the bot back in there."""
    calls: list = []
    s = _with(settings, telegram_api_base_url="http://127.0.0.1:8081/")
    rows = _rows(s, {"getMe": Resp(200, {"result": {"username": "dennis_bot"}})},
                 calls)
    assert rows["Telegram"].state == OK
    asked = [u for u, _ in calls if "getMe" in u]
    assert asked == ["http://127.0.0.1:8081/bot123:tg-SECRET-6/getMe"]


# --------------------------------------------------------------------------
# /cost: the account's own count of the characters left (improvement 14).
# --------------------------------------------------------------------------

_SUB = {"/v1/user/subscription": Resp(200, {
    "character_count": 18800, "character_limit": 100000,
    "next_character_count_reset_unix": 1798761600})}


def test_cost_asks_the_account_for_the_characters_left_once_in_a_while(
        settings, monkeypatch):
    from pipeline import key_check

    monkeypatch.setattr(key_check, "_characters", {})
    live = _with(settings, mock_mode=False)
    calls: list = []
    get = _fake(_SUB, calls)
    assert key_check.characters_left(live, get=get).startswith(
        "81,200 of 100,000 characters left, resets")
    assert key_check.characters_left(live, get=get).startswith("81,200")
    assert len(calls) == 1, "a /cost tapped twice is not two questions"
    assert "el-SECRET-1" not in str(calls[0][0])


def test_no_question_is_asked_offline_or_without_a_key(settings, monkeypatch):
    from pipeline import key_check

    monkeypatch.setattr(key_check, "_characters", {})
    calls: list = []
    assert key_check.characters_left(_with(settings, mock_mode=True),
                                     get=_fake(_SUB, calls)) == ""
    assert key_check.characters_left(
        _with(settings, mock_mode=False, elevenlabs_api_key=""),
        get=_fake(_SUB, calls)) == ""
    assert calls == []


def test_a_refused_key_reads_as_not_read_and_never_shows_the_key(
        settings, monkeypatch):
    from pipeline import key_check

    monkeypatch.setattr(key_check, "_characters", {})
    got = key_check.characters_left(
        _with(settings, mock_mode=False),
        get=_fake({"/v1/user/subscription": Resp(401, {"detail": "bad"})}))
    assert got.startswith("not read (refused the key (401))")


def test_the_cost_report_carries_the_count_and_the_model_s_cap(
        settings, monkeypatch):
    """Improvements 14 and 15: the account's figure beside the ledger's, and
    the hosted model's spend against its own cap."""
    from bot.handlers import BotCore
    from pipeline import key_check

    monkeypatch.setattr(key_check, "_characters", {})
    monkeypatch.setattr(key_check, "_get", _fake(_SUB))
    live = _with(settings, mock_mode=False, llm_monthly_cap_usd=5.0)
    core = BotCore(live)
    core.ledger.record_llm(0.25)
    text = core.cost_text()
    assert "🎙 ElevenLabs: 81,200 of 100,000 characters left" in text
    assert "Hosted AI model: $0.25 of $5.00 cap (LLM_MONTHLY_CAP)" in text
    assert "🎙" not in BotCore(settings).cost_text()


def _drive_settings(settings, tmp_path, monkeypatch, **over):
    from pipeline.delivery import GDriveBackend

    creds = tmp_path / "gdrive.json"
    creds.write_text('{"refresh_token": "r"}', encoding="utf-8")
    monkeypatch.setattr(GDriveBackend, "_token", lambda self: "ya29.ACCESS")
    return _with(settings, gdrive_credentials=str(creds),
                 delivery_backend="gdrive", **over)


def test_drive_is_asked_for_the_folder_a_final_goes_into(settings, tmp_path, monkeypatch):
    """Drive had no row: a sign-in that did not take showed first as a final
    kept on the PC instead of delivered."""
    s = _drive_settings(settings, tmp_path, monkeypatch)
    calls = []
    rows = _rows(s, {"drive/v3/files": Resp(200, {"files": [{"id": "f1"}]})}, calls)
    assert rows["Google Drive"].state == OK
    assert rows["Google Drive"].detail == "delivers into its Dennis folder"
    asked = [kw for url, kw in calls if "drive/v3/files" in url]
    assert asked and asked[0]["headers"]["Authorization"] == "Bearer ya29.ACCESS"
    assert "'Dennis'" in asked[0]["params"]["q"]
    assert "ya29" not in keys_text(s, get=_fake({"drive/v3/files": Resp(200, {})}))

    fresh = _rows(s, {"drive/v3/files": Resp(200, {"files": []})})
    assert "makes its Dennis folder with the first final" in fresh["Google Drive"].detail
    idle = _rows(s.model_copy(update={"delivery_backend": "telegram"}),
                 {"drive/v3/files": Resp(200, {"files": [{"id": "f1"}]})})
    assert "DELIVERY_BACKEND is not gdrive" in idle["Google Drive"].detail


def test_a_folder_made_by_hand_and_a_failed_sign_in_are_bad(settings, tmp_path, monkeypatch):
    from pipeline.delivery import GDriveBackend

    s = _drive_settings(settings, tmp_path, monkeypatch, gdrive_root_folder_id="byhand")
    rows = _rows(s, {"drive/v3/files/byhand": Resp(404)})
    assert rows["Google Drive"].state == BAD
    assert "leave that blank" in rows["Google Drive"].detail

    def refused(self):
        raise RuntimeError("invalid_grant")
    monkeypatch.setattr(GDriveBackend, "_token", refused)
    rows = _rows(s, {})
    assert rows["Google Drive"].state == BAD
    assert rows["Google Drive"].detail == "the credentials did not sign in: RuntimeError"

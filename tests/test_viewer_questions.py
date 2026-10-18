"""S7: viewer questions, a closing section of the long, off by default."""

from datetime import datetime, timezone

from pipeline.viewer_questions import (fallback_questions, load_questions,
                                       questions_block, questions_due,
                                       refresh_questions)
from pipeline.youtube import VideoLog, VideoRecord

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
ON = {"viewer_questions": True}


class FakeClient:
    def __init__(self, comments):
        self.comments = comments
        self.asked: list[str] = []

    def top_comments(self, video_id, n=50):
        self.asked.append(video_id)
        return self.comments.get(video_id, [])


def _video(vid, privacy="public", uploaded="2026-10-10T10:00:00+00:00"):
    return VideoRecord(ticker="EXMPL", video_id=vid, title="EXMPL — debt",
                       privacy=privacy, uploaded_at=uploaded,
                       workdate="2026-10-10", fmt="long")


def test_off_by_default_block(settings):
    assert settings.viewer_questions is False
    assert questions_block(settings) == ""
    assert not questions_due(settings, NOW)
    client = FakeClient({"aaaaaaaaaaa": ["Why is the debt so high?"]})
    VideoLog(settings).record(_video("aaaaaaaaaaa"))
    assert refresh_questions(settings, client, NOW) == 0
    assert client.asked == [], "nothing is read while the switch is off"


def test_on_but_empty_is_blank(settings):
    on = settings.model_copy(update=ON)
    assert questions_block(on) == ""
    assert questions_due(on, NOW)


def test_refresh_fallback_picks_questions(settings):
    on = settings.model_copy(update=ON)
    VideoLog(on).record(_video("aaaaaaaaaaa"))
    client = FakeClient({"aaaaaaaaaaa": [
        "Great video. Why does the debt matter if they have cash?",
        "first",
        "check my channel https://example.com?",
        "?",
    ]})
    assert refresh_questions(on, client, NOW) == 1
    rows = load_questions(on)["questions"]
    assert rows == [{"text": "Why does the debt matter if they have cash?",
                     "video_id": "aaaaaaaaaaa", "ticker": "EXMPL"}]
    assert not questions_due(on, NOW)


def test_only_public_videos_read(settings):
    on = settings.model_copy(update=ON)
    log = VideoLog(on)
    log.record(_video("aaaaaaaaaaa", privacy="unlisted"))
    log.record(_video("bbbbbbbbbbb", uploaded="2026-06-01T10:00:00+00:00"))
    log.record(_video("ccccccccccc"))
    client = FakeClient({})
    refresh_questions(on, client, NOW)
    assert client.asked == ["ccccccccccc"], "unlisted and old videos stay out"


def test_block_lists_questions(settings):
    on = settings.model_copy(update=ON)
    VideoLog(on).record(_video("aaaaaaaaaaa"))
    refresh_questions(on, FakeClient({"aaaaaaaaaaa": [
        "How do they pay the dividend with no cash?"]}), NOW)
    block = questions_block(on)
    assert block.startswith("### VIEWER QUESTIONS — CLOSING SECTION")
    assert "“How do they pay the dividend with no cash?” (under the EXMPL " \
           "video)" in block
    assert "never name the commenter" in block
    assert "before the sign-off" in block
    assert questions_block(settings) == "", "switching off hides it again"


def test_fallback_keeps_one_question_per_comment():
    got = fallback_questions(["Why? Because? Really, how is margin 40%?",
                              "How is margin 40% when peers are at 12%?"])
    # Too short to be a question ("Why?") is skipped; one per comment.
    assert got == ["Really, how is margin 40%?",
                   "How is margin 40% when peers are at 12%?"]

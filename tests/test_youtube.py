"""YouTube upload + retention feedback (P3.5) and scheduled publishing (5b).

No credentials here and no channel to upload to, so `YouTubeClient` itself is
verified on the real machine. What is tested is everything that decides what
gets published and when: the privacy guarantee, the publish-time parsing, the
package validation that would otherwise fail after a forty-minute render, and
the retention mapping that turns a ratio through the video into "chapter three
is where they leave".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipeline.publish import UploadPackage
from pipeline.youtube import (
    TITLE_MAX,
    UploadError,
    VideoLog,
    VideoRecord,
    YouTubeUnavailable,
    available,
    build_body,
    chapter_type_evidence,
    map_retention_to_chapters,
    pull_retention,
    resolve_publish_at,
    retention_report,
    upload_video,
    validate_package,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def package():
    return UploadPackage(
        ticker="EXMPL",
        titles=["EXMPL: cheap, or a trap?", "The EXMPL problem"],
        description="00:00 Cold open\n02:30 The numbers\n11:00 The verdict",
        tags=["stocks", "value investing", "EXMPL"],
        pinned_comment="Not advice. Opinion and entertainment.",
    )


class FakeClient:
    def __init__(self, video_id: str = "vid123", rows=None, boom: str = ""):
        self.video_id = video_id
        self.rows = rows or []
        self.boom = boom
        self.body: dict | None = None
        self.comments: list[str] = []

    def upload(self, path: Path, body: dict) -> str:
        if self.boom == "upload":
            raise RuntimeError("quota exceeded")
        self.body = body
        return self.video_id

    def comment(self, video_id: str, text: str) -> None:
        if self.boom == "comment":
            raise RuntimeError("comments are disabled")
        self.comments.append(text)

    def retention(self, video_id, start, end):
        if self.boom == "retention":
            raise RuntimeError("no data yet")
        return self.rows


@pytest.fixture()
def video(tmp_path):
    f = tmp_path / "long_final.mp4"
    f.write_bytes(b"not really an mp4")
    return f


# --------------------------------------------------------------------------
# Never public.
# --------------------------------------------------------------------------


def test_an_upload_is_private_by_default(settings, package, video):
    """Nothing goes public straight out of a machine."""
    client = FakeClient()
    record = upload_video(video, package, settings, client=client, now=NOW)
    assert client.body["status"]["privacyStatus"] == "private"
    assert "publishAt" not in client.body["status"]
    assert record.privacy == "private"


def test_a_scheduled_upload_is_still_private_with_a_publish_time(settings,
                                                                package, video):
    """That is how the API expresses a schedule: private + publishAt."""
    client = FakeClient()
    when = "2026-08-07 18:00"
    record = upload_video(video, package, settings, publish_at=when,
                          client=client, now=NOW)
    status = client.body["status"]
    assert status["privacyStatus"] == "private"
    assert status["publishAt"].startswith("2026-08-07T18:00")
    assert status["publishAt"].endswith("Z")
    assert record.privacy == "scheduled"


def test_public_is_never_requested(settings, package, video):
    client = FakeClient()
    upload_video(video, package, settings, client=client, now=NOW)
    assert "public" not in json.dumps(client.body)


# --------------------------------------------------------------------------
# Publish times (5b) — batch on Sunday, publish Friday.
# --------------------------------------------------------------------------


def test_several_formats_are_accepted():
    for text in ("2026-08-07 18:00", "2026-08-07T18:00", "2026/08/07 18:00",
                 "2026-08-07T18:00:00"):
        got = resolve_publish_at(text, NOW)
        assert got.year == 2026 and got.month == 8 and got.day == 7, text


def test_a_bare_date_is_accepted():
    got = resolve_publish_at("2026-08-07", NOW)
    assert got.date().isoformat() == "2026-08-07"


def test_no_time_means_no_schedule():
    assert resolve_publish_at(None) is None
    assert resolve_publish_at("") is None


def test_a_past_time_is_refused_rather_than_publishing_now():
    """"I meant last Friday" must not put a video live this second."""
    with pytest.raises(ValueError) as e:
        resolve_publish_at("2020-01-01 10:00", NOW)
    assert "in the past" in str(e.value)


def test_nonsense_is_refused_with_an_example():
    with pytest.raises(ValueError) as e:
        resolve_publish_at("next friday-ish", NOW)
    assert "2026-08-07" in str(e.value)


def test_two_videos_can_be_scheduled_for_different_days(settings, package, video):
    """The actual workflow: render two on a Sunday, space them out."""
    upload_video(video, package, settings, publish_at="2026-08-07 18:00",
                 client=FakeClient("v1"), now=NOW)
    upload_video(video, package, settings, publish_at="2026-08-09 12:00",
                 client=FakeClient("v2"), now=NOW)
    rows = VideoLog(settings).scheduled()
    assert [r.video_id for r in rows] == ["v1", "v2"], "sorted by publish time"


# --------------------------------------------------------------------------
# Validation — cheaper here than after a 40-minute render.
# --------------------------------------------------------------------------


def test_an_over_long_title_is_caught_before_uploading(settings, package, video):
    package.titles = ["x" * (TITLE_MAX + 20)]
    with pytest.raises(UploadError) as e:
        upload_video(video, package, settings, client=FakeClient(), now=NOW)
    assert "title" in str(e.value)


def test_the_usual_rejections_are_all_named():
    problems = validate_package("", "x" * 6000, ["y" * 600])
    joined = " ".join(problems)
    assert "empty" in joined and "description" in joined and "tags" in joined


def test_angle_brackets_in_a_title_are_caught():
    assert any("angle brackets" in p
               for p in validate_package("<b>EXMPL</b>", "d", []))


def test_a_clean_package_has_no_problems(package):
    assert validate_package(package.titles[0], package.description,
                            package.tags) == []


def test_a_missing_file_is_refused(settings, package, tmp_path):
    with pytest.raises(UploadError) as e:
        upload_video(tmp_path / "nope.mp4", package, settings,
                     client=FakeClient(), now=NOW)
    assert "no file" in str(e.value)


# --------------------------------------------------------------------------
# The pinned comment must not be able to lose the video.
# --------------------------------------------------------------------------


def test_the_pinned_comment_is_posted(settings, package, video):
    client = FakeClient()
    upload_video(video, package, settings, client=client, now=NOW)
    assert client.comments == [package.pinned_comment]


def test_a_failed_comment_does_not_fail_the_upload(settings, package, video):
    """The video is up. A comment is not worth losing it over."""
    client = FakeClient(boom="comment")
    record = upload_video(video, package, settings, client=client, now=NOW)
    assert record.video_id == "vid123"


# --------------------------------------------------------------------------
# The record.
# --------------------------------------------------------------------------


def test_what_was_published_is_remembered(settings, package, video):
    upload_video(video, package, settings, client=FakeClient(), now=NOW,
                 workdate="2026-07-27", chapters=[("00:00", "Cold open")],
                 duration_s=900.0)
    stored = VideoLog(settings).get("vid123")
    assert stored is not None
    assert stored.ticker == "EXMPL"
    assert stored.duration_s == 900.0
    assert stored.url() == "https://youtu.be/vid123"


def test_the_record_survives_a_restart(settings, package, video):
    upload_video(video, package, settings, client=FakeClient(), now=NOW)
    assert VideoLog(settings).for_ticker("EXMPL")


def test_no_credentials_means_unavailable_not_a_crash(settings):
    ok, why = available(settings)
    assert not ok
    assert "MOCK_MODE" in why or "YOUTUBE" in why

    live = settings.model_copy(update={"mock_mode": False,
                                       "youtube_enabled": True,
                                       "youtube_credentials": ""})
    ok, why = available(live)
    assert not ok and "YOUTUBE_CREDENTIALS" in why


def test_uploading_without_credentials_raises_the_right_type(settings, package,
                                                             video):
    with pytest.raises(YouTubeUnavailable):
        upload_video(video, package, settings, now=NOW)


# --------------------------------------------------------------------------
# Retention mapped onto chapters — the whole point of the feedback loop.
# --------------------------------------------------------------------------


CHAPTERS = [("00:00", "Cold open"), ("02:00", "The numbers"),
            ("06:00", "The verdict")]


def _rows(pairs):
    return [{"elapsed_ratio": r, "watch_ratio": w} for r, w in pairs]


def test_a_ratio_through_the_video_becomes_a_named_chapter():
    """Without the timestamps and the duration the API's numbers say nothing
    actionable."""
    rows = _rows([(0.0, 1.0), (0.1, 0.95), (0.3, 0.7), (0.5, 0.6), (0.9, 0.4)])
    mapped = map_retention_to_chapters(rows, CHAPTERS, duration_s=600.0)
    assert [m["chapter"] for m in mapped] == ["Cold open", "The numbers",
                                              "The verdict"]
    assert mapped[0]["avg_watch_ratio"] > mapped[-1]["avg_watch_ratio"]


def test_the_drop_across_a_chapter_is_recorded_not_just_the_level():
    """A chapter that starts low may simply be late in the video; the drop is
    what says the chapter itself lost them."""
    rows = _rows([(0.0, 1.0), (0.15, 0.98),          # cold open: flat
                  (0.35, 0.90), (0.5, 0.55),          # numbers: falls off
                  (0.75, 0.50), (0.95, 0.48)])        # verdict: flat but low
    mapped = map_retention_to_chapters(rows, CHAPTERS, duration_s=600.0)
    by_name = {m["chapter"]: m for m in mapped}
    assert by_name["The numbers"]["drop"] > by_name["The verdict"]["drop"]


def test_missing_inputs_produce_nothing_rather_than_a_fake_reading():
    assert map_retention_to_chapters([], CHAPTERS, 600.0) == []
    assert map_retention_to_chapters(_rows([(0.1, 1.0)]), [], 600.0) == []
    assert map_retention_to_chapters(_rows([(0.1, 1.0)]), CHAPTERS, 0.0) == []


def test_timestamps_with_hours_are_parsed():
    chapters = [("00:00", "A"), ("01:05:00", "B")]
    rows = _rows([(0.1, 1.0), (0.9, 0.5)])
    mapped = map_retention_to_chapters(rows, chapters, duration_s=7800.0)
    assert [m["chapter"] for m in mapped] == ["A", "B"]
    assert mapped[1]["start_s"] == 3900.0


def test_the_report_names_the_worst_chapter():
    rows = _rows([(0.0, 1.0), (0.15, 0.98), (0.35, 0.90), (0.5, 0.55),
                  (0.75, 0.50), (0.95, 0.48)])
    mapped = map_retention_to_chapters(rows, CHAPTERS, 600.0)
    text = retention_report(mapped)
    assert "Biggest drop-off" in text
    assert "The numbers" in text


def test_an_empty_report_says_to_wait():
    assert "day or two" in retention_report([])


def test_pulling_retention_stores_it_against_the_video(settings, package, video):
    upload_video(video, package, settings, client=FakeClient(), now=NOW,
                 chapters=CHAPTERS, duration_s=600.0)
    client = FakeClient(rows=_rows([(0.0, 1.0), (0.5, 0.6), (0.9, 0.4)]))
    payload = pull_retention("vid123", settings, client=client, today=NOW)
    assert payload["status"] == "ok"
    stored = VideoLog(settings).get("vid123")
    assert stored.retention["chapters"], "not written back to the record"


def test_a_video_too_new_for_data_is_reported_not_raised(settings, package,
                                                         video):
    """Feedback is a loop, not a dependency."""
    upload_video(video, package, settings, client=FakeClient(), now=NOW,
                 chapters=CHAPTERS, duration_s=600.0)
    payload = pull_retention("vid123", settings,
                             client=FakeClient(boom="retention"), today=NOW)
    assert payload["status"] == "unavailable"
    assert "no data yet" in payload["reason"]


def test_an_unknown_video_is_reported(settings):
    assert pull_retention("nope", settings, client=FakeClient())["status"] == \
        "unknown video"


def test_the_same_chapter_across_videos_becomes_evidence(settings):
    """One video's drop-off is an anecdote; the same chapter type dropping
    across several is the thing worth acting on."""
    log_ = VideoLog(settings)
    for i, ratio in enumerate([0.30, 0.34, 0.28]):
        log_.record(VideoRecord(
            ticker=f"T{i}", video_id=f"v{i}", title="t", privacy="private",
            retention={"chapters": [
                {"chapter": "The valuation", "avg_watch_ratio": ratio},
                {"chapter": "Cold open", "avg_watch_ratio": 0.95},
            ]}))
    evidence = chapter_type_evidence(settings)
    assert evidence[0]["chapter"] == "the valuation", evidence
    assert evidence[0]["videos"] == 3
    assert evidence[-1]["chapter"] == "cold open"


# --------------------------------------------------------------------------
# The bot surface.
# --------------------------------------------------------------------------


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def test_upload_without_credentials_hands_back_the_package(core, settings,
                                                           long_valid_text):
    import shutil

    core.start_lane(5, "long", "EXMPL")
    ws = core.context.get(5)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    core.intake_script(5, long_valid_text)
    (ws.path / "long_final.mp4").write_bytes(b"x")

    reply = core.upload_command(["EXMPL"])
    assert "can't upload" in reply.text
    assert "by hand" in reply.text


def test_upload_refuses_a_past_publish_time(core):
    reply = core.upload_command(["EXMPL", "2020-01-01", "10:00"])
    assert "in the past" in reply.text


def test_upload_needs_a_finished_render(core, settings):
    core.start_lane(6, "long", "EXMPL")
    assert "No finished" in core.upload_command(["EXMPL"]).text


def test_scheduled_is_empty_until_something_is(core):
    assert "nothing scheduled" in core.scheduled_text().text


def test_scheduled_lists_what_is_queued(core, settings, package, video):
    upload_video(video, package, settings, publish_at="2026-08-07 18:00",
                 client=FakeClient(), now=NOW)
    text = core.scheduled_text().text
    assert "EXMPL" in text and "2026-08-07" in text


def test_retention_with_nothing_published_explains_itself(core):
    assert "No retention data" in core.retention_text([]).text
    assert "Nothing published" in core.retention_text(["EXMPL"]).text

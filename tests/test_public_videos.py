"""S12: what is out and public, and marking a video by hand."""

from datetime import datetime, timezone

import pytest

from bot.handlers import BotCore
from pipeline.youtube import (VideoLog, VideoRecord, is_public,
                              parse_video_id, public_videos,
                              public_videos_block)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
VID = "dQw4w9WgXcQ"


def test_parse_video_id_forms():
    assert parse_video_id(f"https://youtu.be/{VID}") == VID
    assert parse_video_id(f"https://www.youtube.com/watch?v={VID}&t=3") == VID
    assert parse_video_id(f"https://youtube.com/shorts/{VID}?si=x") == VID
    assert parse_video_id(VID) == VID
    assert parse_video_id("EXMPL") == ""
    assert parse_video_id("https://example.com/watch") == ""


def _rec(privacy, publish_at="", vid=VID, fmt="long"):
    return VideoRecord(ticker="EXMPL", video_id=vid, title="EXMPL — the debt",
                       privacy=privacy, publish_at=publish_at,
                       uploaded_at="2026-10-01T10:00:00+00:00",
                       workdate="2026-10-01", fmt=fmt)


def test_unlisted_is_not_public():
    assert not is_public(_rec("unlisted"), NOW)
    assert not is_public(_rec("private"), NOW)
    assert is_public(_rec("public"), NOW)


def test_passed_schedule_is_public():
    assert is_public(_rec("scheduled", "2026-10-10T17:00:00+00:00"), NOW)
    assert not is_public(_rec("scheduled", "2026-10-20T17:00:00+00:00"), NOW)


def test_block_empty_and_listed(settings):
    assert "no public videos yet" in public_videos_block(settings, NOW)
    log = VideoLog(settings)
    log.record(_rec("public"))
    log.record(_rec("unlisted", vid="aaaaaaaaaaa"))
    block = public_videos_block(settings, NOW)
    assert "EXMPL (long, 2026-10-01) — EXMPL — the debt" in block
    assert block.count("\n- ") == 1, "the unlisted one stays out"
    assert "never as a call" in block
    assert [v.video_id for v in public_videos(settings, NOW)] == [VID]


@pytest.fixture()
def core(settings, workspace):
    return BotCore(settings)


def test_mark_then_public_updates_in_place(core, settings):
    reply = core.mark_upload(["EXMPL", "long", f"https://youtu.be/{VID}",
                              "unlisted"])
    assert "recorded EXMPL long (2026-07-01) as unlisted" in reply
    assert not public_videos(settings)
    reply = core.mark_upload(["EXMPL", VID, "public"])
    assert "now on record as public" in reply
    rows = VideoLog(settings).all()
    assert len(rows) == 1 and rows[0].privacy == "public"
    assert rows[0].fmt == "long" and rows[0].workdate == "2026-07-01"


def test_mark_needs_a_link(core):
    assert core.mark_upload(["EXMPL", "long"]).startswith("usage:")
    assert core.mark_upload([]).startswith("usage:")



def test_a_dated_mark_lands_on_that_folder(core, settings):
    """The page's Upload step names the folder; the newest is a later one."""
    (settings.workspace_dir / "EXMPL" / "2026-07-09").mkdir(parents=True)
    reply = core.mark_upload(["EXMPL@2026-07-01", "long",
                              f"https://youtu.be/{VID}", "unlisted"])
    assert "recorded EXMPL long (2026-07-01)" in reply
    assert VideoLog(settings).all()[0].workdate == "2026-07-01"

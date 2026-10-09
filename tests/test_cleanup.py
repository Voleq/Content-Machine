from datetime import date, timedelta

from pipeline.cleanup import cleanup
from pipeline.workspace import Workspace


def _fill(ws: Workspace):
    (ws.path / "short_final.mp4").write_bytes(b"x" * 1000)
    (ws.path / "render_short").mkdir()
    (ws.path / "render_short" / "row_0.mov").write_bytes(b"y" * 500)
    (ws.path / "script_short.json").write_text("{}", encoding="utf-8")
    (ws.path / "dennis_data.xlsx").write_bytes(b"z")


def test_cleanup_prunes_old_renders_keeps_records(settings):
    old = (date.today() - timedelta(days=30)).isoformat()
    fresh = date.today().isoformat()
    old_ws = Workspace(settings, "OLD", old).create()
    fresh_ws = Workspace(settings, "FRESH", fresh).create()
    _fill(old_ws)
    _fill(fresh_ws)

    stats = cleanup(settings)  # retention default 14d
    assert stats["files_removed"] >= 1 and stats["dirs_removed"] >= 1

    # old: renders gone, records kept (cooldown history + audit trail)
    assert not (old_ws.path / "short_final.mp4").exists()
    assert not (old_ws.path / "render_short").exists()
    assert (old_ws.path / "script_short.json").exists()
    assert (old_ws.path / "dennis_data.xlsx").exists()
    # fresh: untouched
    assert (fresh_ws.path / "short_final.mp4").exists()
    assert (fresh_ws.path / "render_short").exists()


def test_cleanup_dry_run_touches_nothing(settings):
    old = (date.today() - timedelta(days=30)).isoformat()
    ws = Workspace(settings, "OLD", old).create()
    _fill(ws)
    stats = cleanup(settings, dry_run=True)
    assert stats["dry_run"] and stats["files_removed"] >= 1
    assert (ws.path / "short_final.mp4").exists()


def test_cleanup_never_touches_cache(settings):
    (settings.cache_dir / "tts").mkdir(parents=True)
    keep = settings.cache_dir / "tts" / "audio.m4a"
    keep.write_bytes(b"cached")
    cleanup(settings)
    assert keep.exists(), "caches are what make re-runs free — never pruned"


def test_the_local_backend_s_delivered_copy_is_kept_by_default(settings):
    """`_delivered/` is only ever written by the local backend, where it is
    the one copy of the finished video; it used to be pruned as a duplicate
    of something archived remotely."""
    old = (date.today() - timedelta(days=30)).isoformat()
    copy = settings.workspace_dir / "_delivered" / "OLD" / old / "long_final.mp4"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"x")
    cleanup(settings)
    assert copy.exists()


def test_rebuildable_caches_are_pruned_and_the_voice_never_is(settings):
    import os
    import time

    stale = time.time() - 120 * 86400
    shot = settings.cache_dir / "dennis3d" / "abc123"
    shot.mkdir(parents=True)
    (shot / "layer.mov").write_bytes(b"x")
    voice = settings.cache_dir / "tts" / "k" / "audio.m4a"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"paid")
    for p in (shot / "layer.mov", shot, voice, voice.parent):
        os.utime(p, (stale, stale))
    stats = cleanup(settings)
    assert stats["cache_entries_removed"] == 1
    assert not shot.exists()
    assert voice.exists(), "the voice cache was paid for"

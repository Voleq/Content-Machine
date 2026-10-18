"""A8, A9: the room and the de-esser on the voice, both off by default."""

from pipeline.render_common import (DEESSER, ROOM_ECHO, AudioTrack,
                                    CompositeSpec, audio_graph, ffprobe_duration,
                                    render_audio, run_ffmpeg)
from pipeline.sound import voice_track
from pipeline.voice_compare import voice_compare


def _graph(track):
    return ";".join(audio_graph(CompositeSpec(base_input_args=[], duration=3,
                                              audio=[track]), 0)[1])


def test_off_by_default_no_filters(settings, tmp_path):
    assert settings.voice_room is False and settings.voice_deess is False
    graph = _graph(voice_track(tmp_path / "v.wav", settings))
    assert ROOM_ECHO not in graph and DEESSER not in graph
    assert "asplit=2[dry0]" not in graph


def test_room_filter_with_windows(settings, tmp_path):
    on = settings.model_copy(update={"voice_room": True, "voice_deess": True})
    track = voice_track(tmp_path / "v.wav", on, wide=[(1.0, 2.0), (4.0, 5.0)])
    track.start_s = 0.5
    graph = _graph(track)
    assert DEESSER in graph
    assert "asplit=2[dry0][wet0]" in graph
    # programme time moved to the voice's own clock (it starts 0.5 s in)
    assert "between(t,0.500,1.500)+between(t,3.500,4.500)" in graph
    assert graph.index("asplit") < graph.index("adelay=500")


def test_graph_runs_on_a_tone(tmp_path):
    tone = tmp_path / "tone.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=4000:duration=2", str(tone)])
    spec = CompositeSpec(base_input_args=[], duration=2, audio=[
        AudioTrack(path=tone, voice=True, room=True, deess=True,
                   wide=((0.5, 1.0),), start_s=0.2)])
    out = render_audio(spec, tmp_path / "out.wav")
    assert abs(ffprobe_duration(out) - 2.0) < 0.1


def test_compare_writes_four_files(tmp_path):
    tone = tmp_path / "voice.m4a"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=500:duration=6",
                "-c:a", "aac", str(tone)])
    files = voice_compare(tone, tmp_path / "cmp")
    assert [f.name for f in files] == ["compare_dry.wav", "compare_room.wav",
                                       "compare_deess.wav", "compare_both.wav"]
    for f in files:
        assert abs(ffprobe_duration(f) - 6.0) < 0.2
    assert not (tmp_path / "cmp" / "compare_source.wav").exists()

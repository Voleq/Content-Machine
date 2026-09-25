"""What a SHORT sounds like.

The LONG builds its mix inline in `render_long`, beside the segments its cues
hang off. The SHORT's lives here instead, because the compositor is the wrong
place for it: sound reads the shot spans AFTER composition and changes
nothing about the picture, so the two can move independently.

THE SHORT HAD NO MIX FOR SIX WEEKS. The shots rewrite (10c4d23, 15 Aug)
replaced the old renderer's audio block with a `-shortest` mux of the voice
alone. The room tone, the effects, the voice compression and the loudness
pass all went with it, and the commit never said so. A short went out as a
raw, uncompressed voice with digital silence between words, at whatever
level the voice model happened to hand back.

This puts back the floor: the voice through the same compressor the LONG
uses, the room underneath it, and the master bus to the streaming target.
Both formats mix through `render_common.audio_graph`, so a change to the
master reaches both or neither.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.audio_assets import ROOM_TONE_GAIN_DB, ROOM_TONE_NAME, audio_banner
from pipeline.render_common import AudioTrack

log = logging.getLogger(__name__)


def short_mix(tts, settings) -> list[AudioTrack]:
    """The tracks under a SHORT, or none when there is no voice to mix.

    No voice file means no mix at all, the same as before: a proof run on a
    missing file renders a silent picture, and a room tone with nobody in it
    is not a proof of anything.
    """
    voice = getattr(tts, "audio_path", None)
    if not voice or not Path(voice).exists():
        return []
    tracks = [AudioTrack(path=Path(voice), gain_db=0.0, voice=True,
                         name="voice")]
    # The same room the LONG sits in, at the same level. Felt, not heard: it
    # is what stops the gaps between sentences going to digital silence.
    room = settings.assets_dir / "sfx" / ROOM_TONE_NAME
    if room.exists():
        tracks.append(AudioTrack(path=room, gain_db=ROOM_TONE_GAIN_DB,
                                 loop=True, name="room_tone"))
    banner = audio_banner(settings)
    if banner:
        log.warning("%s", banner)
    return tracks


def normalises(settings, tts) -> bool:
    """Whether the master bus moves this mix to the streaming target.

    The LONG's rule: mock and draft audio skip `loudnorm`, because measuring
    a placeholder and raising it thirty decibels tells you nothing about the
    real mix (see `CompositeSpec.normalise_audio`). The limiter runs either
    way.
    """
    return not (settings.mocking_tts or getattr(tts, "draft", False))


def manifest_rows(tracks: list[AudioTrack]) -> list[dict]:
    """What the mix did, in the shape the LONG's manifest already uses."""
    return [{"name": t.name or t.path.stem, "start": round(t.start_s, 2),
             "gain_db": round(t.gain_db, 1), "loop": t.loop}
            for t in tracks]

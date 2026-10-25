"""What a render found worth his eye, read back off its manifest.

An encode whose frames do not match its sound (item 22), a short's flash
shots and lost beats (item 19), the type too small for a phone (V5, the long
only: a short is set for a phone already) and a video that looks like the
last few (V7). The delivery message
on Telegram and the page's Proof step both say these, from here, so the two
cannot word them differently.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import look_alike, phone_type


def frames_note(manifest: dict) -> str:
    """The frame count after the encode (item 22), when it is off: the
    picture shorter than the voice, or out of step with the sound."""
    frames = manifest.get("frames")
    if not isinstance(frames, dict) or frames.get("ok") is not False:
        return ""
    return (f"The encode came out wrong: {frames.get('why')} "
            f"({frames.get('frames')} frames at {frames.get('fps')} fps). "
            f"Render it again before uploading.")


def flashes_note(manifest: dict) -> str:
    """A SHORT's shots up for under the minimum, and the beats the cut lost
    (item 19): each reads as a glitch, and a lost payoff takes its hit."""
    pacing = manifest.get("pacing")
    if not isinstance(pacing, dict):
        return ""
    floor = float(pacing.get("min_shot_s") or 0.8)
    parts = []
    flashes = [f for f in pacing.get("flashes") or () if isinstance(f, dict)]
    if flashes:
        parts.append(f"{len(flashes)} shot{'' if len(flashes) == 1 else 's'} "
                     f"up for under {floor:g}s, which reads as a glitch: "
                     + "; ".join(f"{f.get('shot')} {float(f.get('dur_s') or 0):.2f}s "
                                 f"at {float(f.get('start_s') or 0):.1f}s"
                                 for f in flashes[:4]))
    dropped = [str(d) for d in pacing.get("dropped") or ()]
    if dropped:
        parts.append(f"not in the cut at all: {', '.join(dropped)} (its words "
                     f"came too close to the next beat's, or in the last "
                     f"moment)")
    if not parts:
        return ""
    return ". ".join(parts) + ". Give those words a little more room."


def render_notes(manifest: dict, lane: str) -> list[str]:
    """One paragraph per finding kind, in the order he would fix them."""
    out = []
    bad_frames = frames_note(manifest)
    if bad_frames:
        out.append("🎞 " + bad_frames)
    if lane == "short":
        flashes = flashes_note(manifest)
        if flashes:
            out.append("⚡ " + flashes)
    if lane == "long":
        small = phone_type.report(manifest)
        if small:
            out.append("📱 " + small)
    alike = look_alike.report(manifest, lane)
    if alike:
        out.append("🔁 " + alike)
    return out


def notes_at(path: Path | str | None, lane: str) -> list[str]:
    """`render_notes` off a manifest file; [] when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return render_notes(data, lane) if isinstance(data, dict) else []

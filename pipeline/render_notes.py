"""What a render found worth his eye, read back off its manifest.

The type too small for a phone (V5, the long only: a short is set for a phone
already) and a video that looks like the last few (V7). The delivery message
on Telegram and the page's Proof step both say these, from here, so the two
cannot word them differently.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import look_alike, phone_type


def render_notes(manifest: dict, lane: str) -> list[str]:
    """One paragraph per finding kind, in the order he would fix them."""
    out = []
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

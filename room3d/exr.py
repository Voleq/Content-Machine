"""Reading the passes Blender writes beside each frame of him (lines.py).

Blender's own Python here has numpy and Pillow and no EXR reader, and Pillow
cannot read the float pictures a render's depth and normals come in. Blender
writes them uncompressed (the performer asks for that), one pass to a part of
a multi-part OpenEXR, and an uncompressed scanline EXR is headers, a table of
where each line is, and the lines: this reads exactly that.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# OpenEXR's pixel types: uint, half, float.
_BYTES = {0: 4, 1: 2, 2: 4}
_DTYPE = {0: "<u4", 1: "<f2", 2: "<f4"}


def _header(b: bytes, pos: int) -> tuple[dict[str, bytes], int]:
    """One header's attributes by name, raw, and where the next thing starts."""
    attrs = {}
    while b[pos] != 0:
        end = b.index(b"\0", pos)
        name, pos = b[pos:end].decode(), end + 1
        end = b.index(b"\0", pos)
        pos = end + 1                       # the type's name: the reader knows them
        size = struct.unpack_from("<i", b, pos)[0]
        attrs[name] = b[pos + 4:pos + 4 + size]
        pos += 4 + size
    return attrs, pos + 1


def _channels(raw: bytes) -> list[tuple[str, int]]:
    out, p = [], 0
    while raw[p] != 0:
        end = raw.index(b"\0", p)
        out.append((raw[p:end].decode(), struct.unpack_from("<i", raw, end + 1)[0]))
        p = end + 1 + 16
    return out


def read_exr(path: str | Path) -> dict[str, np.ndarray]:
    """Every channel of an uncompressed scanline OpenEXR, one part or many,
    as float32 (h, w) arrays named "part.channel" (or "channel" in a file of
    one part), the top row first."""
    b = Path(path).read_bytes()
    if b[:4] != b"\x76\x2f\x31\x01":
        raise ValueError(f"{path} is not an OpenEXR")
    multi = bool(struct.unpack_from("<i", b, 4)[0] & 0x1000)
    pos, parts = 8, []
    while True:
        attrs, pos = _header(b, pos)
        parts.append(attrs)
        if not multi or b[pos] == 0:
            break
    pos += 1 if multi else 0
    tables = []
    for attrs in parts:
        if attrs["compression"][0] != 0:
            raise ValueError(f"{path} is compressed: write it with no codec")
        x0, y0, x1, y1 = struct.unpack("<4i", attrs["dataWindow"])
        h = y1 - y0 + 1
        n = struct.unpack("<i", attrs["chunkCount"])[0] if "chunkCount" in attrs else h
        tables.append((struct.unpack_from(f"<{n}Q", b, pos), _channels(attrs["channels"]),
                       x1 - x0 + 1, h, y0, attrs.get("name", b"").decode()))
        pos += 8 * n
    out = {}
    for offsets, chans, w, h, y0, name in tables:
        planes = {ch: np.empty((h, w), np.float32) for ch, _ in chans}
        for off in offsets:
            q = off + (4 if multi else 0)          # a part's chunk names its part
            y = struct.unpack_from("<i", b, q)[0] - y0
            q += 8                                 # the line, and its size
            for ch, kind in chans:
                planes[ch][y] = np.frombuffer(b, _DTYPE[kind], w, q)
                q += w * _BYTES[kind]
        for ch, a in planes.items():
            out[f"{name}.{ch}" if name else ch] = a
    return out

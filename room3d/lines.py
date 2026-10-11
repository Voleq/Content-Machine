"""HIS LINES FROM THE RENDER'S OWN PASSES (11 Oct 2026).

Freestyle traces his lines on the CPU after every frame, one core at a time,
and once Cycles draws him on a GPU that tracing is most of a frame. These are
found instead in the pictures Cycles makes alongside his (on the GPU, at no
extra cost): how far each pixel is (depth), which way it faces (normal), and
which of his parts and materials it is. His outline is where he ends against
what is behind him, or where one part of him stands in front of another; a
detail line is where his surface turns sharply or one material meets another,
the same edges Freestyle's two line sets draw, at their weights and in his
ink. Where something of the room stands in front of him (the desk, the
monitor) nothing is drawn: that edge is the room's, and its picture has it.
Depth and the indexes come from one ray per pixel; the normals are smoothed
over the pixel, so no turn is read where two things meet.

Pure numpy, no Blender, so the drawing can be checked without a render.
"""
from __future__ import annotations

import math

import numpy as np

# Freestyle's crease angle in the room's render setup is 128 degrees between
# faces: a turn of more than 52 degrees from one pixel to the next is a crease.
CREASE_TURN_DEG = 52.0
# A jump in depth this much of the nearer distance (or this many metres) is
# one part of him in front of another, whichever way the nearer one faces.
DEPTH_JUMP = 0.04
DEPTH_JUMP_M = 0.03
# A smaller step is still one surface in front of another (his nose on his
# cheek, his side over his arm) when the nearer one is turning away from the
# camera, facing it less than this, and the step is this many times what the
# surface behind changes from one pixel to the next and at least this deep.
# A surface turning away on its own steps a little more every pixel and is
# never this sudden.
SIL_FACING = 0.75
SIL_RATIO = 3.0
SIL_STEP_M = 0.004
# Where two surfaces nearly touch (his side over his arm) the step is a few
# millimetres, but the nearer one is the one turning away: on one surface
# going round, the nearer pixel always faces the camera more. A nearer
# pixel facing it less than this, and this much less than the one behind,
# is the edge of what is in front, at any step deeper than a millimetre.
SIL_EDGE_FACING = 0.5
SIL_EDGE_TURN = 0.2
SIL_EDGE_STEP_M = 0.001
# Along such an edge the evidence comes and goes from pixel to pixel, and a
# line drawn only where it is sure is a row of dashes. Where it is half as
# sure, a line carries on from where it is drawn, for a few pixels, so the
# gaps close without a line ever starting from nothing.
SIL_FAINT = 0.5
SIL_BRIDGE_PX = 5
# A mark this many pixels or fewer, touching no other, is a speck.
SPECK_PX = 3


def toward(tl, tr, bl, size: tuple[int, int]) -> np.ndarray:
    """From each pixel of a (w, h) frame toward the camera, as unit vectors
    (h, w, 3), given the world directions from the camera through the
    frame's top-left, top-right and bottom-left corners."""
    w, h = size
    tl, tr, bl = (np.asarray(v, np.float32) for v in (tl, tr, bl))
    u = (np.arange(w, dtype=np.float32) + 0.5) / w
    v = (np.arange(h, dtype=np.float32) + 0.5) / h
    ray = tl + u[None, :, None] * (tr - tl) + v[:, None, None] * (bl - tl)
    return -ray / np.linalg.norm(ray, axis=-1, keepdims=True)


def _close_slits(depth, normal, obj, mat):
    """The passes with one-pixel slits through him closed: a pixel of the
    room with him either side of it (left and right, or above and below) is
    a ray that slipped between two of his parts where they touch, and a line
    round it would be a speck Freestyle, working from the shapes, never draws.
    It takes the values of the pixel before it."""
    him = obj >= 0.5
    across = np.zeros_like(him)
    across[:, 1:-1] = ~him[:, 1:-1] & him[:, :-2] & him[:, 2:]
    down = np.zeros_like(him)
    down[1:-1, :] = ~him[1:-1, :] & him[:-2, :] & him[2:, :] & ~across[1:-1, :]
    if not (across.any() or down.any()):
        return depth, normal, obj, mat
    out = []
    for a in (depth, normal, obj, mat):
        a = a.copy()
        a[:, 1:][across[:, 1:]] = a[:, :-1][across[:, 1:]]
        a[1:, :][down[1:, :]] = a[:-1, :][down[1:, :]]
        out.append(a)
    return tuple(out)


def _own(obj) -> np.ndarray:
    """Pixels whose four neighbours are the same part as them. The normal
    pass is smoothed over each pixel like the picture, so where two things
    meet it is a blend of both, which is no turn of his surface."""
    p = np.pad(obj, 1, mode="edge")
    return ((p[1:-1, :-2] == obj) & (p[1:-1, 2:] == obj)
            & (p[:-2, 1:-1] == obj) & (p[2:, 1:-1] == obj))


def _row_edges(depth, facing, normal, obj, mat, own, turn):
    """The lines between each pixel and the next along its row: (outline
    on the first, outline on the second, detail on the first)."""
    him = obj >= 0.5
    ha, hb = him[:, :-1], him[:, 1:]
    da, db = depth[:, :-1], depth[:, 1:]
    oa, ob = obj[:, :-1], obj[:, 1:]
    ma, mb = mat[:, :-1], mat[:, 1:]
    fa, fb = facing[:, :-1], facing[:, 1:]
    # the pixel before the first and after the second: how the surface
    # behind runs on, one pixel further from the edge
    dp = np.pad(depth, ((0, 0), (1, 1)), mode="edge")
    d_before, d_after = dp[:, :-3], dp[:, 3:]
    near_a = da <= db
    step = np.abs(da - db)
    jump = step > np.maximum(DEPTH_JUMP * np.minimum(da, db), DEPTH_JUMP_M)
    runs_on = np.where(near_a, np.abs(d_after - db), np.abs(d_before - da))
    f_near = np.where(near_a, fa, fb)
    f_far = np.where(near_a, fb, fa)
    sil = (f_near < SIL_FACING) & (step > np.maximum(SIL_RATIO * runs_on, SIL_STEP_M))
    sil |= ((f_near < SIL_EDGE_FACING) & (f_far - f_near > SIL_EDGE_TURN)
            & (step > SIL_EDGE_STEP_M))
    k = SIL_FAINT
    faint = ((f_near < SIL_FACING + (1 - SIL_FACING) * k)
             & (step > np.maximum(SIL_RATIO * k * runs_on, SIL_STEP_M * k))) | (
        (f_near < SIL_EDGE_FACING + (1 - SIL_EDGE_FACING) * k)
        & (f_far - f_near > SIL_EDGE_TURN * k) & (step > SIL_EDGE_STEP_M * k))
    # his edge against what is behind him: on his side of it
    a_out = ha & ~hb & (db > da)
    b_out = hb & ~ha & (da > db)
    both = ha & hb
    other_part = np.abs(oa - ob) > 0.5
    other_mat = np.abs(ma - mb) > 0.5
    # one surface of him in front of another, or a part of its own stuff
    # on him (his glasses, his beard, his mouth): drawn round, on the
    # nearer side. Two parts of one stuff meeting (his sleeve at his
    # shoulder) are one surface, and nothing is drawn.
    part = both & (jump | sil | (other_part & other_mat))
    a_out |= part & near_a
    b_out |= part & ~near_a
    na, nb = normal[:, :-1], normal[:, 1:]
    bend = (na * nb).sum(-1) < turn
    crease = both & ~other_part & ~part & (other_mat | (own[:, :-1] & own[:, 1:] & bend))
    faint &= both
    return a_out, b_out, crease, faint & near_a, faint & ~near_a


def _neighbours(mask) -> np.ndarray:
    """How many of each pixel's eight neighbours are set."""
    p = np.pad(mask, 1).astype(np.uint8)
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] + p[1:-1, 2:]
            + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:])


def _bridge(line, faint) -> np.ndarray:
    """`line` carried on along `faint` for `SIL_BRIDGE_PX` pixels."""
    for _ in range(SIL_BRIDGE_PX):
        more = faint & ~line & (_neighbours(line) > 0)
        if not more.any():
            break
        line = line | more
    return line


def _despeck(mask) -> np.ndarray:
    """`mask` without its specks: a mark with no more than `SPECK_PX` pixels
    within two of it. A line always has more; a line's last pixel may not,
    and the line is a pixel shorter for it."""
    p = np.pad(mask, 2).astype(np.uint8)
    h, w = mask.shape
    near = sum(p[dy:dy + h, dx:dx + w] for dy in range(5) for dx in range(5))
    return mask & (near > SPECK_PX)


def edges(depth, normal, obj, mat, toward=None) -> tuple[np.ndarray, np.ndarray]:
    """(outline, detail): where his lines go, as boolean masks the size of
    the passes. `obj` is each pixel's object index, his parts 1 and up and
    the room 0; `mat` its material index; `depth` metres from the camera,
    huge where nothing is; `normal` (h, w, 3) in the world, and `toward`
    the same shape, from each pixel toward the camera (`toward()`); without
    it, his surfaces in front of one another show only where they jump."""
    # nothing behind him is infinitely far in a half-float depth
    depth = np.where(np.isfinite(depth), depth, 1e9).astype(np.float32)
    depth, normal, obj, mat = _close_slits(depth, normal, obj, mat)
    facing = ((normal * toward).sum(-1) if toward is not None
              else np.ones(depth.shape, np.float32))
    turn = math.cos(math.radians(CREASE_TURN_DEG))
    own = _own(obj)
    outline = np.zeros(depth.shape, bool)
    detail = np.zeros(depth.shape, bool)
    faint = np.zeros(depth.shape, bool)
    a, b, c, fa, fb = _row_edges(depth, facing, normal, obj, mat, own, turn)
    outline[:, :-1] |= a
    outline[:, 1:] |= b
    detail[:, :-1] |= c
    faint[:, :-1] |= fa
    faint[:, 1:] |= fb
    a, b, c, fa, fb = _row_edges(depth.T, facing.T, normal.transpose(1, 0, 2), obj.T,
                                 mat.T, own.T, turn)
    outline[:-1, :] |= a.T
    outline[1:, :] |= b.T
    detail[:-1, :] |= c.T
    faint[:-1, :] |= fa.T
    faint[1:, :] |= fb.T
    outline = _despeck(_bridge(outline, faint))
    return outline, _despeck(detail & ~outline)


def coverage(mask, width: float) -> np.ndarray:
    """A line `width` pixels wide over every marked pixel, anti-aliased, as
    alpha 0..1: full on the pixel itself, falling off over the last pixel."""
    out = mask.astype(np.float32)
    if not mask.any():
        return out
    reach = width / 2.0 + 0.5
    r = int(math.ceil(reach))
    h, w = mask.shape
    padded = np.pad(mask, r)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            d = math.hypot(dx, dy)
            a = min(max(reach - d, 0.0), 1.0)
            if a <= 0 or (dx == 0 and dy == 0):
                continue
            shifted = padded[r + dy:r + dy + h, r + dx:r + dx + w]
            np.maximum(out, shifted * a, out=out)
    return out


def ink(rgba, alpha_line, colour) -> np.ndarray:
    """`rgba` (uint8, straight alpha) with the line drawn over it in `colour`."""
    px = rgba.astype(np.float32) / 255.0
    a = alpha_line[..., None]
    base = px[..., 3:4]
    out_a = a + base * (1 - a)
    rgb = (np.asarray(colour, np.float32)[None, None, :] / 255.0 * a
           + px[..., :3] * base * (1 - a)) / np.maximum(out_a, 1e-6)
    out = np.concatenate([rgb, out_a], axis=-1)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def draw(rgba, depth, normal, obj, mat, *, outline_px: float, detail_px: float,
         colour, toward=None) -> np.ndarray:
    """His frame `rgba` with his lines on it."""
    outline, detail = edges(depth, normal, obj, mat, toward)
    a = np.maximum(coverage(outline, outline_px), coverage(detail, detail_px))
    return ink(rgba, a, colour)

"""Generate the deterministic placeholder brand assets committed to the repo.

Run from the repo root:  .venv/bin/python scripts/gen_assets.py

Everything here is procedural (Pillow + ffmpeg lavfi), seeded and
deterministic — no downloads, no licenses to clear. The operator is
expected to replace sfx/music with properly licensed material for
production; stamps/backgrounds/folders are shippable as-is.

Outputs:
  assets/stamps/<VERDICT>.png           transparent grunge verdict stamps
  assets/backgrounds/desk_dark.png      1080x1920 mahogany desk (SHORT)
  assets/backgrounds/desk_wide.png      1920x1080 mahogany desk (LONG filler)
  assets/backgrounds/folder_closed.png  manila folder, cover label area
  assets/backgrounds/folder_open.png    open folder spread (data block area)
  assets/sfx/*.wav                      placeholder SFX (6 palette keys + ui)
  assets/music/deadpan_bed.m4a          60s droning music bed (LONG)
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.models import Verdict  # noqa: E402

ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"

RED = (196, 32, 40)
GREEN = (28, 148, 74)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


# --------------------------------------------------------------------- stamps

def gen_stamps() -> None:
    out = ASSETS / "stamps"
    out.mkdir(parents=True, exist_ok=True)
    for verdict in Verdict:
        rng = random.Random(f"stamp:{verdict.value}")
        text = verdict.value.replace("_", " ")
        color = GREEN if verdict.is_laudatory else RED

        w, h = 1000, 460
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        d.rounded_rectangle([14, 14, w - 14, h - 14], radius=38, outline=color, width=14)
        d.rounded_rectangle([44, 44, w - 44, h - 44], radius=26, outline=color, width=6)

        size = 150
        font = _font("DejaVuSans-Bold.ttf", size)
        while d.textlength(text, font=font) > w - 130 and size > 40:
            size -= 6
            font = _font("DejaVuSans-Bold.ttf", size)
        tw = d.textlength(text, font=font)
        bbox = d.textbbox((0, 0), text, font=font)
        th = bbox[3] - bbox[1]
        d.text(((w - tw) / 2, (h - th) / 2 - bbox[1]), text, font=font, fill=color)

        # distress: punch seeded holes through the ink
        px = img.load()
        for _ in range(2600):
            x = rng.randrange(0, w)
            y = rng.randrange(0, h)
            r = rng.randrange(1, 5)
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= r * r and 0 <= x + dx < w and 0 <= y + dy < h:
                        pr, pg, pb, pa = px[x + dx, y + dy]
                        if pa:
                            px[x + dx, y + dy] = (pr, pg, pb, max(0, pa - rng.randrange(90, 220)))

        img = img.rotate(-8, expand=True, resample=Image.BICUBIC)
        img.save(out / f"{verdict.value}.png")
    print(f"stamps: {len(list(Verdict))} written")


# ---------------------------------------------------------------- backgrounds

def _wood(w: int, h: int, seed: str) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (34, 20, 13))
    d = ImageDraw.Draw(img)
    # vertical grain streaks
    x = 0
    while x < w:
        streak_w = rng.randrange(8, 42)
        tone = rng.randrange(-9, 10)
        col = (34 + tone + rng.randrange(0, 7), 20 + tone // 2, 13 + max(tone // 3, -4))
        d.rectangle([x, 0, x + streak_w, h], fill=col)
        x += streak_w
    img = img.filter(ImageFilter.GaussianBlur(2))
    # fine grain noise
    noise = Image.effect_noise((w, h), 14).convert("L")
    img = Image.composite(img.point(lambda p: min(255, p + 6)), img, noise.point(lambda p: p // 6))
    # vignette
    mask = Image.new("L", (w, h), 0)
    dm = ImageDraw.Draw(mask)
    dm.ellipse([-w * 0.35, -h * 0.35, w * 1.35, h * 1.35], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = Image.new("RGB", (w, h), (12, 6, 4))
    return Image.composite(img, dark, mask)


def gen_backgrounds() -> None:
    out = ASSETS / "backgrounds"
    out.mkdir(parents=True, exist_ok=True)
    _wood(1080, 1920, "desk:tall").save(out / "desk_dark.png")
    _wood(1920, 1080, "desk:wide").save(out / "desk_wide.png")

    # closed folder (whip-pan + cold open prop): tab + cover label plate
    w, h = 900, 1150
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 90, w, h], radius=26, fill=(178, 141, 84, 255))
    d.rounded_rectangle([40, 0, 380, 130], radius=22, fill=(178, 141, 84, 255))
    d.rounded_rectangle([8, 104, w - 8, h - 10], radius=22, outline=(120, 90, 48, 255), width=5)
    d.rounded_rectangle([170, 420, w - 170, 620], radius=10, fill=(238, 230, 210, 255),
                        outline=(120, 90, 48, 255), width=4)
    label = _font("DejaVuSansMono-Bold.ttf", 44)
    d.text((190, 445), "CASE FILE", font=label, fill=(90, 70, 40, 255))
    d.text((190, 505), "CONFIDENTIAL", font=label, fill=(170, 40, 40, 255))
    img.save(out / "folder_closed.png")

    # open folder spread — the data block types onto this
    w, h = 1000, 1240
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w, h], radius=24, fill=(196, 160, 100, 255))
    d.rounded_rectangle([26, 30, w - 26, h - 30], radius=14, fill=(242, 235, 218, 255))
    d.line([w // 2, 40, w // 2, h - 40], fill=(205, 190, 160, 255), width=3)
    rng = random.Random("paper")
    for y in range(90, h - 60, 56):  # faint ruled lines
        d.line([60, y, w - 60, y + rng.randrange(-2, 3)], fill=(216, 205, 182, 255), width=2)
    d.rounded_rectangle([0, 0, w, h], radius=24, outline=(120, 90, 48, 255), width=5)
    img.save(out / "folder_open.png")
    print("backgrounds: 4 written")


# ------------------------------------------------------------------------ sfx

def _lavfi(out: Path, *args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def gen_sfx() -> None:
    out = ASSETS / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    wav = ["-c:a", "pcm_s16le", "-ar", "44100"]

    _lavfi(out / "windows_error.wav",
           "-f", "lavfi", "-i", "sine=f=830:d=0.14",
           "-f", "lavfi", "-i", "sine=f=623:d=0.22",
           "-filter_complex",
           "[0]volume=0.7[a];[1]volume=0.7[b];[a][b]concat=n=2:v=0:a=1,afade=t=out:st=0.30:d=0.06",
           *wav)
    _lavfi(out / "cash_register.wav",
           "-f", "lavfi", "-i", "sine=f=1568:d=0.5",
           "-f", "lavfi", "-i", "sine=f=2093:d=0.5",
           "-filter_complex",
           "[0][1]amix=inputs=2:normalize=0,volume=0.5,afade=t=out:st=0.08:d=0.42",
           *wav)
    _lavfi(out / "record_scratch.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.35:color=white:seed=7",
           "-af", "highpass=f=1800,tremolo=f=34:d=0.9,volume=0.8,afade=t=out:st=0.25:d=0.1",
           *wav)
    _lavfi(out / "sad_trombone.wav",
           "-f", "lavfi", "-i", "sine=f=392:d=0.4",
           "-f", "lavfi", "-i", "sine=f=370:d=0.4",
           "-f", "lavfi", "-i", "sine=f=349:d=0.4",
           "-f", "lavfi", "-i", "sine=f=311:d=0.7",
           "-filter_complex",
           "[0]vibrato=f=6:d=0.4[a];[1]vibrato=f=6:d=0.4[b];[2]vibrato=f=6:d=0.4[c];"
           "[3]vibrato=f=7:d=0.6,afade=t=out:st=0.3:d=0.4[d];"
           "[a][b][c][d]concat=n=4:v=0:a=1,volume=0.55",
           *wav)
    _lavfi(out / "camera_shutter.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.03:color=white:seed=3",
           "-f", "lavfi", "-i", "anullsrc=d=0.05",
           "-f", "lavfi", "-i", "anoisesrc=d=0.04:color=white:seed=4",
           "-filter_complex",
           "[0]volume=0.9[a];[1]volume=0[b];[2]volume=0.6[c];[a][b][c]concat=n=3:v=0:a=1,highpass=f=900",
           *wav)
    _lavfi(out / "vine_boom.wav",
           "-f", "lavfi", "-i", "sine=f=52:d=0.9",
           "-af", "volume=1.4,afade=t=in:st=0:d=0.005,afade=t=out:st=0.15:d=0.75,aecho=0.8:0.6:60:0.35",
           *wav)
    # UI sounds used by the renderers themselves
    _lavfi(out / "stamp_hit.wav",
           "-f", "lavfi", "-i", "sine=f=68:d=0.22",
           "-f", "lavfi", "-i", "anoisesrc=d=0.06:color=brown:seed=5",
           "-filter_complex",
           "[0]volume=1.2[a];[1]volume=0.8[b];[a][b]amix=inputs=2:normalize=0,"
           "afade=t=in:st=0:d=0.004,afade=t=out:st=0.05:d=0.17",
           *wav)
    _lavfi(out / "whoosh.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.45:color=pink:seed=6",
           "-af", "lowpass=f=1100,afade=t=in:st=0:d=0.12,afade=t=out:st=0.2:d=0.25,volume=0.7",
           *wav)
    _lavfi(out / "typewriter_tick.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.018:color=white:seed=8",
           "-af", "highpass=f=2500,volume=0.35",
           *wav)
    print("sfx: 9 written")


def gen_overlays() -> None:
    """Pre-rendered glitch overlays (§7.2): rendered ONCE here, composited
    by the filtergraph at render time — never frame-by-frame in Python."""
    out = ASSETS / "overlays"
    out.mkdir(parents=True, exist_ok=True)
    # transparent speckle glitch: seeded Pillow frames (sparse hard white
    # speckles + occasional tear bands), authored small and upscaled chunky
    # (nearest-neighbour) at composite time. Pre-rendered ONCE here.
    from pipeline.rasters import frames_to_alpha_clip  # noqa: E402

    rng = random.Random("glitch")
    frames = []
    w, h = 320, 180
    for _ in range(15):  # 0.5s @ 30fps
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = img.load()
        for _ in range(int(w * h * 0.10)):
            px[rng.randrange(w), rng.randrange(h)] = (255, 255, 255, 255)
        if rng.random() < 0.4:  # horizontal tear band
            y0 = rng.randrange(h - 8)
            d = ImageDraw.Draw(img)
            d.rectangle([0, y0, w, y0 + rng.randrange(2, 7)],
                        fill=(255, 255, 255, 170))
        frames.append(img)
    frames_to_alpha_clip(frames, 30, out / "glitch_noise.mov")

    # rgb-split horizontal tear (opaque, for blend/flash moments)
    _lavfi(out / "rgb_tear.mp4",
           "-f", "lavfi", "-i", "color=c=0x0a0a0a:s=480x270:r=30:d=0.5",
           "-vf", "noise=alls=40:allf=t,rgbashift=rh=8:bv=-6,eq=contrast=1.5",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "26")
    print("overlays: 2 written")


def gen_music() -> None:
    out = ASSETS / "music"
    out.mkdir(parents=True, exist_ok=True)
    _lavfi(out / "deadpan_bed.m4a",
           "-f", "lavfi", "-i", "sine=f=110:d=60",
           "-f", "lavfi", "-i", "sine=f=164.81:d=60",
           "-f", "lavfi", "-i", "sine=f=220.5:d=60",
           "-f", "lavfi", "-i", "sine=f=277.18:d=60",
           "-filter_complex",
           "[0]volume=0.5[a];[1]volume=0.30[b];[2]volume=0.22[c];[3]volume=0.12,tremolo=f=0.13:d=0.9[d];"
           "[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=800,tremolo=f=0.11:d=0.35,"
           "afade=t=in:st=0:d=2,afade=t=out:st=57:d=3,volume=0.6",
           "-c:a", "aac", "-b:a", "128k")
    print("music: 1 written")


# ---------------------------------------------------------------- Dennis kit
# Placeholder versions of the reusable asset kit (the production kit is
# produced in Claude Design and dropped over these — same filenames).

INK_BG = (14, 17, 23)


def gen_dennis_backgrounds() -> None:
    """Dark branded backdrops: subtle grid + vignette, zero desk energy."""
    out = ASSETS / "backgrounds"
    out.mkdir(parents=True, exist_ok=True)
    for name, (w, h) in (("dennis_bg_tall.png", (1080, 1920)),
                         ("dennis_bg_wide.png", (1920, 1080))):
        rng = random.Random(f"dennis:{name}")
        img = Image.new("RGB", (w, h), INK_BG)
        d = ImageDraw.Draw(img)
        step = max(w, h) // 24
        grid = (24, 28, 36)
        for x in range(0, w, step):
            d.line([x, 0, x, h], fill=grid, width=1)
        for y in range(0, h, step):
            d.line([0, y, w, y], fill=grid, width=1)
        # faint scattered "data dust"
        for _ in range(int(w * h / 22000)):
            x, y = rng.randrange(w), rng.randrange(h)
            tone = rng.randrange(30, 52)
            d.point((x, y), fill=(tone, tone + 4, tone + 10))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        # vignette
        mask = Image.new("L", (w, h), 0)
        dm = ImageDraw.Draw(mask)
        dm.ellipse([-w * 0.35, -h * 0.35, w * 1.35, h * 1.35], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
        dark = Image.new("RGB", (w, h), (7, 9, 13))
        Image.composite(img, dark, mask).save(out / name)
    print("dennis backgrounds: 2 written")


def gen_dennis_sfx() -> None:
    """Kit stings: beat-transition riser + zoom-punch pop."""
    out = ASSETS / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    wav = ["-c:a", "pcm_s16le", "-ar", "44100"]
    _lavfi(out / "sting.wav",
           "-f", "lavfi", "-i", "sine=f=220:d=0.28",
           "-af",
           "vibrato=f=9:d=0.3,volume=0.5,afade=t=in:st=0:d=0.02,afade=t=out:st=0.14:d=0.14",
           *wav)
    _lavfi(out / "pop.wav",
           "-f", "lavfi", "-i", "sine=f=520:d=0.09",
           "-f", "lavfi", "-i", "anoisesrc=d=0.03:color=pink:seed=11",
           "-filter_complex",
           "[0]volume=0.7[a];[1]highpass=f=1200,volume=0.5[b];"
           "[a][b]amix=inputs=2:normalize=0,afade=t=in:st=0:d=0.004,afade=t=out:st=0.04:d=0.05",
           *wav)
    print("dennis sfx: 2 written")


def gen_dennis_music() -> None:
    """Lo-fi-ish placeholder bed for both formats (replace with the
    Claude Design / licensed bed in production)."""
    out = ASSETS / "music"
    out.mkdir(parents=True, exist_ok=True)
    _lavfi(out / "dennis_bed.m4a",
           "-f", "lavfi", "-i", "sine=f=98:d=60",
           "-f", "lavfi", "-i", "sine=f=146.83:d=60",
           "-f", "lavfi", "-i", "sine=f=196:d=60",
           "-f", "lavfi", "-i", "anoisesrc=d=60:color=brown:seed=21",
           "-filter_complex",
           "[0]volume=0.42[a];[1]volume=0.26,tremolo=f=0.12:d=0.8[b];"
           "[2]volume=0.16[c];[3]lowpass=f=300,volume=0.06[d];"
           "[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=700,"
           "tremolo=f=0.10:d=0.3,afade=t=in:st=0:d=2,afade=t=out:st=57:d=3,volume=0.55",
           "-c:a", "aac", "-b:a", "128k")
    print("dennis music: 1 written")


def gen_meme_placeholders() -> None:
    """One placeholder PNG per meme_index.json entry. Only fills GAPS —
    real memes the operator drops in are never overwritten."""
    import json

    lib = ASSETS / "meme_library"
    index_file = lib / "meme_index.json"
    if not index_file.exists():
        print("meme placeholders: no meme_index.json — skipped")
        return
    index = json.loads(index_file.read_text())
    written = 0
    for stem, entry in index.items():
        existing = [p for p in lib.glob(f"{stem}.*") if p.suffix != ".json"]
        if existing:
            continue
        rng = random.Random(f"meme:{stem}")
        w, h = 720, 540
        hue = rng.randrange(30, 90)
        img = Image.new("RGB", (w, h), (hue // 2 + 20, hue // 3 + 18, hue // 2 + 26))
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, w - 11, h - 11], outline=(235, 235, 235), width=5)
        title_font = _font("DejaVuSansMono-Bold.ttf", 30)
        words = stem.split("-")
        lines, cur = [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if d.textlength(trial, font=title_font) > w - 80 and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
        y = h / 2 - len(lines) * 20
        for line in lines:
            d.text(((w - d.textlength(line, font=title_font)) / 2, y),
                   line, font=title_font, fill=(240, 240, 240))
            y += 42
        small = _font("DejaVuSansMono.ttf", 18)
        d.text((24, h - 44), "placeholder — drop the real meme here",
               font=small, fill=(190, 190, 190))
        img.save(lib / f"{stem}.png")
        written += 1
    print(f"meme placeholders: {written} written ({len(index)} indexed)")


if __name__ == "__main__":
    gen_stamps()
    gen_backgrounds()
    gen_sfx()
    gen_overlays()
    gen_music()
    gen_dennis_backgrounds()
    gen_dennis_sfx()
    gen_dennis_music()
    gen_meme_placeholders()

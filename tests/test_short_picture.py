"""The short's company photo, full screen (Valentin's pick, 10-17).

The long plays everything taken from the net full screen; the short's one
photograph sat in a taped paper frame. It now fills the 9:16 screen, cropped
from the full-size copy kept at fetch, with the company's name and the
credit on strips of paper over it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


class _Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class _Stub:
    """Fills every slot, and hands the company photo the file given."""

    def __init__(self, photo):
        self.photo = photo

    def text_for(self, src):
        if "series" in src or "figures" in src:
            return "10,13,16,19,22,25"
        if src == "numbers.header":
            return "\tFY-4\tFY-3\tFY-2\tFY-1\tFY-0"
        if {"heads", "axis"} & set(src.split(".")):
            return "a,b,c,d"
        if "years" in src.split("."):
            return "a,b,c,d,e,f"
        return "3.4%" if src.rsplit(".", 1)[-1] in (
            "reported", "expected", "latest", "label", "last", "unit",
            "ticker", "kicker", "headline_figure") else "words"

    def image_for(self, src):
        return self.photo if src.startswith("photo.") else None

    def list_for(self, src):
        return ["m1", "m2", "m3", "m4"]


@pytest.fixture(scope="module")
def reg():
    from config import Settings
    from pipeline.plates import load_plates

    return load_plates(Settings(_env_file=None).assets_dir)


def _picture_layers(reg, photo):
    from pipeline.compose import build_layers
    from pipeline.shots import expand_sequences, load_format, resolve_spans

    fmt = expand_sequences(load_format("short"), lambda src: ["m1", "m2"])
    words = [_Word(f"w{i}", i * 0.3, (i + 1) * 0.3) for i in range(200)]
    spans = resolve_spans(fmt, words, 60.0, {})
    result = build_layers(fmt, spans, _Stub(photo), reg, aspect=fmt.aspect,
                          seed="test")
    return result, [l for l in result.layers if l.shot_id == "the-picture"]


def test_the_company_photo_fills_the_screen(reg, tmp_path):
    from pipeline.compose import caption_obstacles

    result, layers = _picture_layers(reg, tmp_path / "photo.jpg")
    media = [l for l in layers if l.kind == "media"]
    assert len(media) == 1
    fw, fh = result.frame
    assert (media[0].x, media[0].y, media[0].w, media[0].h) == (0, 0, fw, fh)
    assert media[0].bleed
    # No frame plate around it any more.
    assert not [l for l in layers if l.kind == "plate"]
    # The name and the credit are on strips, inside the caption's safe band
    # and clear of the place a caption is looked for.
    strips = [l for l in layers if l.kind == "text"]
    assert [l.panel for l in strips] == [True, True]
    assert all(170 <= l.y and l.y + l.h <= 1395 for l in strips), \
        [(l.y, l.h) for l in strips]
    # The picture is the ground the caption sits on, the strips are not.
    names = [n for n, _ in caption_obstacles(reg, layers)]
    assert "media" not in names and "text:caption" in names


def test_no_picture_no_shot(settings, tmp_path):
    """A strip round "imagery unavailable" is not a picture."""
    from pipeline.render_short import prune_empty_shots
    from pipeline.shots import load_format

    fmt = load_format("short")
    kept, dropped = prune_empty_shots(fmt, _Stub(None))
    assert "the-picture" in dropped
    assert "the-picture" not in [s.id for s in kept.shots]
    kept, dropped = prune_empty_shots(fmt, _Stub(tmp_path / "p.jpg"))
    assert "the-picture" in [s.id for s in kept.shots]


def _strip(settings, text, *, max_lines, size_fh=0.04, y=1073, h=None,
           canvas=None):
    from pipeline.compose import Layer
    from pipeline.marks import face_for, panel_height
    from pipeline.render_short import _draw_text

    canvas = canvas or Image.new("RGBA", (1080, 1920), (0, 0, 0, 255))
    h = h or panel_height(face_for(size_fh), round(size_fh * 1920), max_lines)
    layer = Layer(name="t", kind="text", shot_id="s", t_start=0, t_end=1,
                  x=86, y=y, w=907, h=h, size_fh=size_fh, text=text,
                  halign="left", max_lines=max_lines, panel=True)
    lost: dict = {}
    _draw_text(canvas, layer, settings, None, lost)
    return canvas, layer, lost


def _paper_rows(canvas, x):
    return [y for y in range(canvas.height)
            if canvas.getpixel((x, y))[0] > 150]


def test_the_strip_is_cut_to_its_words(settings):
    from pipeline.rasters import caption_colours

    _ink, paper = caption_colours(settings)
    canvas, layer, lost = _strip(settings, "Kroger · grocery", max_lines=2)
    assert not lost
    # Its foot on the box's foot, one line shorter than the box for two.
    rows = _paper_rows(canvas, layer.x + 2)
    assert rows[-1] == layer.y + layer.h - 1
    assert rows[0] > layer.y + 40
    assert canvas.getpixel((layer.x + 2, rows[-1]))[:3] == paper
    # As wide as the words, not the box.
    right = max(x for x in range(layer.x, layer.x + layer.w)
                if canvas.getpixel((x, rows[-1]))[0] > 150)
    assert right < layer.x + layer.w - 200


def test_a_two_line_name_breaks_at_its_dot(settings, monkeypatch):
    said: list[str] = []
    real = ImageDraw.ImageDraw.text

    def record(self, xy, text, *a, **k):
        said.append(text)
        return real(self, xy, text, *a, **k)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    _canvas, _layer, lost = _strip(
        settings, "The Procter & Gamble Company · household and personal "
                  "products", max_lines=2)
    assert said == ["The Procter & Gamble Company",
                    "household and personal products"]
    assert not lost


def test_the_short_crops_from_the_full_size_copy(settings, tmp_path):
    from pipeline.broll import Visual
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import ShortResolver

    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(
        encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    norm, master = tmp_path / "normalized_0.png", tmp_path / "master_0.jpg"
    norm.write_bytes(b"x")

    def resolver(v):
        r = ShortResolver(script=script, workdir=tmp_path, settings=settings,
                          prices=None, handle="@channel")
        r._pictures = {"company": v}
        return r

    pic = Visual(key="x", kind="img", path=norm, is_video=False,
                 source="cache", master=master)
    # An entry from before masters were kept: the normalised file.
    assert resolver(pic).image_for("photo.company") == norm
    master.write_bytes(b"x")
    assert resolver(pic).image_for("photo.company") == master


def test_the_master_is_kept_whole_but_never_enlarged(tmp_path):
    from pipeline.broll import MASTER_MAX_SIDE, keep_master

    big, small = tmp_path / "big.bin", tmp_path / "small.bin"
    Image.new("RGB", (6000, 3000), (10, 20, 30)).save(big, format="PNG")
    Image.new("RGBA", (800, 600), (10, 20, 30, 255)).save(small, format="PNG")
    got = keep_master(big, tmp_path / "m" / "big.jpg")
    with Image.open(got) as im:
        assert im.size == (MASTER_MAX_SIDE, MASTER_MAX_SIDE // 2)
        assert im.format == "JPEG"
    with Image.open(keep_master(small, tmp_path / "small.jpg")) as im:
        assert im.size == (800, 600)
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not a picture")
    assert keep_master(junk, tmp_path / "junk.jpg") is None

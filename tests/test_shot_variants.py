"""Alternates and cut orders: where a SHORT's variety comes from.

The three vertical formats are fixed shot lists and `parser_short` never reads
an inline `[PLATE]` tag, so until this existed the writer chose nothing visual
and neither did the code: every short of a format showed the same drawings in
the same order, and 55 plates drawn at 9:16 had no route to a frame at all.

That is the right shape for a lane whose whole point is mass production — the
character budgets can only be stated up front because the beats are fixed. So
the variety has to come from the code, and these are the tests that say it
does, and that it never does so at the cost of a line that no longer fits or a
picture that arrives over the wrong sentence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.compose import build_layers, check_budgets, check_invariants
from pipeline.shots import (AS_AUTHORED, apply_order, choose_order,
                            expand_sequences, load_format, order_names,
                            parse_format, resolve_spans, TemplateError)

VERTICAL = ("short", "earnings", "macro")


class FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word, self.start, self.end = word, start, end


class StubResolver:
    """Fills everything a template asks for, so the rotation is what shows.

    A copy of the one in `test_short_shots`, kept here rather than imported so
    a change made for one file's reasons cannot quietly move this one's
    answers.
    """

    def __init__(self, missing: set[str] = frozenset()) -> None:
        self.missing = set(missing)

    def text_for(self, src: str) -> str | None:
        if src in self.missing:
            return None
        # A day moves one way. The stub's went up, so the rising move plate is
        # in its rotation and the falling one never is.
        if src == "chart.move_up":
            return "+3.4%"
        if src == "chart.move_down":
            return None
        if src == "numbers.header":
            return "\tFY-4\tFY-3\tFY-2\tFY-1\tFY-0"
        parts = set(src.split("."))
        if {"series", "figures"} & parts:
            return ",".join(str(10 + i * 3) for i in range(6))
        if {"heads", "axis"} & parts:
            return "a,b,c,d"
        if "years" in parts:
            return "a,b,c,d,e,f"
        leaf = src.rsplit(".", 1)[-1]
        if leaf in ("versus", "reported", "expected", "latest", "label",
                    "headline_figure", "headline_label", "headline_kicker",
                    "last", "unit", "ticker", "kicker", "expected_label"):
            return "vs" if leaf == "versus" else "3.4%"
        return f"words for {leaf}"

    def image_for(self, src: str):
        return None

    def frac_box_for(self, src: str):
        return (0.4, 0.3, 0.12, 0.09)


@pytest.fixture(scope="module")
def reg():
    from config import Settings
    from pipeline.plates import load_plates
    return load_plates(Settings(_env_file=None).assets_dir)


def _words(duration: float = 70.0, n: int = 240) -> list[FakeWord]:
    step = duration / n
    return [FakeWord(f"w{i}", i * step, (i + 1) * step) for i in range(n)]


def _cut(fmt, reg, seed: str, *, resolver=None, avoid=()):
    """One whole build, as a `{shot id: plate key}` map."""
    fmt = expand_sequences(fmt, lambda _s: ["m1", "m2", "m3"])
    spans = resolve_spans(fmt, _words(), 70.0, {})
    result = build_layers(fmt, spans, resolver or StubResolver(), reg,
                          aspect=fmt.aspect, seed=seed, avoid=avoid)
    return fmt, result, {l.shot_id: l.entry_key
                         for l in result.layers if l.kind == "plate"}


# ---------------------------------------------------------------------------
# The alternates reach the screen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", VERTICAL)
def test_a_beat_with_alternates_does_not_draw_the_same_plate_every_time(
        name, reg):
    """The whole point. A fixed shot list drew one picture per beat, forever."""
    base = load_format(name)
    rotating = {sh.id for sh in base.shots if sh.alts}
    assert rotating, f"{name} declares no alternates at all"

    seen: dict[str, set[str]] = {}
    for i in range(12):
        _fmt, _result, plates = _cut(base, reg, f"seed-{i}")
        for shot_id, key in plates.items():
            seen.setdefault(shot_id.rsplit("-", 1)[0]
                            if shot_id[-1].isdigit() else shot_id,
                            set()).add(key)

    for shot_id in rotating:
        assert len(seen.get(shot_id, set())) > 1, (
            f"{name}/{shot_id} declares alternates and drew "
            f"{seen.get(shot_id)} across twelve videos")


@pytest.mark.parametrize("name", VERTICAL)
def test_every_alternate_composes_and_every_line_still_fits(name, reg):
    """A rotation that can produce a cut the renderer refuses is not a feature.

    The invariants and the budgets are checked on EVERY seed rather than on
    one, because the failure mode of a rotation is the seed nobody tried: a
    plate with a tighter box on the beat where the copy is longest, found by
    the fifteenth video rather than by the suite.
    """
    base = load_format(name)
    for i in range(16):
        fmt, result, _plates = _cut(base, reg, f"seed-{i}")
        problems = check_invariants(
            fmt, result,
            host_shots=[sh.id for sh in fmt.shots if sh.host])
        assert not problems, f"{name} seed-{i}: {problems[:3]}"
        over = check_budgets(fmt, result, reg)
        assert not over, f"{name} seed-{i}: {over[:3]}"


def test_the_rotation_steers_off_what_the_last_few_videos_used(reg):
    """`avoid` is the same preference the host and the rooms already take."""
    base = load_format("short")
    _fmt, _r, first = _cut(base, reg, "same-seed")
    hook = first["hook"]

    _fmt, _r, second = _cut(base, reg, "same-seed", avoid={hook})
    assert second["hook"] != hook, (
        "the hook card ignored a plate the last video already used")


def test_rotation_is_a_preference_and_never_fails_a_render(reg):
    """Every option used recently puts every option back on the table.

    The rule `_prefer_unused` has always had, asserted here because a beat
    whose alternates were ALL recent is exactly where a constraint masquerading
    as a preference would take a render down.
    """
    base = load_format("short")
    everything = set()
    for sh in base.shots:
        for v in sh.variants:
            everything.add(v.plate)
            everything.add(f"{v.plate}-9x16")
    _fmt, _result, plates = _cut(base, reg, "s", avoid=everything)
    assert plates, "avoiding everything drew nothing"


# ---------------------------------------------------------------------------
# An alternate is only chosen when it actually works
# ---------------------------------------------------------------------------

def test_an_alternate_the_script_cannot_fill_is_not_chosen(reg):
    """The wrong plate for THIS video, rather than the wrong plate.

    A required bind the script carries nothing for makes that drawing
    unusable — and quietly, since a required slot with no value is exactly the
    empty box the kit refuses to draw. The authored plate is the floor the
    chooser falls back to.
    """
    raw = json.loads(
        Path("templates/shots/short.json").read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        if shot["id"] == "the-comment":
            shot["alts"] = [{
                "plate": "cards/definition-9x16",
                # `turn_line` is optional on a script and this bind is not.
                "bind": {"term": "script.ticker",
                         "body": "script.turn_line"}}]
    raw.pop("orders", None)
    fmt = parse_format(raw)

    # With a turn line it is in the rotation ...
    reached = {_cut(fmt, reg, f"s{i}")[2]["the-comment"] for i in range(8)}
    assert "cards/definition-9x16" in reached

    # ... and without one it is never chosen, rather than drawn empty.
    blind = StubResolver(missing={"script.turn_line"})
    for i in range(8):
        _f, result, plates = _cut(fmt, reg, f"s{i}", resolver=blind)
        assert plates["the-comment"] == "cards/quote-pull-9x16"
        assert not result.unfilled, result.unfilled


def test_an_alternate_whose_box_cannot_hold_the_line_is_not_chosen(reg):
    """A rotation that ignored the budgets would fail on the LONG videos only.

    `check_budgets` refuses a required fill that runs over, so a plate picked
    without measuring trades sameness for a render that breaks after the
    writing and only for some seeds — the worst trade available. The same
    words always fit the authored plate, which stays in the set.
    """
    raw = json.loads(
        Path("templates/shots/short.json").read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        if shot["id"] == "close":
            # 58 characters against `structure/closing`'s 136.
            shot["alts"] = [{"plate": "structure/end-card-9x16",
                             "bind": {"line": "script.conclusion"}}]
    raw.pop("orders", None)
    fmt = parse_format(raw)

    class Long(StubResolver):
        def text_for(self, src):
            if src == "script.conclusion":
                return "a conclusion of rather more than fifty-eight " \
                       "characters, which is most of them"
            return super().text_for(src)

    class Short(StubResolver):
        def text_for(self, src):
            return "noise." if src == "script.conclusion" \
                else super().text_for(src)

    for i in range(8):
        _f, _r, plates = _cut(fmt, reg, f"s{i}", resolver=Long())
        assert plates["close"] == "structure/closing-9x16"
    reached = {_cut(fmt, reg, f"s{i}", resolver=Short())[2]["close"]
               for i in range(8)}
    assert "structure/end-card-9x16" in reached


def test_an_alternate_missing_from_the_kit_is_dropped_not_raised_on(reg):
    """A kit swap retires plates by name. That must degrade, not fail.

    The next drop drops `host/close-up` and four room angles outright. A
    rotation that hard-failed on a retired alternate would turn every swap into
    a render outage over a picture nothing needed.
    """
    raw = json.loads(
        Path("templates/shots/short.json").read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        if shot["id"] == "close":
            shot["alts"] = [{"plate": "structure/no-such-plate-9x16",
                             "bind": {"line": "script.conclusion"}}]
    raw.pop("orders", None)
    fmt = parse_format(raw)

    for i in range(6):
        _fmt, _result, plates = _cut(fmt, reg, f"s{i}")
        assert plates["close"] == "structure/closing-9x16"


def test_an_alternate_binding_a_slot_its_plate_lacks_is_not_drawn(reg):
    """`build_fill` refuses an undeclared slot, and it is right to.

    But a refusal here would take the whole render down over one of several
    interchangeable pictures, so the chooser tries the fill before it commits
    and moves on when it does not take.
    """
    raw = json.loads(
        Path("templates/shots/short.json").read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        if shot["id"] == "the-comment":
            shot["alts"] = [{"plate": "cards/criteria-9x16",
                             "bind": {"nonesuch": "script.numbers_comment"}}]
    raw.pop("orders", None)
    fmt = parse_format(raw)

    for i in range(6):
        _fmt, _result, plates = _cut(fmt, reg, f"s{i}")
        assert plates["the-comment"] == "cards/quote-pull-9x16"


# ---------------------------------------------------------------------------
# The budgets the writer is given
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", VERTICAL)
def test_the_budget_quoted_fits_every_plate_the_beat_may_land_on(name, reg):
    """THE ONE THING THE ROTATION MUST NOT COST.

    The writer is asked for a line long before the plate is picked, and the
    render REFUSES an over-budget fill rather than truncating it. So a budget
    read off the authored plate alone promises room an alternate may not have,
    and the failure arrives after the writing rather than during it.
    """
    from pipeline.compose import resolve_plate
    from pipeline.form import writer_fields
    from pipeline.plate_frames import budget

    fmt = load_format(name)
    quoted = {f.src: f.budget for f in writer_fields(name) if f.budget}

    for shot in fmt.shots:
        for variant in shot.variants:
            plate = resolve_plate(reg, variant.plate, fmt.aspect)
            if plate is None:
                continue
            bind, _lit, _focus = variant.resolved(shot)
            for slot_name, src in bind.items():
                # An OPTIONAL value that does not fit is left out of that
                # drawing rather than refused — the kit's own rule — so only
                # the required ones have to be promised room.
                if src.startswith("?") or src not in quoted:
                    continue
                slot = plate.slot(slot_name)
                if slot is None:
                    continue
                limit = budget(plate, slot).get("maxChars")
                if not limit:
                    continue
                assert quoted[src] <= int(limit), (
                    f"{name}/{shot.id}: the writer is promised "
                    f"{quoted[src]} characters for {src} and "
                    f"{plate.key}.{slot_name} holds {limit}")


# ---------------------------------------------------------------------------
# Authoring: what the parser refuses
# ---------------------------------------------------------------------------

def _tiny(**shot) -> dict:
    base = {"id": "a", "plate": "cards/quote-pull-9x16",
            "bind": {"body": "script.conclusion"}}
    base.update(shot)
    return {"format": "t", "aspect": "9x16", "frame": {"w": 1080, "h": 1920},
            "shots": [base]}


def test_a_declared_mark_lands_on_its_slot_after_the_shot_opens(reg):
    """The template grammar says `kind` and `target`; compose read `style`
    and `on`, so the first template to declare a mark would have stopped the
    build with an AttributeError. A mark on a slot the plate lacks is skipped
    and reported, like any other bind that finds nothing."""
    fmt = parse_format(_tiny(marks=[
        {"kind": "underline-swipe", "target": "body"},
        {"kind": "scrawl-oval-wide", "target": "no-such-slot"}]))
    _f, result, _plates = _cut(fmt, reg, "seed")
    shot = result.spans[0]
    marks = result.of_kind("mark")
    assert [(m.slot, round(m.t_start - shot.start, 3)) for m in marks] == \
        [("underline-swipe", 0.6)]
    assert "a.mark:scrawl-oval-wide <- no-such-slot" in result.skipped


def test_an_alternate_repeating_the_authored_plate_is_refused():
    """A duplicate is weight on the rotation, not another picture."""
    with pytest.raises(TemplateError, match="already names"):
        parse_format(_tiny(alts=[{"plate": "cards/quote-pull-9x16"}]))


def test_alternates_on_a_bare_ground_shot_are_refused():
    """The authored plate is what every alternate falls back to."""
    with pytest.raises(TemplateError, match="no plate of its own"):
        parse_format(_tiny(plate=None, bind=None,
                           text=[{"src": "script.conclusion",
                                  "size_fh": 0.05}],
                           alts=[{"plate": "cards/definition-9x16"}]))


def test_an_unknown_key_on_an_alternate_is_refused():
    """A template key the engine does not read is a silent no-op."""
    with pytest.raises(TemplateError, match="unknown key"):
        parse_format(_tiny(alts=[{"plate": "cards/definition-9x16",
                                  "plaet": "typo"}]))


def test_an_alternate_may_be_written_as_a_bare_plate_name():
    """The common case is a plate naming its slots the same way."""
    fmt = parse_format(_tiny(alts=["cards/definition-9x16"]))
    assert fmt.shots[0].alts[0].plate == "cards/definition-9x16"
    assert fmt.shots[0].alts[0].bind is None


# ---------------------------------------------------------------------------
# Cut orders
# ---------------------------------------------------------------------------

def _ordered(order: dict, **shot) -> dict:
    raw = {"format": "t", "aspect": "9x16", "frame": {"w": 1080, "h": 1920},
           "shots": [
               {"id": "one", "plate": "shorts/hook-card-t1",
                "anchor": "hook", "captions": False,
                "bind": {"hook": "script.hook_text"}},
               {"id": "two", "plate": "cards/quote-pull-9x16",
                "anchor": "turn", "bind": {"body": "script.turn_line"}},
               {"id": "three", "plate": "structure/closing-9x16",
                "bind": {"line-1": "script.conclusion"}},
           ],
           "orders": [order]}
    return raw


def test_an_order_must_name_every_shot_exactly_once():
    """Dropping a beat in an order would drop it silently."""
    with pytest.raises(TemplateError, match="Missing"):
        parse_format(_ordered({"name": "b", "shots": ["one", "two"]}))


def test_an_order_may_not_move_a_shot_the_narration_pins():
    """THE CEILING ON ALTERNATE ORDERS, AND IT IS NOT A CODE LIMIT.

    A shot with an anchor starts where its own words are spoken, and the words
    are one take written to the beat order the writing prompt states as fixed.
    Swap two anchored beats and the picture is over the wrong sentence —
    `resolve_spans` will not even let it try, because its monotonic pass drops
    an anchor landing before one already fixed, so the shot stops being
    anchored and interpolates to somewhere that matches nothing.
    """
    with pytest.raises(TemplateError, match="pins"):
        parse_format(_ordered({"name": "b",
                               "shots": ["two", "one", "three"]}))


def test_an_order_may_move_a_shot_the_narration_leaves_free():
    """The sign-off listens for nothing, so it can go anywhere after the open."""
    fmt = parse_format(_ordered({"name": "b",
                                 "shots": ["one", "three", "two"]}))
    assert [s.id for s in apply_order(fmt, "b").shots] == \
        ["one", "three", "two"]


def test_nothing_goes_ahead_of_the_opening_shot():
    """`sign-off-first` put the closing card ahead of the hook on every other
    earnings and macro short. The timing gave it a full even share of the
    opening while the hook was spoken over it, and dropped the hook's anchor
    for landing on top of it — the first seconds, spent on a sign-off."""
    with pytest.raises(TemplateError, match="opens on 'three'"):
        parse_format(_ordered({"name": "b",
                               "shots": ["three", "one", "two"]}))


@pytest.mark.parametrize("name", VERTICAL)
def test_every_order_opens_on_the_hook(name):
    fmt = load_format(name)
    assert fmt.shots[0].anchor == "hook"
    for order in order_names(fmt):
        assert apply_order(fmt, order).shots[0].id == fmt.shots[0].id, order


def test_two_shots_listening_for_the_same_words_may_swap():
    """`the-sheet` and `the-comment` both anchor on the numbers comment.

    They are interchangeable to the voice, which is what makes this the one
    swap the SHORT's narration leaves free.
    """
    fmt = load_format("short")
    assert "comment-first" in order_names(fmt)
    moved = [s.id for s in apply_order(fmt, "comment-first").shots]
    assert moved.index("the-comment") < moved.index("the-sheet")


def test_the_authored_order_is_always_in_the_rotation_and_never_listed():
    for name in VERTICAL:
        assert order_names(load_format(name))[0] == AS_AUTHORED
    with pytest.raises(TemplateError, match="always in the rotation"):
        parse_format(_ordered({"name": AS_AUTHORED,
                               "shots": ["one", "two", "three"]}))


def test_an_unknown_order_name_is_the_authored_one_rather_than_an_error():
    """A manifest outlives the template that wrote it.

    The order is recorded on a render and read back later, so a template that
    has since dropped one must not make an old workspace unrenderable.
    """
    fmt = load_format("short")
    assert [s.id for s in apply_order(fmt, "retired-last-year").shots] == \
        [s.id for s in fmt.shots]


def test_the_cut_order_rotates_off_the_recent_ones():
    fmt = load_format("short")
    names = set(order_names(fmt))
    picked = {choose_order(fmt, seed=f"s{i}") for i in range(20)}
    assert picked == names, picked
    # Everything recent puts everything back, the same preference the plates
    # take — a rotation must never fail for want of a fresh sequence.
    assert choose_order(fmt, seed="s", avoid=names) in names


@pytest.mark.parametrize("name", VERTICAL)
def test_every_declared_order_cuts_a_whole_video(name, reg):
    for order in order_names(name and load_format(name)):
        fmt = apply_order(load_format(name), order)
        f, result, plates = _cut(fmt, reg, "seed")
        problems = check_invariants(
            f, result, host_shots=[sh.id for sh in f.shots if sh.host])
        assert not problems, f"{name}/{order}: {problems[:3]}"
        assert not check_budgets(f, result, reg)


# ---------------------------------------------------------------------------
# The seams
# ---------------------------------------------------------------------------

def test_a_sequence_repeat_steps_its_alternates_binds_too():
    """MACRO's consequences are one card per beat, on either card.

    The step number is substituted into the authored bind; an alternate that
    did not step with it placed a literal `$n` on the frame the moment the
    rotation picked it.
    """
    fmt = expand_sequences(load_format("macro"),
                           lambda _s: ["c1", "c2", "c3"])
    steps = [sh for sh in fmt.shots if sh.id.startswith("who-it-hits-")]
    assert len(steps) == 3
    for n, shot in enumerate(steps, 1):
        for variant in shot.variants:
            bind, _lit, _focus = variant.resolved(shot)
            body = bind["body"]
            assert "$n" not in body, (shot.id, variant.plate, body)
            assert body.endswith(str(n - 1)), (shot.id, variant.plate, body)


def test_the_manifest_records_which_order_the_video_was_cut_in(settings,
                                                               tmp_path):
    """`recent_orders` reads this back exactly as `recent_plates` reads plates.

    Without it the rotation has nothing to steer off and every video is a fresh
    coin toss, which is how three in a row come out identical.
    """
    from pipeline.reach import recent_orders

    work = Path(settings.workspace_dir) / "EXMPL" / "2026-01-01"
    work.mkdir(parents=True)
    (work / "short_manifest.json").write_text(
        json.dumps({"shot_order": "comment-first",
                    "plates_used": ["cards/quote-pull-9x16"]}),
        encoding="utf-8")
    assert recent_orders(settings) == {"comment-first"}
    # A renderer MUST exclude its own workspace, or a second pass reads the
    # manifest its first pass wrote and cuts the same video differently.
    assert recent_orders(settings, exclude=work) == set()


def test_a_manifest_from_before_the_field_existed_contributes_nothing(
        settings):
    """A rotation hint that cannot be built does not apply; it never errors."""
    from pipeline.reach import recent_orders

    work = Path(settings.workspace_dir) / "OLD" / "2025-01-01"
    work.mkdir(parents=True)
    (work / "short_manifest.json").write_text(
        json.dumps({"plates_used": ["cards/quote-pull-9x16"]}),
        encoding="utf-8")
    assert recent_orders(settings) == set()


def test_the_reachability_report_counts_an_alternate_as_a_template_route(reg):
    """The census that found 55 stranded 9:16 plates reads this.

    An alternate puts a plate on screen with no writer involved, which is what
    `template` means. Counting only the authored plate reported drawings the
    templates were actively reaching for as having no route to a frame.
    """
    from pipeline.gates import reachable_plates

    routes = reachable_plates(reg)
    for key in ("shorts/hook-card-t3", "figures/compare-side-9x16",
                "cards/definition-9x16", "paper/headline-band-t3-9x16",
                "tables/numbers-sheet-4r-spark-9x16",
                "structure/confession-statement-9x16",
                # round one's phone plates
                "shorts/hook-card-t5", "figures/move-on-the-day-9x16",
                "figures/move-on-the-day-up-9x16", "structure/closing-t2-9x16",
                "structure/before-after-9x16"):
        assert key in routes["template"], key


@pytest.mark.parametrize("name", VERTICAL)
def test_the_rotation_never_asks_the_writer_for_a_shorter_line(name, tmp_path):
    """THE PRICE THE VARIETY IS NOT ALLOWED TO COST.

    An alternate narrows the quoted budget wherever it REQUIRES the value, and
    that narrowing is correct — the render refuses an over-budget required fill
    rather than truncating it, so the writer has to be told the smallest box
    the beat may land in. What it must not do is narrow the ask past the limit
    the SCRIPT MODEL already gives the writer: then a line written to the
    brief gets refused, and the rotation has quietly rewritten the brief.

    `structure/end-card` holds 58 characters where `structure/closing` holds
    136 and a conclusion is written to 220. That is why the sign-off's
    alternate is `cards/quote-pull` and not the end card, and this is the test
    that said so.
    """
    import json as _json

    from pipeline.form import writer_fields
    from pipeline.models import ShortScript

    def cap(field_name: str) -> int | None:
        info = ShortScript.model_fields.get(field_name.split(".")[0])
        if info is None:
            return None
        return next((getattr(m, "max_length", None)
                     for m in (info.metadata or ())
                     if getattr(m, "max_length", None)), None)

    # The same format with every alternate stripped: what the writer was asked
    # for before any of this, and the number no alternate may undercut.
    raw = _json.loads(Path(f"templates/shots/{name}.json")
                      .read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        shot.pop("alts", None)
    root = tmp_path
    (root / "templates" / "shots").mkdir(parents=True)
    (root / "templates" / "shots" / f"{name}.json").write_text(
        _json.dumps(raw), encoding="utf-8")
    authored = {f.src: f.budget for f in writer_fields(name, root)}

    for field in writer_fields(name):
        was, now = authored.get(field.src), field.budget
        if was is None or now is None or now >= was:
            continue
        # THE TICKER IS NOT A LINE SOMEBODY WRITES. The model caps it at 15 to
        # refuse nonsense, not to promise room; `short.json` has quoted the
        # nine `shorts/hook-card-t1` holds since before any of this, so nine is
        # already this channel's real ticker budget and an alternate adopting
        # it introduces nothing.
        if field.name.split(".")[0] == "ticker":
            continue
        allowed = cap(field.name)
        assert allowed is not None and now >= int(allowed), (
            f"{name}: an alternate narrows {field.src} from {was} to {now}, "
            f"and the writer may write {allowed}")


# ---------------------------------------------------------------------------
# Round one's phone plates
# ---------------------------------------------------------------------------

def _script(**over):
    from pipeline.models import ShortScript

    data = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A muted hook line here.",
        "audio_script": "Numbers first. Then the point. Noise.",
        "move_summary": "+34% today · 6× average volume",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [{"label": "Rev", "values": ["$1M"] * 5 + ["$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    data.update(over)
    return ShortScript.model_validate(data)


def _real(script, tmp_path):
    """The render's own resolver, with no price data loaded."""
    from config import Settings
    from pipeline.render_short import ShortResolver

    return ShortResolver(script=script, workdir=tmp_path,
                         settings=Settings(_env_file=None), prices=None,
                         handle="@channel")


@pytest.mark.parametrize("summary, want", [
    ("+34% today · 6× average volume", "figures/move-on-the-day-up-9x16"),
    ("-8.5% · guidance cut", "figures/move-on-the-day-9x16"),
    ("\u221212% after the call", "figures/move-on-the-day-9x16"),
    ("+0% · flat into the print", "charts/line-dense-9x16"),
    ("Q3 print · guide raised", "charts/line-dense-9x16"),
])
def test_the_move_is_drawn_with_the_arrow_its_sign_calls_for(summary, want, reg,
                                                             tmp_path):
    """The two move plates DRAW their arrow, so each is the right picture for
    one direction only. The figure is offered to a plate only when the move
    summary opens on a sign that says which; a summary that opens on words, or
    on a flat day, reaches neither and the beat keeps its authored chart.

    No prices are loaded here, which is also the case this helps most: the
    chart has nothing to draw, and the move plate needs nothing but the line
    the writer already wrote.
    """
    from pipeline.compose import choose_variant

    fmt = load_format("short")
    shot = next(s for s in fmt.shots if s.id == "the-move")
    resolver = _real(_script(move_summary=summary), tmp_path)
    for i in range(6):
        assert choose_variant(reg, shot, fmt.aspect, resolver,
                              seed=f"s{i}").plate == want


def test_the_move_figure_and_its_label_come_off_the_summary(tmp_path):
    up = _real(_script(move_summary="+34% today · 6× average volume"), tmp_path)
    assert up.text_for("chart.move_up") == "+34%"
    assert up.text_for("chart.move_down") is None
    assert up.text_for("chart.move_detail") == "today · 6× average volume"
    down = _real(_script(move_summary="-8.5% · guidance cut"), tmp_path)
    assert down.text_for("chart.move_down") == "-8.5%"
    assert down.text_for("chart.move_up") is None
    words = _real(_script(move_summary="Q3 print · guide raised"), tmp_path)
    assert words.text_for("chart.move_detail") is None


@pytest.mark.parametrize("name", VERTICAL)
def test_no_caption_runs_under_a_figure_the_plate_sets_at_display_size(name, reg):
    """Large type and the caption band never share a shot, WHICHEVER drawing
    the rotation picked. The template's `captions` flag is the shot's and
    cannot know the plate: the payoff says false by hand for `big-number`, and
    the move on the day, an alternate, sets its figure just as large."""
    from pipeline.shots import LARGE_TYPE_FH

    base = load_format(name)
    for i in range(12):
        fmt, result, _plates = _cut(base, reg, f"seed-{i}")
        captioned = {l.shot_id for l in result.layers if l.kind == "caption"}
        for layer in result.layers:
            if layer.kind != "plate" or layer.shot_id not in captioned:
                continue
            plate = reg.get(layer.entry_key)
            k = layer.h / plate.canvas[1] / fmt.frame[1]
            big = [n for n, v in (layer.values or {}).items()
                   if plate.slot(n) is not None and str(v).strip()
                   and float((plate.type_roles.get(plate.slot(n).role) or {})
                             .get("size") or 0) * k >= LARGE_TYPE_FH]
            assert not big, (f"{name} seed-{i}: captions run under "
                             f"{layer.entry_key}'s {big}")


@pytest.mark.parametrize("name", ("earnings", "macro"))
def test_before_and_after_is_only_drawn_against_a_real_expectation(name, reg):
    """`structure/before-after`'s caution: without a prior expectation it reads
    as a comparison against a number the plate invented. So the consensus is a
    REQUIRED bind there, and a script without one never lands on it."""
    base = load_format(name)
    reached = {_cut(base, reg, f"s{i}")[2]["vs-expected"] for i in range(12)}
    assert "structure/before-after-9x16" in reached
    blind = StubResolver(missing={"compare.expected"})
    for i in range(12):
        _f, _result, plates = _cut(base, reg, f"s{i}", resolver=blind)
        assert plates["vs-expected"] != "structure/before-after-9x16"

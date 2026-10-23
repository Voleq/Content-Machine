# Visual code items (V3, V4, V5, V7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The long's ending holds a clear end screen, a short opens on Dennis and its big number, and two new render notes catch type too small for a phone and a video that looks like the last few.

**Architecture:** Each item is a small pure module under `pipeline/` with its own tests, wired into the renderer at one point and reported through the render's manifest. The bot turns the manifest into lines on the delivery message (Telegram) and the page's Proof and Upload steps, as `_frame_holds` already does for the short.

**Tech Stack:** Python 3.11, Pillow, ffmpeg, the plate registry (`pipeline/plates.py`), the 3D performer (`pipeline/dennis3d.py`).

**Spec:** Claude Doc "Build plan: your picks and the web page" (Visuals table, rows V3, V4, V5, V7), https://claude.ai/code/artifact/2fef74dc-c79a-44db-bf87-4ed649a04478

## Global Constraints

- 3D Dennis only; one plate look, paper. No new plates from design: anything new is drawn bot-side from the kit's own type roles and inks.
- Warnings never block a render; every line names where it is and the fix.
- Web media stays full screen; memes stay off in shorts.
- No new paid calls. Render time grows only where the spec needs Dennis on screen.
- Tests never read his `.env` (`Settings(_env_file=None)`).

## Decisions taken here

- **V3.** YouTube's end screen covers the last 5 to 20 s and Studio places it by hand (the API cannot). The bot guarantees the last 20 s are one shot of him, extends the video with a quiet tail when the sign-off is shorter (he idles, the outro theme ends with the video), and picks an end room whose free side clears his figure and the NOT FINANCIAL ADVICE sign. The manifest records `end_screen: {start, end, side, rect}`; the Upload step and the Studio checklist say "End screen from M:SS, boxes on the right".
- **V4.** Today's first frame is the hook card: type on paper, no number at size, no Dennis. A short now opens on a cold shot of up to 1.6 s (ending at the first sentence's end if sooner): Dennis in close-up in the turn's room, with the big number on a strip of paper above him, set at the kit's `huge` role. The number never counts up in this shot, so frame one carries it final. The big number is the day's move, else the reported print, else the payoff figure. The hook card follows as now.
- **V5.** Measured as a phone held sideways: the frame is 640 px wide on the phone. Text whose set size is under 7 px there (21 units of a 1920-wide canvas) is flagged. The kit's own declared sizes all pass (smallest 21-22), so what flags is type the fitter shrank and bot-drawn text.
- **V7.** After a proof or final, the plate order (base keys of plate beats) and the room order (base keys of his beats) are compared with the last 3 longs or 5 shorts of other videos, by `difflib.SequenceMatcher` ratio. A plate ratio of 0.75 or more, or a room ratio of 0.8 or more, is a warning naming the video it matches.

## Review Focus

1. A long whose last beat is a plate or a clip: the tail must still give 20 s of him, never an end screen over evidence.
2. A video under 33 min with the end wipe, and one over with the clock close: the end shot starts after the cover, and the 20 s count from there.
3. No outro theme on disk: the tail must still be in the audio (silence padded), or the mux cuts the video back to the voice.
4. A short whose script has no move, no print and no payoff figure: the cold shot still opens on him, with the ticker strip only, and says so in the manifest.
5. A first video with no earlier manifests, and manifests from before this change without the new fields: V7 stays silent, never errors.

---

### Task 1: The end screen (V3)

**Files:**
- Create: `pipeline/end_screen.py`
- Modify: `pipeline/render_long.py` (after `plan_long_segments`, the end room pick, `theme_tracks` call, the audio pad, the manifest)
- Modify: `bot/panel_views.py` (Upload step line), `pipeline/publish.py` or wherever the Studio checklist text lives
- Test: `tests/test_end_screen.py`

**Interfaces:**
- Produces: `END_SCREEN_S = 20.0`; `end_tail(segments: list[Segment], voice_end: float) -> float`; `extend_for_end(segments, voice_end) -> tuple[list[Segment], float]` (returns the segments with the last host beat stretched, or a host beat appended, and the video's new end); `clear_side(frame: tuple[int, int], him: tuple[int, int, int, int], sign: list[tuple[float, float]] | None) -> tuple[str, tuple[int, int, int, int]] | None`; `ZONE_W = 0.36`, `ZONE_Y = (0.14, 0.86)`, `ZONE_MARGIN = 0.03`.

- [ ] Step 1: tests: `test_a_short_sign_off_gets_a_tail` (last host beat starts 8 s before a 600 s voice end: tail 12, last segment ends at 612); `test_a_long_last_beat_needs_no_tail`; `test_a_last_plate_gets_a_beat_of_him` (last segment kind "plate": a host segment of 20 s appended); `test_the_side_clears_him_and_the_sign` (him at x 0.07-0.34: "right"; a sign quad inside the right zone: "left" or None).
- [ ] Step 2: run, expect import failure.
- [ ] Step 3: implement `pipeline/end_screen.py`.
- [ ] Step 4: wire into `render_long`: tail after the plan, `duration` becomes the video's end from there on (the voice keeps `tts.duration_s`); the last beat's room chosen among the rooms the rotation allows where `clear_side` finds a side for the room's host anchor and its sign (`writable["labels"]["items"]` kind "stitch"); after his layer is drawn, re-check with `dennis3d.extent`; pad the mix to the video's end; manifest `end_screen`.
- [ ] Step 5: render test on the fixture long: manifest `end_screen.end - end_screen.start >= 20`, the file's duration matches, the audio stream runs to the end.
- [ ] Step 6: Upload step and Studio checklist read `end_screen`; test in `tests/test_panel_*`.
- [ ] Step 7: commit.

### Task 2: A short opens on Dennis and its number (V4)

**Files:**
- Modify: `templates/shots/short.json`, `earnings.json`, `macro.json` (a `cold` shot first, or an `opener` block the resolver splits off the hook's span)
- Modify: `pipeline/shots.py` (`resolve_spans` gives the cold shot `[0, min(1.6, first sentence end)]`), `pipeline/render_short.py` (no count-up on the cold shot; the number strip)
- Test: `tests/test_short_opens_on_him.py`

**Interfaces:**
- Produces: `COLD_OPEN_S = 1.6`; `big_number(script, data) -> tuple[str, str]` (value, where it came from: "move" | "print" | "payoff" | ""); manifest `opening: {"number": str, "from": str, "host": bool}`.

- [ ] Step 1: tests: the first span is the cold shot with a host; it ends by 1.6 s; the hook span follows; `big_number` picks move, then print, then payoff; the plan schedules no move on the cold shot; frame 0 of a mock render carries the number's ink in the strip box (pixel check against the paper ground).
- [ ] Step 2: run, expect failure.
- [ ] Step 3: implement.
- [ ] Step 4: run the short suites (`tests/test_short_*`, `tests/test_shorts_phase1.py`, `tests/test_parser_short.py`).
- [ ] Step 5: commit.

### Task 3: Type too small for a phone (V5)

**Files:**
- Create: `pipeline/phone_type.py`
- Modify: `pipeline/plate_frames.py` (`fill_slot` reports the size it set to a recorder when one is active), `pipeline/render_long.py` (records per beat, manifest `phone_type`), `bot/handlers.py` (delivery note)
- Test: `tests/test_phone_type.py`

**Interfaces:**
- Produces: `PHONE_W = 640`, `MIN_PHONE_PX = 7.0`; `recording() -> contextmanager[list[dict]]` (rows `{plate, slot, text, units, canvas_w}`); `findings(rows, at: dict[str, float]) -> list[dict]` (`{plate, slot, text, phone_px, t}`); `report(manifest: dict) -> str`.

- [ ] Step 1: tests: a 22-unit row passes; a 16-unit row on a 1920 canvas flags at 5.3 px with the plate and slot named; `report` names the time and says "shorten the line or split it"; an old manifest gives "".
- [ ] Step 2-4: implement, wire, run `tests/test_render_long.py` and the new tests.
- [ ] Step 5: commit.

### Task 4: A video that looks like the last few (V7)

**Files:**
- Create: `pipeline/visual_sameness.py`
- Modify: `pipeline/render_long.py` (seg meta gains `plate` on plate beats and `room` on his beats), `pipeline/render_short.py` (its shots already carry plates and rooms; confirm), `bot/handlers.py` (delivery note)
- Test: `tests/test_visual_sameness.py`

**Interfaces:**
- Produces: `orders(manifest) -> tuple[list[str], list[str]]` (plates, rooms as base keys); `recent(settings, fmt, exclude: Path, n) -> list[tuple[str, dict]]` (label, manifest), globbing `*/*/*manifest*.json` as `_recorded_cold_opens` does; `compare(manifest, recent) -> list[dict]`; `report(found) -> str`. `PLATE_RATIO = 0.75`, `ROOM_RATIO = 0.8`, `LONGS_BACK = 3`, `SHORTS_BACK = 5`.

- [ ] Step 1: tests: identical orders flag with the other video named; a reordered half passes; no history is silent; a manifest without `plate`/`room` fields is skipped.
- [ ] Step 2-4: implement, wire, run.
- [ ] Step 5: commit.

### Task 5: Show the notes on the page and Telegram

- [ ] Proof and Render steps on the page list `phone_type`, `visual_sameness` and `end_screen` lines from the manifest; Telegram's delivery note carries the same text.
- [ ] Full suite (two shards), then merge to `claude/new-session-lxhson`.

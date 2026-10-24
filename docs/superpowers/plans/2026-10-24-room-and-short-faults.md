# Room renders and the short's faults (V8, V10, V12 pile, room picks 2 3 4 6 7 8)

**Goal:** the four known short faults fixed, a real dusk and a rain set, the
10-K pile that grows by one per public long, and the room picks, then one
full re-render of every angle.

**Spec:** build plan doc rev 9 (V8, V10, V12; room picks 2, 3, 4, 6, 7, 8 from
the thread, 10-18 21:35).

## Global constraints

- 3D Dennis only; paper plates only; anything per video is bot-written.
- One full re-render (EXRs are not kept): every room change is built and
  previewed first, then 64 angles rendered in resumable chunks, committed in
  batches. He reruns `python scripts/ingest_kit.py kit` after pulling.
- Tests never read his .env; targeted tests per change, the full suite once.

## What each fault turned out to be (checked 10-24 on sample shorts)

- **Evening colours:** a short at dusk failed on its first shot: the opener
  bound its room by the dusk key, which a registry viewed at dusk does not
  know (`compose._bound_values`). The mock stand-in card set its words in
  the hour's `structure` ink, dark violet on a dark picture at dusk. Plates
  are paper at both hours, so nothing else differs; the room at dusk is the
  night render until V10.
- **Sparse cards:** the 9:16 plates keep the kit's margins, so a card like
  NET INCOME uses the top quarter of the phone and leaves the rest bare.
- **Floor paper:** board-wide, doorway, doorway-wide and panel-left (9:16)
  have nothing in front of him since the floor stacks went.
- **Turn to screen (9:16):** the camera leaves the monitor just out of shot.

## Tasks

1. **Dusk short** - `_bound_values` binds `plate.base_key`; stand-in card ink
   is the lighter of the hour's structure and ground. Test: a short composes
   at dusk.
2. **Fill the phone** - `compose.fill_safe`: on a 9:16 plate shot with no
   host, focus or two-shot, the plate's ink box (rendered last frame, off
   its paper) is scaled up to fill the safe band less a caption row, at most
   `FILL_MAX` 1.5, centred; skipped under 1.08. Tests: the NET INCOME card
   grows and stays inside the band; a room or a focus shot is untouched.
3. **Room build** (`room3d/build.py`, `textures.py`):
   - one light group a sky (`sky`, `sky_rain`, `sky_dusk`, `sky_dusk_rain`;
     December's snow twins), each a see-through pane in front of a black
     backing with its own light into the room, and `laundromat` (pick 8:
     warm light up from the street under the window); a state is a mix of
     groups, a weight may be a tint; `apply_state` lights perform's room;
   - states: plain `""`, `_rain`, `_dusk`, `_dusk_rain`; December `_t0..2`
     and `_t0..2_dusk`; the unused dips go;
   - skies: night (with the laundromat glow), dusk, rain, and the snow twins;
   - props: Mum's DENNIS (AGAIN) jar on the bookcase (3), the framed loss
     post by the margin call (4), a crumpled blanket and a bed pillow (6),
     a tag in the plant pot (2, lettered `plant`), the phone's screen
     (7, lettered `phone`), floor paper in front of him on the four phone
     angles (V8);
   - the 9:16 turn-to-screen camera re-aimed so the monitor is in shot.
4. **Ingest** - dusk rooms from the `_dusk` states; rain on every room with
   a window in shot (outside December), from `_rain`, streaks plus drops on
   the glass.
5. **Writing** - the plant tag is the latest broken thesis's ticker (else
   "No. 14"); the phone lights with "Kev: thoughts?" only when the script
   carries Kev's tip; lit, not inked.
6. **The pile (V12)** - perform renders the pile alone (`props` job: count,
   angle, light state) as an overlay with its shadow; the dressing lays it
   on every room picture of the video. Count = public longs; 24 to a pile,
   a second pile beside it, capped at 48. Perform also lights him for the
   hour (`light` key), so he is lit for dusk and rain like the room.
7. **Dusk on** - after a dusk long and short are watched end to end,
   `kit/roles.json` hours episodes `["night", "night", "night", "dusk"]`.
8. **Render, ingest, test, merge.**

# audit/

Both files here are **generated, not authored** — `proof/preflight.html` writes
them from its two buttons.

```
baseline-14.json    per-frame hashes of every asset. The acceptance baseline.
breathe-map.json    per-plate share of ink that breathes, and why each
                    still-by-design plate is still.
```

## They are in the pack now

They were absent from the last one, and correctly: they had gone stale the moment
drop two landed — 472 frames became 708, and §1.4's settle renumbers frames on
cards, figures and paper. A stale baseline that someone trusts is worse than an
absent one, because it reports a diff on every plate that moved for a good reason,
which trains people to ignore it.

The pair here was generated from the engine in this pack: **218 assets, 760
frames, 0 errors**, 106 gated plates, ink breathing 0.0%–67.6%, pin mechanism
true/true, no plate frozen without being on the still-by-design list.

The build is deterministic, so **the copy you generate from the engine you are
holding still beats the copy shipped here.** Click both buttons in
`proof/preflight.html` and compare; they should be identical, and if they are not,
that difference is the thing to look at before anything else.

§1's title ground does not appear in either file: `engine/build.js`
`TITLE_GROUND` is `null`, so `room/` is byte-identical to delta-14. Turning a
treatment on resets `room/` — 22 assets, 66 frames — and nothing else.

§2's ten quarter assets DO appear, as 34 new frames (30 gated frames plus
`figures/qoq-yoy`'s four settle frames). Every pre-existing frame in `charts/` and
`figures/` is byte-identical to delta-14 — hashed both ways, 218 frames, 0
changed — so the only diff against the previous baseline in those two families is
an addition.

## When to regenerate

After any engine change, before using the baseline to check anything. The next
pack is checked against the file generated at the end of *this* one — that is the
whole point of it, and it only works if the copy in hand matches the engine that
shipped.


## What the baseline cannot see, and it matters

`baseline-14.json` hashes the **emitted SVG**. A slot is not drawn, so **slot
geometry is invisible to it** — narrowing `structure/language-shift`'s year box
from 32% of the measure to 22% changed every budget on that slot and produced
**zero** baseline diffs, correctly.

That is a blind spot rather than a bug: the renderer composites against slot
boxes, so a slot moving is exactly the kind of change the pipeline cares about
and this file will never report. Two things follow.

- A pack that changes only slot geometry looks byte-identical here. Say so in
  CHANGES rather than letting the clean baseline imply nothing moved.
- `proof/preflight.html` is where slot changes get caught, because its checks
  read the manifest. Checks **I, J, K, L, N and O** all assert slot geometry;
  the baseline asserts ink. They are not redundant and neither replaces the
  other.

A manifest baseline alongside this one would close it. Not written — it wants a
decision about what counts as a meaningful slot diff (every box shifts by a unit
when a type role changes size, and a file that reports 200 diffs on a deliberate
type change is the stale-baseline problem again).

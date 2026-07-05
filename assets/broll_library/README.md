# Owned B-roll library

Drop your OWNED, curated ironic clips here — they always win over cache
and Pexels in the `[CLIP]` resolution order.

Naming: `<palette_key>.mp4` for the primary clip, `<palette_key>__2.mp4`,
`<palette_key>__3.mp4`… for swap alternates. Accepted containers:
mp4 / mov / mkv / webm. Clips are normalized (project resolution, fps,
duration cap, audio stripped) into the cache on first use — the
originals here are never modified.

The valid palette keys are defined in `pipeline/broll.py` (PALETTE).
Owned memes live next door in `assets/meme_library/` (see its
`meme_index.json`), and bespoke Claude-Design visuals for `[ASSET]` tags
go in `assets/custom/`.

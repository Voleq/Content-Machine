# Owned B-roll library

Drop your OWNED, curated ironic clips here — they always win over cache
and Pexels (§6 resolution order).

Naming: `<palette_key>.mp4` for the primary clip, `<palette_key>__2.mp4`,
`<palette_key>__3.mp4`… for swap alternates. Accepted containers:
mp4 / mov / mkv / webm. Clips are normalized (16:9 project resolution,
fps, duration cap, audio stripped) into the cache on first use — the
originals here are never modified.

The valid palette keys are defined in `pipeline/broll.py` (PALETTE).

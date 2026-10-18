# Audio items (A5–A11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The picked audio items work from the bot and Telegram, ready for the page (phase 3) to put buttons on: a pronunciation list sent to ElevenLabs only, the fresh voice pushed to Telegram as soon as it lands, one-sentence redos spliced in, room tone and a de-esser behind switches that ship off, body sounds cued from the 3D motion, and a phone-speaker check on the finished mix.

**Architecture:** Pronunciations are substitutions applied after `expand_delivery`, outside its inserted spans, with an edit list that `remap_to_clean` undoes, so captions and timings stay on the clean words. A voice that already exists is never re-keyed by a later list change: an index of generated variants per base request is consulted first. A sentence redo is a paid fragment under the same spend fence, spliced into the cache entry in use, keeping the original. A8/A9 are extra filters in `render_common.audio_graph` on the voice track. A10 exports body events from the Blender worker into `perf.json`. A11 renders audio-only stems through the same graph and measures them through a phone filter.

**Tech Stack:** Python 3.11, ffmpeg filters (`aecho`, `equalizer`, `deesser`, `highpass`, `lowpass`, `astats`, `acrossfade`), pytest.

**Spec:** Claude Doc "Build plan: your picks and the web page" (rev 9), section Audio; design copy in the session scratchpad. His calls: render starts at once when the voice lands (A6), a redo keeps the same words and is capped at 10 per video (A7), A8/A9 ship off until he hears a clip cut from his first paid voice.

## Global Constraints

- Pronunciations reach the text sent to ElevenLabs (paid tier) only, never captions, plates, words.json or the corpus.
- Every paid call goes through `SpendLedger.reserve_tts_spend` / `record_tts`; nothing paid runs in tests (mock tier).
- A list change never re-bills a voice that already exists.
- `VOICE_ROOM=false`, `VOICE_DEESS=false` by default.
- No new installs: ffmpeg filters that ship with ffmpeg only.
- Telegram: new commands only where they help remotely (listen, redo, fix a word, compare clip).

## Review Focus

- A rule word inside a delivery tag span (`[SIGH]`) is never substituted — test in Task 1.
- A rule that turns one word into three ("EBITDA" → "ee bit dah") still gives ONE clean word with the first start and the last end — Task 1.
- A rule added after the paid voice exists: `is_cached` stays true and `billable_chars` unchanged — Task 2.
- A redo on a sentence at the very start or end of the audio splices without a gap or a clipped word — Task 4.
- A body-sound key with no sound files fetched yet plays nothing and blocks nothing — Task 6.

---

### Task 1: Pronunciation rules (A5 core)

**Files:** Create `pipeline/pronounce.py`, `assets/writing/pronunciations.txt`; modify `pipeline/writing_files.py` (`WRITING_FILES["pronunciations"]`); test `tests/test_pronounce.py`.

**Interfaces:**
- `@dataclass Rule(word: str, said: str)`; file lines `WORD => spoken form`, `#` comments; matching whole-word, case-sensitive.
- `load_rules(settings) -> list[Rule]`; `add_rule(settings, word, said)`, `remove_rule(settings, word) -> bool` (edit the state copy via `writing_files.write_text`).
- `apply_rules(text, rules, protect=()) -> tuple[str, list[Edit]]`, `Edit(src_start, src_end, dst_start, dst_end)`; no match inside a `protect` span.
- `undo_rules(words, edits, src_text) -> list[WordTimestamp]`: request words inside an edit's dst span merge into one word `src_text[src_start:src_end]` (first start, last end); words after shift back by the summed length change.
- `rules_hitting(text, rules) -> list[Rule]`.
- Default list: `EBITDA => ee-bit-dah` active; examples commented.

- [ ] Tests: `test_apply_and_undo_merge_one_word`, `test_protected_span_untouched`, `test_case_and_whole_word`, `test_add_remove_rule_roundtrip`, `test_rules_hitting`.
- [ ] Implement, run, commit `feat(voice): A5 pronunciation rules`.

### Task 2: Pronunciations in the TTS request, pinned per voice

**Files:** Modify `pipeline/tts.py` (`_cache_dir`, `synthesize`, remap), test `tests/test_pronounce_tts.py`.

**Interfaces:**
- Paid tier only: after `expand_delivery`, `apply_rules(req_text, rules_hitting(...), protect=spans)`; the rule set joins the key as `keyed["_say"]` only when non-empty (an empty set keeps today's key).
- `cache_dir/tts/say_index.json`: `{base_key: [rules_json, …]}` newest last, where base_key is the key with no rules. Lookup order: live rules' dir if complete → newest indexed variant complete → base (no rules) complete → generate with live rules, then index it.
- remap: `undo_rules` first, then `_remap_by_spans`.

- [ ] Tests (mock tier forced to paid through a fake `_generate_real`): `test_request_carries_the_spoken_form`, `test_words_stay_clean`, `test_rule_added_after_voice_keeps_cache`, `test_new_script_uses_rules`, `test_mock_and_local_get_no_rules`.
- [ ] Implement, run `tests/test_tts*.py tests/test_pronounce*.py`, commit `feat(voice): A5 rules reach ElevenLabs only, pinned per voice`.

### Task 3: Hear the voice (A6) and the `/voice` family

**Files:** Modify `bot/handlers.py` (`_execute_job` short and long: after a fresh non-cached paid voice, `push_file(audio, caption)` with "🎙 {T} {fmt} voice is in; the render has started. Stop it: /cancel {T}"), `bot/commands.py` (Family `voice`; `/voice` = the voice file plus numbered sentences with times; `/voice say [WORD => spoken]` lists or adds and names the sentences of the active video that contain it; `/voice unsay WORD`), README regenerated; test `tests/test_voice_commands.py`.

**Interfaces:** `BotCore.voice_listing(chat_id) -> Reply`, `BotCore.say_command(chat_id, raw) -> Reply`, `BotCore.unsay_command(args) -> Reply`; `pipeline/voice_redo.sentences(words, clean_text) -> list[SpokenSentence(index, text, start, end, char_start, char_end)]` (Task 4 builds on it, so it lands here).

- [ ] Tests: `test_listing_numbers_sentences_with_times`, `test_say_adds_and_names_sentences`, `test_unsay`, `test_voice_pushed_once_when_fresh` (fake pusher; cached run pushes nothing).
- [ ] Implement, run, commit `feat(voice): A6 the voice goes to Telegram as it lands; /voice`.

### Task 4: Redo one sentence (A7)

**Files:** Create `pipeline/voice_redo.py`; modify `pipeline/tts.py` (`TTSEngine.voice_dir(text, fmt, events) -> Path | None` for the entry in use; `synthesize_fragment(text, fmt, ticker) -> TTSResult` under `cache_dir/tts/fragments/<key>`, same tier rules, fence and ledger, live pronunciations), `bot/handlers.py` + `bot/commands.py` (`/voice redo N`), test `tests/test_voice_redo.py`.

**Interfaces:** `MAX_REDOS = 10`; `redo_sentence(engine, settings, *, text, fmt, events, index, ticker, ws_path) -> RedoResult(index, old_s, new_s, cost_usd, left)`. Fragment trimmed of edge silence (`silenceremove` start and end, -45 dB), spliced at the sentence's word window ±0.04 s with 15 ms `acrossfade` both sides; `audio.orig.m4a` kept once; words after the window shift by the length change; `voice_redos_{fmt}.json` in the workspace counts redos (refuses the 11th). After a redo, a QUEUED or RUNNING render of the same video and format is cancelled and queued again (handler).

- [ ] Tests: `test_sentence_window_from_words`, `test_splice_shifts_later_words`, `test_first_and_last_sentence`, `test_cap_of_ten`, `test_fragment_goes_through_ledger` (mock tier records nothing paid; paid fake records).
- [ ] Implement, run, commit `feat(voice): A7 redo one sentence, spliced`.

### Task 5: Voice in the room (A8) and de-esser (A9), with the compare clip

**Files:** Modify `config.py` (`voice_room`, `voice_deess`, aliases `VOICE_ROOM`, `VOICE_DEESS`), `.env.example`, `pipeline/render_common.py` (`voice_filters(settings, wide=()) -> str`, applied after the voice `acompressor`; wide windows in track time), `pipeline/render_short.py` / `pipeline/render_long.py` (pass wide windows: shots that are not close-ups), create `scripts/voice_compare.py`, `/voice compare` in bot; test `tests/test_voice_filters.py`.

**Interfaces:** room = `asplit` dry/wet, wet `aecho=0:1:18|31:0.10|0.07`, wet volume 1.0 close / 1.4 wide by `between(t,a,b)` windows, `amix normalize=0`, then `equalizer=f=180:t=q:w=1:g=1.5`; de-ess = `deesser=i=0.4:m=0.5:f=0.5:s=o`. `voice_compare(ws_path, fmt, settings) -> list[Path]`: 20 s from the voice's middle, written as `compare_dry.wav`, `compare_room.wav`, `compare_deess.wav`, `compare_both.wav`.

- [ ] Tests: `test_off_by_default_no_filters`, `test_room_filter_with_windows`, `test_graph_runs_on_a_tone` (real ffmpeg, 2 s), `test_compare_writes_four_files`.
- [ ] Implement, run, commit `feat(sound): A8 room tone and A9 de-esser, off; /voice compare`.

### Task 6: Sounds from Dennis's body (A10)

**Files:** Modify `room3d/motion.py` (`body_events(channels, fps) -> list[dict(kind, frame)]`: `turn` when yaw moves > 25° within 0.3 s, `lean` when lean rises past its rest by half its range, `step` when the root moves > 0.25 m within 0.5 s, each kind at most once per 1.2 s), `room3d/perform.py` (write `events` into `perf.json`), `pipeline/dennis3d.py` (read `events` per shot into its meta), `pipeline/sound.py` (`MOVE_CUES` gains `body_turn`, `body_lean`, `body_step`; `body_cues(shots, settings, voicing)`), the two renders (add the cues), `scripts/fetch_sfx.py` (`QUERIES` for the three keys); test `tests/test_body_sounds.py`.

- [ ] Tests: `test_events_from_channels`, `test_events_spaced`, `test_cues_offset_by_shot_start`, `test_no_files_no_cue_no_block`.
- [ ] Implement, run with the sfx and dennis3d suites, commit `feat(sound): A10 body sounds from the 3D motion`.

### Task 7: Phone speaker check (A11)

**Files:** Create `pipeline/phone_check.py`; modify the two renders (after the mix, finals and proofs), `pipeline/provenance.py` (a `phone` line), test `tests/test_phone_check.py`.

**Interfaces:** `PHONE = "highpass=f=300,lowpass=f=7000"`; `bass_share(path) -> float` (share of level lost through the filter, cached by file hash); `masked_seconds(voice_stem, rest_stem, *, margin_db=6.0) -> list[int]` (per-second RMS through the filter, seconds where the voice speaks and leads the rest by less than the margin); `phone_report(tracks, spec, settings, out_dir) -> dict(masked=[…], bass_effects=[…])`, stems rendered audio-only through `audio_graph` on track subsets. Warns at 3+ masked seconds, and on any effect with `bass_share` ≥ 0.7.

- [ ] Tests: `test_bass_effect_flagged` (100 Hz tone), `test_voice_band_effect_passes` (2 kHz), `test_masked_seconds` (loud 1 kHz bed under a quiet voice tone), `test_report_line`.
- [ ] Implement, run, commit `feat(sound): A11 phone speaker check`.

### Task 8: Merge

- [ ] Run the touched suites and `tests/test_gates.py tests/test_botcore.py`; compare failures with the default branch.
- [ ] Merge into `claude/new-session-lxhson`, push both branches.
- [ ] Reply: what he can do now from Telegram, that A8/A9 wait for his ear on `/voice compare` after the first paid voice, and to rerun the sound fetch for A10.

# Writing items (S1–S12, voice bible v3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every picked writing item (S1, S2, S3, S4, S6, S7, S8, S9, S10, S11, S12) works end to end from the bot, and Dennis's voice moves to bible v3 (Benjamin-style humour, the story, swearing rules).

**Architecture:** New warn-only checks join `pipeline.gates.run_gates`; new prompt blocks join `bot.prompts.PAYLOAD` and the master templates; what the channel has already said (jokes, Dennis facts, recurring bits) is remembered in plain JSON under `state/`, written at ship time beside the thesis and confession ledgers, never in mock mode. Editable lists live in `assets/writing/` with the operator's edited copy in `state/writing/`, so the page (phase 3) can edit them without touching git.

**Tech Stack:** Python 3.11, pydantic v2, pytest, stdlib `difflib`, the local Gemma through `pipeline.llm.chat_result(providers=["ollama"])`.

**Spec:** Claude Doc "Build plan: your picks and the web page", https://claude.ai/code/artifact/2fef74dc-c79a-44db-bf87-4ed649a04478 (rev 9). Sections Writing, Dennis's story, Recurring bits, Voice changes.

## Global Constraints

- Every new check is `severity="warn"`. Only the existing sameness block may block (spec Goals).
- Model passes are local only: `chat_result(..., providers=[OLLAMA])`, each `purpose` registered in `pipeline.llm.PURPOSES` (test_recall fails otherwise). No paid model calls.
- Ship-time bookkeeping is skipped in `MOCK_MODE` and never fails a delivered job (wrap in try/except, log a warning).
- Never at the viewer; no calls, no price targets; no unproven claim about a living named person; Benjamin's lines are never put in a prompt, only in the copy check.
- Swearing: a long carries at most 4 strong swears and never two within 60 spoken seconds (144 words at `SPOKEN_WPS` 2.4); a short at most 1; none in a title, chapter title, description or pinned comment.
- Recurring bits: Kev's tip and the old trade each return every 6–8 longs (gap drawn per bit, seeded), never both in one video; the old trade only when a confession is due, and it is that video's confession.
- Only public videos count as published (privacy `public`, or `scheduled` with `publish_at` passed).
- Tests never read the operator's `.env`: the `settings` fixture, or `Settings(..., _env_file=None)`.
- The ElevenLabs voice and its settings are untouched.

## Review Focus

- A narration with no sentences, or a script with no chapters, must give no findings and no crash (every new check). Covered: each check's test file has an `_empty` test.
- An edited list file that is empty or holds a bad regex line: the bad line is skipped with a log warning, never an exception (Task 1 `test_bad_regex_line_is_skipped`).
- The ledgers are unreadable or hold junk JSON: prompts still fill, with a "(… unreadable …)" line (Tasks 5, 7 `test_junk_ledger`).
- The same video delivered twice (re-render of a final): its jokes, facts and bit are recorded once, keyed `TICKER/workdate/fmt` (Task 5 `test_remember_is_idempotent`).
- A proper noun at sentence start ("Kevin", "Kevlar") must not count as Kev's tip: word-boundary match on `\bKev\b` only (Task 7).

---

### Task 1: Editable writing files

**Files:**
- Create: `pipeline/writing_files.py`, `assets/writing/ai_phrases.txt`, `assets/writing/style_references.txt`, `assets/writing/dennis_story.md`, `assets/writing/README.md`
- Test: `tests/test_writing_files.py`

**Interfaces:**
- Produces: `WRITING_FILES: dict[str, str]` (name → default filename); `read_text(settings, name) -> str` (state copy if present, else the asset, else ""); `write_text(settings, name, text) -> Path` (always to `state/writing/<file>`); `reset(settings, name) -> bool`; `list_lines(settings, name) -> list[str]` (strips, drops blanks and `#` comments); `phrase_patterns(settings) -> list[tuple[str, re.Pattern]]` (a line `re: <regex>` compiles as given, any other line is matched as a whole phrase, case-insensitive, `\b` at word edges).
- Names: `ai_phrases`, `style_references`, `dennis_story`.

- [ ] Step 1: tests — `test_state_copy_wins_over_asset`, `test_write_goes_to_state_only` (asset bytes unchanged), `test_reset_removes_state_copy`, `test_list_lines_drops_comments_and_blanks`, `test_phrase_patterns_plain_and_regex` ("here's the thing" matches "Here's the thing:"; `re: \bdelve\w*` matches "delving"), `test_bad_regex_line_is_skipped`, `test_unknown_name_raises_keyerror`.
- [ ] Step 2: run, expect ImportError.
- [ ] Step 3: implement; write the three asset files (phrases ≈30: here's the thing, let that sink in, the result?, delve, in conclusion, it's worth noting, it is worth noting, at the end of the day, make no mistake, buckle up, let's dive in, dive into, in today's video, without further ado, it's important to note, a testament to, tapestry, the elephant in the room, plot twist, spoiler alert, here's the kicker, here's where it gets interesting, the truth is, let's be honest, let's break it down, fast forward to, the bottom line, simply put, unpack, moreover, furthermore, in essence, `re: \bnot just\b[^.?!]{1,60}\bbut\b`; style references = the Benjamin lines from his 21:11 message, one per line; the story = spec section "Dennis's story (draft 2)").
- [ ] Step 4: run, expect PASS.
- [ ] Step 5: commit `feat(writing): editable phrase list, style references and Dennis's story`.

### Task 2: Voice bible v3

**Files:**
- Modify: `assets/voice_bible.md`
- Test: `tests/test_voice_bible.py`

**Interfaces:** Produces the bible text the prompts inject verbatim (`bot.prompts.voice_bible`).

- [ ] Step 1: tests — heading reads `voice bible v3`; contains sections for the story pointer ("his story"), "Recurring bits", "Swearing" with the numbers 4 and 1; the recurring cast lists the five new archetypes (TikTok guru, signal Discord, chart-lines guy, comment-section mentor, macro doom guy); no line of `style_references.txt` appears in the bible (`difflib` ratio < 0.75 for every bible sentence).
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: rewrite to v3: keep §1–§4, §7–§9; §5 adds the family and friends as material, the no-credentials running bit and the family benchmark; §6 adds the five archetypes, recurring bits (footnote nobody read, said versus filed as tools; Kev's tip and the old trade only when the prompt says due; Kev's tip debunks, never recommends); new §3 moves with Dennis-original examples (mock formula ending in zero, fake rule with a loophole, family benchmark, absurd escalation ending somewhere dark); new swearing paragraph with the Global Constraints numbers.
- [ ] Step 4: run, expect PASS; run `pytest tests/test_prompt_payload.py tests/test_docs.py -q`.
- [ ] Step 5: commit `feat(voice): voice bible v3`.

### Task 3: S1 phrasing check and the swearing count

**Files:**
- Create: `pipeline/writing_checks.py`
- Modify: `pipeline/gates.py` (`run_gates`: record `phrasing`, `swearing`)
- Test: `tests/test_writing_checks.py`

**Interfaces:**
- Consumes: `writing_files.phrase_patterns`.
- Produces: `phrasing_lint(narration: str, settings) -> list[Finding]` (gate `phrasing`, one per hit, message names the phrase and says "cut it or say the thing plainly"; plus the built-in `question answered by the next word`: a ≤5-word question followed by a ≤3-word sentence, flagged from the second occurrence); `STRONG_SWEARS: tuple[str, ...]`; `swear_lint(narration: str, fmt: str) -> list[Finding]` (gate `swearing`); `package_swears(texts: dict[str, str]) -> list[Finding]` (gate `swearing`, any strong or moderate swear in a title, chapter title, description or pinned comment).

- [ ] Step 1: tests — `test_listed_phrase_warns_with_line`, `test_answered_question_flags_only_the_second`, `test_phrasing_empty`, `test_long_fifth_swear_warns`, `test_two_swears_within_a_minute_warn`, `test_short_second_swear_warns`, `test_swear_in_title_warns`, `test_clean_package_no_findings`, `test_run_gates_records_phrasing_and_swearing` (`report.ran` has both keys).
- [ ] Step 2: run, expect ImportError.
- [ ] Step 3: implement; in `run_gates` after `voice`: `phrasing_lint(delivery_text(script), settings)` and `swear_lint(narration, fmt)` where fmt is `long` when the script has `chapter_list`, else `short`; package swears go inside `check_title_package` (titles, description, pinned comment) plus the script's chapter titles.
- [ ] Step 4: run `pytest tests/test_writing_checks.py tests/test_gates.py -q`, expect PASS.
- [ ] Step 5: commit `feat(checks): S1 machine-phrasing check and swearing limits`.

### Task 4: S2 copy check

**Files:** Modify `pipeline/writing_checks.py`, `pipeline/gates.py`; Test `tests/test_writing_checks.py`

**Interfaces:**
- Produces: `reference_lines(settings) -> list[tuple[str, str]]` ((source, sentence): the bible's `>` example lines split into sentences, source `bible`, plus `style_references`, source `style reference`); `copy_check(narration: str, settings) -> list[Finding]` (gate `copy`).
- Rule: narration sentences of ≥6 words; a reference sentence of ≥6 words; prefilter on word-set overlap ≥0.4; warn when word-level `SequenceMatcher(...).ratio() >= 0.75`. Message: "repeats a {source} line almost word for word — write Dennis's own".

- [ ] Step 1: tests — `test_bible_line_reused_warns`, `test_style_reference_reworded_slightly_warns` (two words swapped), `test_same_topic_different_words_passes`, `test_copy_empty`.
- [ ] Step 2: run, expect FAIL. Step 3: implement, record `copy` in `run_gates`. Step 4: PASS. Step 5: commit `feat(checks): S2 copy check against the bible and style references`.

### Task 5: S3 used jokes and S8 Dennis facts, remembered at ship time

**Files:**
- Create: `pipeline/channel_memory.py`
- Modify: `bot/handlers.py` (`_deliver` path: call `remember_video` after `_record_thesis`, not in mock), `pipeline/llm.py` (`PURPOSES`: `jokes`, `dennis-facts`), `pipeline/gates.py` (gate `jokes`), `bot/prompts.py` (`{{used_jokes}}`, `{{dennis_story}}`, `{{dennis_facts}}`), `templates/master_prompt_{short,long_write,update,headline}.md`
- Test: `tests/test_channel_memory.py`

**Interfaces:**
- Produces: `JOKES_FILE = "used_jokes.json"`, `FACTS_FILE = "dennis_facts.json"`; `@dataclass Remembered(text: str, ticker: str, workdate: str, fmt: str, added_at: str)`; `class JokeBook(settings)` with `all() -> list[Remembered]`, `recent(n=40)`, `add(key: str, lines: list[str], ticker, workdate, fmt) -> int` (returns added; a key already present adds nothing), `replace_all(texts: list[str])` (page edits), `repeats(sentence: str, overlap=0.6) -> list[Remembered]` (content-word overlap against the joke's own words, as `ConfessionLedger.repeats`); `class FactBook(settings)` with the same `all/recent/add/replace_all`; `extract_jokes(script, settings) -> list[str]` (Gemma, system prompt asks for one line per joke, analogy or callback, verbatim from the script; fallback: lines `_CONSTRUCTIONS` match plus the sentence after each `[BEAT]` in `delivery_text`); `extract_facts(narration: str, settings, known: list[str]) -> list[str]` (Gemma, one new fact per line about Dennis, family, friends, history; fallback: first-person or cast-name (`Kev`, `Linda`, `Gary`, `Megan`, `Nan`, `Marco`, `Tyler`, `Mum`, `Dad`) sentences); `remember_video(settings, ticker, workdate, fmt, script) -> dict` (`{"jokes": n, "facts": m}`); `used_jokes_block(settings) -> str`; `dennis_facts_block(settings) -> str`; `joke_reuse_lint(narration, settings) -> list[Finding]` (gate `jokes`, "this joke was used in TICKER on DATE — write a new one").
- Prompt: `{{dennis_story}}` (writing_files `dennis_story`) and `{{dennis_facts}}`, `{{used_jokes}}` in `_WRITING`; each template gets a `DENNIS — WHO HE IS` and `ALREADY USED ON THIS CHANNEL` section beside the voice bible.

- [ ] Step 1: tests — `test_fallback_jokes_without_model` (mock settings: the `[BEAT]` follow-up line and a simile are extracted), `test_remember_is_idempotent`, `test_recent_is_newest_40`, `test_reworded_joke_is_flagged`, `test_junk_ledger` (a non-list JSON file → blocks say "(none yet)"), `test_blocks_fill_in_prompts` (fill `long_write` for the fixture workspace; story heading and "already used" present).
- [ ] Step 2: FAIL. Step 3: implement. Step 4: `pytest tests/test_channel_memory.py tests/test_prompt_payload.py tests/test_recall.py -q` PASS. Step 5: commit `feat(memory): S3 used jokes and S8 Dennis's story and facts`.

### Task 6: S10 recurring bits

**Files:**
- Create: `pipeline/recurring_bits.py`
- Modify: `bot/prompts.py` (`{{recurring_bits}}` for `long_write`, `update`; `confession_ledger` adds "the old trade is this video's confession" when due), `pipeline/channel_memory.remember_video` (longs: `note_bits`), `pipeline/gates.py` (gate `bits`), `templates/master_prompt_long_write.md`, `templates/master_prompt_update.md`
- Test: `tests/test_recurring_bits.py`

**Interfaces:**
- Produces: `BITS = ("kev_tip", "old_trade")`, `TOOLS = ("footnote", "said_vs_filed")`, `GAP = (6, 8)`; `class BitLedger(settings)` (`state/recurring_bits.json`, rows `{key, ticker, workdate, bit}` one per shipped long, `bit` "" when none) with `since(bit) -> int` (longs since it last ran; `len(rows)` when never), `gap_for(bit) -> int` (seeded on `bit + last-use key`, in 6..8), `note(key, ticker, workdate, bit) -> bool` (idempotent on key); `due_bit(settings) -> str` ("", "kev_tip" or "old_trade"; old trade only when `ConfessionLedger.due()`; both due → the one further past its gap, ties `kev_tip`); `bits_block(settings) -> str`; `detect_bit(narration: str, confessed: bool, due: str) -> str` (`\bKev\b` → kev_tip; else `old_trade` when due was old trade and the script confessed); `bits_lint(script, settings) -> list[Finding]` (Kev appears while not due: warn with the count since the last one).

- [ ] Step 1: tests — `test_nothing_due_on_empty_ledger_until_gap` (5 silent longs → "", the 8th → due), `test_gap_is_seeded_and_in_window`, `test_never_both`, `test_old_trade_waits_for_confession_due`, `test_kev_word_boundary` ("Kevin" no), `test_kev_too_soon_warns`, `test_block_names_the_due_bit`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS with `tests/test_prompt_payload.py`. Step 5: commit `feat(writing): S10 recurring bits every 6 to 8 longs`.

### Task 7: S11 hook types

**Files:**
- Create: `pipeline/hook_types.py`
- Modify: `bot/prompts.py` (`{{hook_type}}` for `short`, `long_write`, `update`, `headline`), `pipeline/retention_lines.py` (`hook_bench_text` adds a "By type" section), templates (one line in the opener instructions)
- Test: `tests/test_hook_types.py`

**Interfaces:**
- Produces: `HOOK_TYPES = ("number", "question", "withheld", "confession", "contradiction")`; `classify_hook(text: str) -> str` (one of `HOOK_TYPES` or `"other"`; precedence confession (`\bI\b` + past tense or `I've|I'd|my`), question (`?` in the first two sentences), withheld (`\bNot\b [^.]{1,40}\.` twice), contradiction (`but|yet|and still|despite|even though|which is strange`), number (`gates.spoken_figures` non-empty)); `recent_hook_types(settings, fmt, n=6) -> list[str]` (corpus entries of that format, newest last); `pick_hook_type(recent) -> str` (least recently used, ties in `HOOK_TYPES` order); `hook_type_block(settings, fmt) -> str`; `bench_by_type(bench: list[Hook]) -> list[tuple[str, float, int]]`.

- [ ] Step 1: tests — one `classify_hook` case per type plus `other`; `test_pick_least_recent`; `test_block_names_last_types_and_pick`; `test_bench_by_type_means`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS with `tests/test_retention_lines.py tests/test_prompt_payload.py`. Step 5: commit `feat(writing): S11 opener types rotate and /hooks reports them`.

### Task 8: S9 chapter order

**Files:** Modify `pipeline/writing_checks.py`, `pipeline/gates.py` (gate `chapters`), `bot/prompts.py` (`{{recent_chapter_orders}}` for `long_write`), `templates/master_prompt_long_write.md`; Test `tests/test_writing_checks.py`

**Interfaces:**
- Produces: `recent_chapter_orders(settings, n=3, exclude: Path | None = None) -> list[tuple[str, list[str]]]` ((`TICKER workdate`, types) from `script_long.json` of the last n shipped longs in `Corpus`); `chapter_order_lint(script, settings, workspace=None) -> list[Finding]` (warn when the type sequence equals one of them, or shares a run of ≥5 consecutive types in the same order); `chapter_orders_block(settings, workspace) -> str`.

- [ ] Step 1: tests — `test_same_order_warns`, `test_five_in_a_row_warns`, `test_different_order_passes`, `test_no_chapters_no_findings`.
- [ ] Step 2–5 as above; commit `feat(checks): S9 chapter order against the last three longs`.

### Task 9: S6 claims list

**Files:**
- Create: `pipeline/claims.py`
- Modify: `pipeline/models.py` (`CostReport.claims: list[str] = []`, rendered under "Claims to check yourself (not workbook numbers):"), `bot/handlers.py` (`_intake_short`, `_intake_long` fill it; `claims_text(chat_id)`), `bot/commands.py` (`Command("script", "claims", "", ...)`)
- Test: `tests/test_claims.py`

**Interfaces:**
- Produces: `@dataclass Claim(line: int, text: str, why: str)`; `list_claims(narration: str, ticker: str = "") -> list[Claim]` — a sentence is a claim when it names a year, a month or a day, or an event verb (acquired, announced, sued, settled, resigned, fired, founded, launched, recalled, restated, raised, cut, guided, filed, approved, banned, fined, merged, spun off) with a capitalised name that is not its first word; sentences in Dennis's voice about himself (first person singular, or a cast name from Task 5) are not claims; `claims_lines(claims) -> list[str]` ("L{n}: {text} ({why})").

- [ ] Step 1: tests — `test_dated_event_is_a_claim`, `test_workbook_figure_alone_is_not`, `test_dennis_story_line_is_not`, `test_report_renders_claims` (CostReport with two claims shows both lines), `test_claims_empty`.
- [ ] Step 2–5; commit `feat(report): S6 claims to check yourself`.

### Task 10: S4 cold read

**Files:**
- Create: `pipeline/cold_read.py`
- Modify: `bot/handlers.py` (`cold_read(chat_id, raw)`), `bot/commands.py` (`Command("script", "coldread", "[the answer]", ...)`)
- Test: `tests/test_cold_read.py`

**Interfaces:**
- Produces: `cold_read_prompt(narration: str, fmt: str) -> str` (numbered narration lines `L1: …`, asks a first-time viewer to answer under five headings — Lost me, Landed, Fell flat, I'd click away, Didn't believe — quoting the line with its `L` number, then three fixes); `@dataclass ColdRead(text: str, saved_at: str, quotes: list[tuple[str, int]])`; `link_quotes(answer: str, narration: str) -> list[tuple[str, int]]` (an `L\d+` reference wins; else a quoted span in “”/"" matched to the line with the highest `SequenceMatcher` ratio ≥0.6); `save_cold_read(ws_path: Path, fmt: str, answer: str, narration: str) -> ColdRead` (`cold_read_{fmt}.json`); `load_cold_read(ws_path, fmt) -> ColdRead | None`.
- Command: no args → the prompt as a `.md` file plus one line; with text → saved, reply lists how many quotes linked.

- [ ] Step 1: tests — `test_prompt_numbers_lines_and_has_headings`, `test_link_by_line_number`, `test_link_by_quote`, `test_save_and_load_roundtrip`, `test_command_without_active_video`.
- [ ] Step 2–5; commit `feat(writing): S4 cold read prompt and paste-back`.

### Task 11: S12 public videos and marking a hand upload

**Files:**
- Modify: `pipeline/youtube.py` (`is_public(v, now) -> bool`, `public_videos(settings, now=None) -> list[VideoRecord]`), `bot/handlers.py` (`mark_upload(args)`), `bot/commands.py` (`Command("publish", "mark", "TICKER [short|long] <link> [public|unlisted]", ...)`), `bot/prompts.py` (`{{public_videos}}` for `long_write`, `update`), the two templates' sign-off instructions
- Test: `tests/test_public_videos.py`

**Interfaces:**
- Produces: `parse_video_id(link: str) -> str` (youtu.be/, watch?v=, shorts/, or a bare 11-char id; "" otherwise); `mark_upload` records a `VideoRecord(privacy=…, workdate=` the ticker's latest workspace`, fmt=…)` and a journal line; marking again with `public` updates privacy in place; `public_videos_block(settings) -> str` ("(no public videos yet — the sign-off names none)" or up to 12 lines `TICKER — title (date)` plus "name one that follows on from this video, by its subject, never as a call").

- [ ] Step 1: tests — `test_parse_video_id_forms`, `test_unlisted_is_not_public`, `test_passed_schedule_is_public`, `test_mark_then_public_updates_in_place`, `test_block_empty_and_listed`.
- [ ] Step 2–5; commit `feat(publish): S12 public videos in the long prompt, /publish mark`.

### Task 12: S7 viewer questions behind a switch

**Files:**
- Create: `pipeline/viewer_questions.py`
- Modify: `config.py` (`viewer_questions: bool = Field(default=False, alias="VIEWER_QUESTIONS")`), `pipeline/youtube.py` (`YouTubeClient.top_comments(video_id, n=50) -> list[str]`), `pipeline/llm.py` (`PURPOSES["viewer-questions"]`), `bot/prompts.py` (`{{viewer_questions}}` for `long_write`, `update`), `bot/handlers.py` (`schedule_viewer_questions`, a weekly job beside `schedule_retention_notes`, no-op while the switch is off), templates
- Test: `tests/test_viewer_questions.py`

**Interfaces:**
- Produces: `QUESTIONS_FILE = "viewer_questions.json"`; `refresh_questions(settings, client) -> int` (top comments of public videos from the last 60 days, Gemma picks up to 8 real questions verbatim; without the model: comments ending in `?`, 12–200 chars; stored with video id); `questions_block(settings) -> str` — his call 10-18 21:29: the questions are a closing section of the long, passed to the writer ONLY when the switch is on. Off, or on with no questions stored: `""`, so the template carries no trace of it (the token sits on its own line where the sign-off instructions end). On with questions: a `VIEWER QUESTIONS — CLOSING SECTION` heading, the list, and "after the last chapter and before the sign-off, answer one or two of these in Dennis's words, as their own short section; quote the question, never name the commenter, never answer with a call".

- [ ] Step 1: tests — `test_off_by_default_block` (returns ""), `test_on_but_empty_is_blank`, `test_refresh_fallback_picks_questions` (fake client), `test_only_public_videos_read`, `test_block_lists_questions`.
- [ ] Step 2–5; commit `feat(writing): S7 viewer questions, off by default`.

### Task 13: Merge

- [ ] Run the touched suites: `pytest tests/test_writing_files.py tests/test_voice_bible.py tests/test_writing_checks.py tests/test_channel_memory.py tests/test_recurring_bits.py tests/test_hook_types.py tests/test_claims.py tests/test_cold_read.py tests/test_public_videos.py tests/test_viewer_questions.py tests/test_gates.py tests/test_prompt_payload.py tests/test_recall.py tests/test_botcore.py -q`.
- [ ] Fill every prompt format for the fixture workspace and read one long_write prompt end to end.
- [ ] Merge `claude/project-thread-wglbni` into `claude/new-session-lxhson`, push both.

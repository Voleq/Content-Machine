// Library and Settings. Library: the writing files he edits, what Dennis
// remembers, the recurring bits, and the owned memes, b-roll, sounds and
// rooms. Settings: the four switches, notifications, and the health rows.
// Loaded after pages.js and uses its helpers (card, table, pageRun, reload).

const pagePost = (label, path, body, btn) => act(label, () => post(path, body), btn);
const LIB_PARTS = [["writing", "Writing"], ["memory", "Memory"], ["memes", "Memes"], ["broll", "B-roll"], ["sounds", "Sounds"], ["rooms", "Rooms"]];
let LIB_PART = readStore("dennis.panel.library") || "writing";
let LIB_WRITING = "";
let LIB = null;

SCREEN_LOAD.library = async () => {
  const box = $("#library-screen");
  try { LIB = await api("/api/library"); } catch (e) { setKids(box, empty("Could not load the library", e.message, "bad", "!")); return; }
  renderLibrary();
};

function renderLibrary() {
  const box = $("#library-screen");
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Part of the library" }, LIB_PARTS.map(([id, name]) =>
    el("button", { type: "button", "aria-pressed": String(id === LIB_PART), text: name, onclick: () => { LIB_PART = id; writeStore("dennis.panel.library", id); renderLibrary(); } })));
  const part = { writing: libWriting, memory: libMemory, memes: libMemes, broll: libBroll, sounds: libSounds, rooms: libRooms }[LIB_PART] || libWriting;
  setKids(box, el("div", { class: "page-head" }, el("h2", { text: "Library" }), seg), part(LIB));
}

// ---------------------------------------------------------------- Writing
function libWriting(d) {
  const files = Array.isArray(d.writing) ? d.writing : [];
  if (!files.length) return sectionError(d.writing) || empty("No writing files", "", "", "·");
  const f = files.find((x) => x.name === LIB_WRITING) || files[0];
  LIB_WRITING = f.name;
  const area = el("textarea", { class: "mono writing", spellcheck: "true", "aria-label": f.title });
  area.value = f.text;
  const count = el("span", { class: "meta" });
  const dirty = () => { const changed = area.value !== f.text; save.disabled = !changed; count.textContent = `${area.value.split("\n").length} lines${changed ? " · not saved" : ""}`; };
  const save = el("button", { type: "button", class: "primary", text: "Save", title: "Keep your edit; the shipped file stays beside it",
    onclick: (e) => pagePost(`Save ${f.title}`, "/api/writing", { name: f.name, text: area.value }, e.currentTarget).then(SCREEN_LOAD.library) });
  const reset = el("button", { type: "button", class: "ghost", text: "Reset", disabled: !f.edited, title: "Throw your edit away and use the shipped file again",
    onclick: async (e) => {
      const b = e.currentTarget;
      if (await askConfirm(`Reset ${f.title}?`, "Your edit is deleted and the shipped file is used again.", "Reset it")) pagePost(`Reset ${f.title}`, "/api/writing", { name: f.name, reset: true }, b).then(SCREEN_LOAD.library);
    } });
  area.addEventListener("input", dirty);
  area.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); if (!save.disabled) save.click(); } });
  dirty();
  const help = {
    voice_bible: "The tone every writing prompt carries. Lines starting with > are examples the copy check keeps Dennis from repeating.",
    dennis_story: "Who Dennis is: family, Kev, the flat, his old trades. The writer reads it for every script.",
    ai_phrases: "Phrases that sound machine-written. The check flags them; one per line, re: for a pattern.",
    style_references: "Lines from the writers he is modelled on. The copy check flags a line copied from them.",
    pronunciations: "How a word is said to ElevenLabs, as WORD => said. Captions keep the real spelling.",
  }[f.name] || "";
  return el("div", { class: "lib-writing" },
    el("nav", { class: "lib-files", "aria-label": "Writing files" }, files.map((x) => el("button", { type: "button", class: x.name === f.name ? "on" : "", "aria-current": x.name === f.name ? "true" : null,
      onclick: () => { if (area.value !== f.text && !confirm("Leave without saving?")) return; LIB_WRITING = x.name; renderLibrary(); } },
      x.title, x.edited ? el("span", { class: "badge soft", text: "edited" }) : null))),
    el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", { text: f.title }), el("span", { class: "meta", text: f.edited ? "your edit" : "the shipped file" })),
      el("p", { class: "meta", text: help }), area,
      el("div", { class: "row between" }, count, el("div", { class: "row" }, reset, save))));
}

// ----------------------------------------------------------------- Memory
function memoryList(book, rows, what) {
  const texts = rows.map((r) => r.text);
  const saveAll = (list, btn, label) => pagePost(label, "/api/memory", { book, texts: list, was: texts }, btn).then(SCREEN_LOAD.library);
  const add = book === "facts" ? el("form", { class: "row inline-form" },
    el("input", { name: "t", class: "grow", placeholder: "A new fact about Dennis, e.g. Dennis's sister lives in Leeds.", required: true }),
    el("button", { type: "submit", class: "sm", text: "Add" })) : null;
  add?.addEventListener("submit", (e) => { e.preventDefault(); saveAll([...texts, e.target.t.value.trim()], e.submitter, "Add a fact"); });
  return [add, rows.length ? el("ul", { class: "mem-list" }, rows.map((r, i) => el("li", {},
    el("span", { class: "grow", text: r.text }),
    r.ticker ? el("span", { class: "meta", text: `${r.ticker} ${r.workdate}` }) : el("span", { class: "meta", text: "yours" }),
    el("button", { type: "button", class: "ghost sm", text: "✕", "aria-label": `Remove: ${r.text}`, title: `Remove it; the writer stops seeing it`,
      onclick: (e) => saveAll(texts.filter((_, j) => j !== i), e.currentTarget, `Remove a ${what}`) }))))
    : el("p", { class: "meta", text: `No ${what}s yet. Each shipped video adds its own.` })];
}
function libMemory(d) {
  const facts = Array.isArray(d.facts) ? d.facts : [];
  const jokes = Array.isArray(d.jokes) ? d.jokes : [];
  const bits = d.bits && !d.bits.error ? d.bits : null;
  return el("div", { class: "grid" },
    card("What Dennis has said about himself", `${facts.length} facts · the writer keeps to them`, sectionError(d.facts), memoryList("facts", facts, "fact")),
    card("Jokes already used", `${jokes.length} · the checks flag a re-tell`, sectionError(d.jokes), memoryList("jokes", jokes, "joke")),
    el("div", { class: "span2" }, card("Recurring bits", bits?.due ? `due in the next LONG: ${bits.due}` : "neither is due in the next LONG", sectionError(d.bits),
      bits ? table(["Bit", "LONGs since", "Comes back after", "Status"], bits.bits.map((b) => el("tr", {},
        el("td", {}, el("b", { text: b.name })), el("td", { class: "num", text: String(b.since) }), el("td", { class: "num", text: `${b.gap} LONGs` }),
        el("td", { text: b.overdue >= 0 ? "due" : `waits ${-b.overdue} more` })))) : null,
      bits?.recent.length ? el("p", { class: "meta", text: `Last LONGs: ${bits.recent.map((r) => `${r.ticker}${r.bit ? ` (${r.bit})` : ""}`).join(" · ")}` }) : null)));
}

// ------------------------------------------------------------------ Memes
function libMemes(d) {
  const m = d.memes && !d.memes.error ? d.memes : { rows: [], unlabelled: [] };
  const recent = m.rows.filter((r) => r.recent).length;
  return el("div", {}, sectionError(d.memes),
    el("p", { class: "meta", text: `${m.rows.length} labelled memes. ${recent} were on screen in the last six videos and are off the writer's list until they rotate back.` }),
    m.unlabelled.length ? el("div", { class: "banner warn", text: `Not labelled, so never picked: ${m.unlabelled.join(", ")}. A thread adds them to meme_index.json.` }) : null,
    el("div", { class: "pic-grid" }, m.rows.map((r) => el("figure", { class: `pic${r.recent ? " used" : ""}`, title: r.use_when },
      el("a", { href: withKey(r.file), target: "_blank", rel: "noopener" }, el("img", { src: withKey(r.thumb), alt: r.stem, loading: "lazy" })),
      el("figcaption", {}, el("b", { text: r.stem }), r.recent ? el("span", { class: "badge soft", text: "used recently" }) : null,
        el("span", { class: "meta", text: r.use_when }),
        el("span", { class: "tags", text: r.tags.map((t) => `#${t}`).join(" ") }))))));
}

// ----------------------------------------------------------------- B-roll
function libBroll(d) {
  const b = d.broll && !d.broll.error ? d.broll : { clips: [], keys: 0, without: [] };
  return el("div", {}, sectionError(d.broll),
    card("Owned clips", `${b.clips.length} clip${b.clips.length === 1 ? "" : "s"} · they win over Pexels`,
      b.clips.length ? table(["Clip", "Palette key", ""], b.clips.map((c) => el("tr", {}, el("td", { text: c.name }), el("td", { class: "mono", text: c.key }),
        el("td", { class: "acts" }, el("button", { type: "button", class: "sm", text: "▶ Play", onclick: () => play({ name: c.name, url: withKey(c.file) }) })))))
        : el("p", { class: "meta", text: "None yet. Drop a clip named after a palette key into assets/broll_library." }),
      b.without.length ? el("details", { class: "report" }, el("summary", { text: `${b.without.length} of ${b.keys} palette keys still reach for Pexels` }),
        el("p", { class: "mono meta", text: b.without.join("  ") })) : null));
}

// ----------------------------------------------------------------- Sounds
function libSounds(d) {
  const rows = Array.isArray(d.sounds) ? d.sounds : [];
  const held = rows.filter((r) => r.placeholder).length;
  return el("div", {}, sectionError(d.sounds),
    held ? el("div", { class: "banner warn", text: `${held} placeholder sound${held === 1 ? "" : "s"} block every final render. Run python scripts/fetch_sfx.py on the box.` }) : null,
    card("Sounds and music", `${rows.length} files`, rows.length ? table(["Sound", "", "Source", "Licence"], rows.map((r) => el("tr", {},
      el("td", {}, el("b", { text: r.name }), el("span", { class: "meta", text: ` ${r.dir}` }), r.placeholder ? el("span", { class: "badge", text: "placeholder" }) : null),
      el("td", {}, el("audio", { controls: true, preload: "none", src: withKey(r.file) })),
      el("td", { class: "meta" }, r.source ? el("a", { href: r.source.startsWith("http") ? r.source : `https://${r.source}`, target: "_blank", rel: "noopener", text: r.author || r.source }) : "–"),
      el("td", { class: "meta", text: r.licence || "–" })))) : el("p", { class: "meta", text: "No sound files." })));
}

// ------------------------------------------------------------------ Rooms
function libRooms(d) {
  const rows = Array.isArray(d.rooms) ? d.rooms : [];
  const doctor = el("button", { type: "button", class: "sm", text: "Run the kit doctor", title: "Plate names nothing resolves, artwork never used, slots left empty. Takes about twelve seconds",
    onclick: (e) => pageRun("/admin kit doctor", e.currentTarget, "Kit doctor") });
  const group = (aspect, label) => {
    const list = rows.filter((r) => r.aspect === aspect);
    return list.length ? el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", { text: label }), el("span", { class: "meta", text: `${list.length} angles` })),
      el("div", { class: `pic-grid rooms r${aspect}` }, list.map((r) => el("figure", { class: "pic", title: r.purpose },
        el("a", { href: withKey(r.file), target: "_blank", rel: "noopener" }, el("img", { src: withKey(r.thumb), alt: r.key, loading: "lazy" })),
        el("figcaption", {}, el("b", { text: r.key }), el("span", { class: "meta", text: [r.hour, r.season].filter(Boolean).join(" · ") })))))) : null;
  };
  return el("div", {}, sectionError(d.rooms),
    el("div", { class: "row between" }, el("p", { class: "meta", text: "The 3D room as the kit holds it. Hover an angle for what it is for; the board, monitor and props are written per video." }), doctor),
    rows.length ? [group("16x9", "LONG rooms (16:9)"), group("9x16", "SHORT rooms (9:16)")]
      : empty("No rooms in the kit", "Run python scripts/ingest_kit.py kit on the box.", "", "·"));
}

// --------------------------------------------------------------- Settings
SCREEN_LOAD.settings = async () => {
  const box = $("#settings-screen");
  setKids(box, el("div", { class: "page-head" }, el("h2", { text: "Settings" })), el("p", { class: "meta", text: "Checking the box…" }));
  let d;
  try { d = await api("/api/settings"); } catch (e) { setKids(box, empty("Could not load the settings", e.message, "bad", "!")); return; }
  const flip = (name, on, label) => (e) => pagePost(label, "/api/switch", { name, on }, e.currentTarget).then(SCREEN_LOAD.settings);
  const switches = Array.isArray(d.switches) ? d.switches : [];
  const toggle = (on, label, onclick, title) => el("button", { type: "button", role: "switch", "aria-checked": String(on), class: `toggle${on ? " on" : ""}`, "aria-label": label, title, onclick }, el("i"));
  const swCard = card("Switches", "take effect at once and survive a restart", sectionError(d.switches),
    el("ul", { class: "switches" }, switches.map((s) => el("li", {},
      toggle(s.on, s.title, flip(s.name, !s.on, `${s.title} ${s.on ? "off" : "on"}`), `${s.on ? "Turn off" : "Turn on"} (${s.env})`),
      el("div", {}, el("b", { text: s.title }), el("span", { class: "meta mono", text: ` ${s.env}${s.from_page ? " · set here" : ""}` }), el("p", { class: "meta", text: s.says }))))),
    el("ul", { class: "switches" }, el("li", {},
      toggle(d.quiet === true, "Quiet notifications", (e) => pageRun(`/admin quiet ${d.quiet === true ? "off" : "on"}`, e.currentTarget, "Notifications").then(SCREEN_LOAD.settings), "Only finished, failed and needs-you pushes"),
      el("div", {}, el("b", { text: "Quiet notifications" }), el("p", { class: "meta", text: "Telegram and the page get only finished, failed and needs-you pushes, no progress." })))));
  const health = Array.isArray(d.health) ? d.health : [];
  const bad = health.filter((r) => r.state === "bad").length;
  const healthCard = card("Health", bad ? `${bad} to fix before a real video` : "nothing blocks a real video", sectionError(d.health),
    el("ul", { class: "health" }, health.map((r) => el("li", { class: r.state },
      el("span", { class: "dot", "aria-label": { ok: "fine", bad: "needs fixing", skip: "not checked" }[r.state] || r.state }),
      el("b", { text: r.name }), el("span", { class: "meta", text: r.detail })))),
    el("div", { class: "row" },
      el("button", { type: "button", class: "sm", text: "Check again", onclick: () => SCREEN_LOAD.settings() }),
      el("button", { type: "button", class: "sm", text: "Test the keys", title: "Asks each service once, with a call that costs nothing, whether its key works. Takes a few seconds",
        onclick: (e) => pageRun("/admin keys", e.currentTarget, "Key check") })));
  const disk = Array.isArray(d.disk) ? d.disk : [];
  const diskCard = card("Disk", "", disk.map((x) => el("p", {}, el("b", { text: `${x.free_gb} GB free` }), el("span", { class: "meta", text: ` of ${x.total_gb} GB · ${x.name} (${x.path})` }))),
    disk.some((x) => x.free_gb < 20) ? el("div", { class: "banner warn", text: "Under 20 GB free: a LONG render can run out. python -m pipeline.cleanup --dry-run on the box shows what it would clear." }) : null);
  const fails = Array.isArray(d.failures) ? d.failures : [];
  const failCard = card("Renders that failed", fails.length ? `the last ${fails.length}` : "none", sectionError(d.failures),
    fails.length ? el("ul", { class: "mem-list" }, fails.map((f) => el("li", {},
      el("div", { class: "grow" }, el("b", { text: `${f.ticker} · ${f.kind.replace("render_", "")}` }), el("span", { class: "meta", text: ` ${ago(f.at)}` }), el("p", { class: "meta mono", text: f.error })),
      el("button", { type: "button", class: "sm", text: "Open", onclick: () => openVideo(f.ticker, f.workdate) })))) : el("p", { class: "meta", text: "Nothing has failed." }));
  setKids(box, el("div", { class: "page-head" }, el("h2", { text: "Settings" })),
    d.dennis_3d_warning ? el("div", { class: "banner warn", text: d.dennis_3d_warning }) : null,
    el("p", { class: "meta", text: "Keys and passwords live in .env on the box and are never shown here." }),
    el("div", { class: "grid" }, swCard, healthCard, diskCard, failCard));
};

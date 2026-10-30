// The video workspace: one video's ten steps, in order, on one screen.
// `#/video/TICKER/YYYY-MM-DD[/step]`. It reads `/api/video` (bot/panel_views)
// and acts only through the bot's own entry points: a button's callback data,
// a command, a paste, an upload. Loaded after app.js and uses its helpers.

const VID = { t: "", d: "", step: "", data: null, raw: {}, timer: 0, logTimer: 0 };
const STEP_HELP = {
  data: "The workbook you filled in Capital IQ. Drop it here; the bot checks it before anything else.",
  angle: "LONG only: the bot's prompt asks your Claude chat for three angles. Paste the answer, then pick one.",
  write: "Paste the bot's prompt into your Claude chat, then paste the script it writes back here.",
  check: "Your script one sentence a row, with what the checks found beside it. Red stops Approve, yellow is worth a look. Click a sentence to change it; every check runs again when you save.",
  proof: "A free full-size look with the free voice. Press n while it plays to note a fault at that moment.",
  approve: "Approving fixes this exact script for the paid render. Nothing is spent yet.",
  voice: "The paid voice, as it landed. Redo one sentence, or teach it how a word is said.",
  render: "The final render. This is the step that spends money.",
  upload: "Everything YouTube asks for, one copy button each, and the upload itself.",
  live: "How viewers watched it once it is out.",
};
const withKey = (url) => (url ? `${url}${url.includes("?") ? "&" : "?"}k=${encodeURIComponent(KEY)}` : "");
const fmtTime = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const dur = (s) => (s == null ? "" : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);

// ------------------------------------------------------------------ routing
function openVideo(t, d, step = "") {
  location.hash = `#/video/${encodeURIComponent(t)}/${encodeURIComponent(d)}${step ? "/" + step : ""}`;
}
function routeVideo() {
  const m = location.hash.match(/^#\/video\/([^/]+)\/([^/]+)(?:\/([a-z]+))?/);
  if (!m) { stopVideo(); return false; }
  const [t, d, step] = [decodeURIComponent(m[1]), decodeURIComponent(m[2]), m[3] || ""];
  const same = t === VID.t && d === VID.d;
  VID.t = t; VID.d = d; VID.step = step;
  showTab("video", false, true);
  if (!same) { VID.data = null; VID.raw = {}; setKids($("#video-screen"), el("p", { class: "meta", text: "Opening…" })); }
  loadVideo(true);
  clearInterval(VID.timer);
  VID.timer = setInterval(() => loadVideo(false), 4000);
  return true;
}
function stopVideo() {
  clearInterval(VID.timer); clearInterval(VID.logTimer);
  VID.timer = 0; VID.logTimer = 0;
}
window.addEventListener("hashchange", () => { if (!$("#app").hidden) routeVideo(); });

// Every paste, upload, command and button here names this video, in the
// same request: the page made it active first and sent the action after,
// and a tap in Telegram or another tab in between sent it to another video.
const here = () => ({ ticker: VID.t, workdate: VID.d });
const vRun = (text, btn, label = text) => act(label, () => post("/api/run", { text, video: here() }), btn);
const vText = (text, btn, label) => act(label, () => post("/api/text", { text, video: here() }), btn);

function sendFile(file, url, origin) {
  return new Promise((resolve) => {
    const box = addReply(origin);
    const big = tooBig(file);
    if (big) { failReply(box, new Error(big), origin); resolve(); return; }
    BUSY++;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url + (/[?&]t=/.test(url) ? "" : `&t=${encodeURIComponent(VID.t)}&d=${encodeURIComponent(VID.d)}`));
    xhr.setRequestHeader("X-Panel-Key", KEY);
    xhr.onloadend = () => {
      BUSY--;
      let data = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch { /* empty */ }
      if (xhr.status === 200 && data.reply) fillReply(box, data.reply, origin);
      else failReply(box, new Error(data.error || `upload failed (${xhr.status})`), origin);
      refresh(true); loadVideo(true);
      resolve();
    };
    xhr.send(file);
  });
}

async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand("copy"); } catch { /* nothing more to try */ }
    ta.remove();
  }
  if (btn) { const was = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(() => { btn.textContent = was; }, 1400); }
  say("Copied");
}
const copyBtn = (label, getText, title = "") => el("button", {
  type: "button", class: "sm", text: label, title: title || `Copy ${label.replace(/^Copy\s*/i, "")}`,
  onclick: async (e) => { const b = e.currentTarget; copyText(typeof getText === "function" ? await getText() : getText, b); },
});
async function fileText(url) {
  const res = await fetch(url, { headers: { "X-Panel-Key": KEY } });
  if (!res.ok) throw new Error(`could not read the file (${res.status})`);
  return res.text();
}

// The page's own "are you sure", for money and for deleting.
function askConfirm(title, text, ok = "Yes") {
  const dlg = $("#confirm");
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  $("#confirm-ok").textContent = ok;
  dlg.returnValue = "";
  dlg.showModal();
  $("#confirm-no").focus();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true }));
}
// A button from a bot keyboard; money ones ask first, then send the callback.
function cbButtons(rows, opts = {}) {
  return buttonsBlock(rows, Object.assign({ video: here() }, opts, {
    local: (b, btn) => {
      if (opts.local && opts.local(b, btn)) return true;
      if (!isMoney(b.text)) return false;
      askConfirm("This spends money", `${b.text.replace(/💰/g, "").trim()} — the paid voice and render. Go ahead?`, "Spend it").then((yes) => {
        if (yes) { INFLIGHT.add(b.data); callback(b.data, b.text, btn, here()).finally(() => { INFLIGHT.delete(b.data); loadVideo(true); }); }
      });
      return true;
    },
  }));
}
function mainButton(text, onclick, cls = "primary", title = "") {
  return el("button", { type: "button", class: cls, text, title: title || null, onclick });
}

// -------------------------------------------------------------------- load
async function loadVideo(force) {
  if (!VID.t || document.hidden && !force) return;
  if ($("#tab-video").hidden) return;
  let data;
  try {
    data = await api(`/api/video?t=${encodeURIComponent(VID.t)}&d=${encodeURIComponent(VID.d)}`);
  } catch (e) {
    setKids($("#video-screen"), empty("Could not open this video", e.message || String(e), "bad", "!"));
    return;
  }
  const prev = VID.data;
  VID.data = data;
  if (data.error || !data.exists) {
    setKids($("#video-screen"), empty("No such video", `${VID.t} ${VID.d} has no folder on the render box.`, "bad", "!",
      el("button", { type: "button", class: "ghost sm", text: "Back to Videos", onclick: () => showTab("videos") })));
    return;
  }
  const step = VID.step || data.now;
  if (!prev || prev.ticker !== data.ticker || !$("#video-screen .ws")) return renderVideoScreen(step);
  renderRail(step);
  renderHead();
  const raw = JSON.stringify(data[step]);
  if (raw !== VID.raw[step] && (force || !panelBusy())) renderPanel(step);
}

// He is typing, has a line open, or is watching: a redraw would lose it.
function panelBusy() {
  const node = $("#ws-panel");
  if (!node) return false;
  const f = document.activeElement;
  if (f && f !== document.body && node.contains(f) && f.matches("input, textarea, select, video, audio")) return true;
  if (node.querySelector("[data-dirty]")) return true;
  return $$("video, audio", node).some((m) => !m.paused);
}

function renderVideoScreen(step) {
  setKids($("#video-screen"), el("div", { class: "ws" },
    el("div", { class: "ws-head", id: "ws-head" }),
    el("nav", { class: "ws-rail", id: "ws-rail", "aria-label": "Steps" }),
    el("section", { class: "ws-panel card", id: "ws-panel", "aria-live": "polite" })));
  renderHead(); renderRail(step); renderPanel(step);
}

function renderHead() {
  const v = VID.data, st = v.state;
  const a = STATE?.active;
  const isActive = a && a.ticker === v.ticker && a.workdate === v.workdate;
  setKids($("#ws-head"),
    el("button", { type: "button", class: "ghost sm", text: "← Videos", title: "Back to every video", onclick: () => showTab("videos") }),
    el("h2", {}, el("span", { class: "tk", text: v.ticker }), " ",
      el("span", { class: "lane", text: st.update ? "update" : (st.lane || "no lane") }), " ",
      el("span", { class: "meta", text: v.workdate })),
    el("p", { class: "next-line" }, "Next: ", el("b", { text: st.next_step })),
    isActive ? el("span", { class: "active-badge", title: "Pastes and uploads from Home land here", text: "Active" })
      : el("button", { type: "button", class: "ghost sm", text: "Make active", title: "Pastes and uploads from Home and Telegram land in the active video",
        onclick: (e) => act(`Work on ${v.ticker} ${v.workdate}`, () => post("/api/active", { ticker: v.ticker, workdate: v.workdate }), e.currentTarget) }));
}

function renderRail(current) {
  const v = VID.data;
  const rail = $("#ws-rail");
  const focused = document.activeElement?.closest?.("#ws-rail")?.dataset?.step;
  setKids(rail, v.steps.map((s, i) => el("a", {
    href: `#/video/${encodeURIComponent(v.ticker)}/${encodeURIComponent(v.workdate)}/${s.id}`,
    class: `step ${s.status}${s.id === current ? " on" : ""}`, "data-step": s.id,
    "aria-current": s.id === current ? "step" : null, title: STEP_HELP[s.id],
  },
    el("span", { class: "n", "aria-hidden": "true", text: s.status === "done" ? "✓" : s.status === "skip" ? "–" : String(i + 1) }),
    el("span", { class: "t" }, el("b", { text: s.title }),
      el("small", { text: s.status === "now" ? (s.summary || "you are here") : s.status === "skip" ? "not for this lane" : s.summary || (s.status === "optional" ? "optional" : "") })),
  )));
  if (focused) rail.querySelector(`[data-step="${focused}"]`)?.focus({ preventScroll: true });
}

function renderPanel(step) {
  const v = VID.data;
  const data = v[step] || {};
  VID.raw[step] = JSON.stringify(data);
  clearInterval(VID.logTimer); VID.logTimer = 0;
  const meta = v.steps.find((s) => s.id === step) || { title: step, status: "" };
  let built = { main: null, body: [] };
  if (data.error) {
    built.body = [el("div", { class: "banner bad", text: `This step could not be read: ${data.error}` })];
  } else {
    try { built = (STEPS_UI[step] || (() => built))(data, v) || built; } catch (e) {
      built.body = [el("div", { class: "banner bad", text: `The page could not draw this step: ${e.message}` })];
    }
  }
  setKids($("#ws-panel"),
    el("div", { class: "ws-panel-head" },
      el("div", {}, el("h3", { text: meta.title }), el("p", { class: "meta", text: STEP_HELP[step] || "" })),
      el("div", { class: "ws-main" }, built.main)),
    built.body);
}

// ------------------------------------------------------------- the steps
const STEPS_UI = {};

function dropZone(label, accept, onFile, help) {
  const input = el("input", { type: "file", class: "sr-only", accept });
  const zone = el("label", { class: "drop", title: help || label },
    input, el("span", {}, el("b", { text: label }), " or ", el("u", { text: "browse" }), help ? el("small", { text: help }) : null));
  input.addEventListener("change", () => { const f = input.files[0]; if (f) onFile(f); input.value = ""; });
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) onFile(f); });
  zone.pick = () => input.click();
  return zone;
}
const uploadFile = (f) => sendFile(f, `/api/upload?name=${encodeURIComponent(f.name)}`, `Upload · ${f.name} → ${VID.t}`);

function findingList(items) {
  if (!items.length) return null;
  return el("ul", { class: "findings" }, items.map((f) => el("li", { class: f.severity === "block" || f.blocking ? "bad" : f.severity === "warn" ? "warn" : "" },
    el("b", { text: f.kind || f.gate || (f.severity === "block" ? "blocking" : "note") }), " ", f.message)));
}

STEPS_UI.data = (d) => {
  const zone = dropZone("Drop the workbook", ".xlsx,.csv", uploadFile, "dennis_data.xlsx from your Capital IQ terminal");
  const body = [];
  if (d.file) {
    body.push(el("p", {}, el("b", { text: d.file }), d.as_of ? el("span", { class: "meta", text: ` · numbers as of ${d.as_of}` }) : null));
  }
  body.push(findingList(d.problems || []), findingList(d.freshness || []));
  (d.missing || []).forEach((m) => body.push(el("p", { class: "warn-line", text: m })));
  if ((d.figures || []).length) {
    body.push(el("dl", { class: "figures" }, d.figures.map((f) => el("div", {}, el("dt", { text: f.label }), el("dd", { text: f.value })))));
  }
  body.push(zone);
  return { main: mainButton(d.file ? "Upload a newer workbook" : "Upload the workbook", () => zone.pick()), body };
};

function promptCard(p, what) {
  if (!p || !p.url) return el("p", { class: "meta", text: `The ${what} prompt is written when the step before it is done.` });
  return el("div", { class: "prompt-card" },
    el("div", {}, el("b", { text: p.name }), el("span", { class: "meta", text: ` · ${(p.chars || 0).toLocaleString()} characters` })),
    el("div", { class: "row" },
      copyBtn("Copy the prompt", () => fileText(withKey(p.url)), "Copy it, then paste it into your Claude chat"),
      el("a", { href: withKey(p.url), download: p.name, class: "button sm", text: "Download" })));
}
// AN UNSENT PASTE IS KEPT in this browser, one per box per video, until the
// bot says it took it: a tab closed or reloaded before the send lost a whole
// script the chat had written.
const draftKey = (label) => `cm.draft.${VID.t}@${VID.d}.${label}`;
function dropStore(k) { try { localStorage.removeItem(k); } catch { /* private window */ } }

function pasteBox(placeholder, label, send) {
  const key = draftKey(label);
  const ta = el("textarea", { rows: 8, spellcheck: "false", placeholder });
  ta.value = readStore(key);
  if (ta.value.trim()) ta.dataset.dirty = "1";
  ta.addEventListener("input", () => {
    if (ta.value.trim()) { ta.dataset.dirty = "1"; writeStore(key, ta.value); } else { delete ta.dataset.dirty; dropStore(key); }
  });
  const btn = el("button", { type: "button", class: "primary", text: label, onclick: (e) => {
    const text = ta.value;
    if (!text.trim()) { ta.focus(); return; }
    send(text, e.currentTarget).then((ok) => { if (ok) { ta.value = ""; delete ta.dataset.dirty; dropStore(key); } });
  } });
  return el("div", { class: "paste" }, ta, el("div", { class: "row end" }, btn));
}

STEPS_UI.angle = (d) => ({
  main: d.prompt?.url ? copyBtn("Copy the angle prompt", () => fileText(withKey(d.prompt.url))) : null,
  body: [
    promptCard(d.prompt, "angle"),
    d.chosen ? el("p", {}, "Chosen: ", el("b", { text: d.chosen })) : null,
    d.awaiting ? el("p", { class: "meta", text: "Paste the three angles your chat gave, then pick one." }) : null,
    pasteBox("Paste the angles (or a tweak to one)", "Send the angles", (t, b) => vText(t, b, `Angles → ${VID.t}`)),
    d.awaiting ? cbButtons(d.pick, { nextRow: true }) : null,
  ],
});

STEPS_UI.write = (d) => ({
  main: d.prompt?.url ? copyBtn("Copy the prompt", () => fileText(withKey(d.prompt.url))) : null,
  body: [
    promptCard(d.prompt, "writer's"),
    d.script ? el("p", { class: "ok-line", text: `A script is in: ${(d.chars || 0).toLocaleString()} characters, ${d.revisions} edits. Pasting a new one replaces it.` }) : null,
    pasteBox("Paste the script your chat wrote", "Send the script", (t, b) => vText(t, b, `Script · ${t.length.toLocaleString()} chars → ${VID.t}`)),
    dropZone("Or drop the script file", ".txt,.md,.json", uploadFile, ".txt or .json"),
  ],
});

// Check: the script, with each finding beside its line.
const TAG_RE = /(\[[A-Z][A-Z0-9_ ]*(?::[^\]]*)?\])/g;
function lineText(text) {
  // A plate's tag carries its whole data; the line shows its name, the
  // rest on hover and in the editor.
  return text.split(TAG_RE).filter(Boolean).map((part) => {
    if (!/^\[[A-Z][A-Z0-9_ ]*(?::[^\]]*)?\]$/.test(part)) return part;
    const short = part.includes("|") ? `${part.split("|")[0].trim()} …]` : part;
    return el("span", { class: "tag", text: short, title: part });
  });
}
// A LONG's line is replaced by its number (`/script edit N`); a SHORT's
// sentence by its own words (`/script replace old => new`), as it is stored.
const jsonInner = (t) => JSON.stringify(t).slice(1, -1);
function editLine(row, n, text, raw = "", fs = []) {
  const ta = el("textarea", { rows: Math.max(2, Math.ceil(text.length / 90)), spellcheck: "true", "data-dirty": "1" });
  ta.value = text;
  const what = raw ? "sentence" : "line";
  const cmd = (next) => (raw ? `/script replace ${raw} => ${jsonInner(next)}` : `/script edit ${n}${next ? " " + next : ""}`);
  const status = el("span", { class: "meta", text: "" });
  const save = el("button", { type: "button", class: "primary sm", text: `Save ${what}`, title: `Stores the new ${what} and runs every check again`,
    onclick: (e) => {
      status.textContent = "Saving, then running every check again…";
      vRun(cmd(ta.value.replace(/\n+/g, " ").trim()), e.currentTarget, `Edit ${what} ${n} · ${VID.t}`).then(() => loadVideo(true));
    } });
  const del = el("button", { type: "button", class: "danger sm", text: `Delete ${what}`, onclick: async (e) => {
    if (await askConfirm(`Delete this ${what}?`, `${what[0].toUpperCase() + what.slice(1)} ${n} goes; Undo brings it back.`, "Delete")) vRun(cmd(""), e.currentTarget, `Delete ${what} ${n} · ${VID.t}`).then(() => loadVideo(true));
  } });
  const cancel = el("button", { type: "button", class: "ghost sm", text: "Cancel", onclick: () => renderPanel("check") });
  ta.addEventListener("keydown", (e) => { if (e.key === "Escape") cancel.click(); if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save.click(); });
  // What he is fixing, above the words, so the finding is not a scroll away.
  const said = fs.length ? el("ul", { class: "findings in-edit" }, fs.map((f) => el("li", { class: f.severity === "block" ? "bad" : f.severity === "note" ? "" : "warn" },
    el("b", { text: `${SEV_WORD[f.severity] || ""} · ${f.gate}: ` }), f.message))) : null;
  const tags = /\[[A-Z]/.test(text) ? el("p", { class: "meta", text: "Words in [BRACKETS] are marks, not spoken: [BEAT: …] starts a part of the video, and ones like [CURIOUS] set how the voice says the words after them. Keep them where they are." }) : null;
  setKids(row, el("span", { class: "ln", text: String(n) }), el("div", { class: "edit" }, said, ta, tags,
    el("p", { class: "meta", text: `Save stores this as a new version (Undo goes back to the old one) and runs every check again. Ctrl+Enter saves, Esc cancels.` }),
    el("div", { class: "row" }, save, cancel, del, status)));
  ta.focus();
}

const SEV_WORD = { block: "Stops Approve", warn: "Worth a look", note: "For the record" };

// What this step is and how to use it, once, at the top.
function checkHowTo(blocking, unit) {
  let open = blocking > 0;
  try { if (localStorage.getItem("check-howto") === "closed") open = false; } catch { /* private window */ }
  const box = el("details", { class: "how-to", open },
    el("summary", { text: "How this step works" }),
    el("ul", {},
      el("li", { text: "The checks are rules the bot runs on your script, not an AI. The fact-check finds every figure the voice says, works out which row of your workbook it is about (revenue, free cash flow, …) and which period (a year or a quarter), and compares it with your workbook." }),
      el("li", { text: "Red stops Approve. Yellow is worth a look and does not stop anything. Plain ones are for the record: a figure it could not check, and why. When the check is unsure which row a figure belongs to it says “a guess”, and a guess is only ever yellow." }),
      el("li", { text: `To fix one: press “Edit ${unit}” on the finding, or click the ${unit}. Change the words and press Save ${unit}. The bot keeps the new version, runs every check again (a few seconds), and this page updates. “Undo last change” goes back one save.` }),
      el("li", { text: "When a red fact-check is wrong and you know the figure is right, press “It's right, let it through” on it. It turns into a note until that sentence or your workbook changes; then it is checked again." })));
  box.addEventListener("toggle", () => { try { localStorage.setItem("check-howto", box.open ? "open" : "closed"); } catch { /* fine */ } });
  return box;
}

STEPS_UI.check = (d) => {
  const byLine = {};
  (d.findings || []).forEach((f) => { if (f.raw_line) (byLine[f.raw_line] ||= []).push(f); });
  const claimLines = new Set((d.claims || []).map((c) => c.line));
  const sentences = d.mode === "sentences";
  const openers = {};
  const lineRow = (ln, idPrefix, raw) => {
    const fs = idPrefix === "line" ? byLine[ln.n] || [] : [];
    const row = el("li", { id: `${idPrefix}-${ln.n}`, class: `${fs.some((f) => f.severity === "block") ? "bad" : fs.some((f) => f.severity === "warn") ? "warn" : ""}${idPrefix === "line" && claimLines.has(ln.n) ? " claim" : ""}`,
      tabindex: "0", title: `Click to change this ${raw ? "sentence" : "line"}`, "data-n": ln.n },
      el("span", { class: "ln", text: String(ln.n) }), el("span", { class: "tx" }, lineText(ln.text) || " "));
    const open = () => { if (!row.querySelector("textarea")) editLine(row, ln.n, ln.text, raw ? ln.raw : "", fs); };
    if (idPrefix === "line") openers[ln.n] = open;
    row.addEventListener("click", (e) => { if (!row.querySelector("textarea")) open(); e.stopPropagation(); });
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" && !row.querySelector("textarea")) { e.preventDefault(); open(); } });
    return row;
  };
  const lines = el("ol", { class: `script-lines${sentences ? " sentences-mode" : ""}` }, (d.lines || []).map((ln) => lineRow(ln, "line", sentences)));
  const dataLines = sentences && (d.data_lines || []).length ? el("details", { class: "data-lines" },
    el("summary", { text: `The rest of the script: headlines, numbers, the plates' data (${d.data_lines.length} lines)` }),
    el("ol", { class: "script-lines" }, d.data_lines.map((ln) => lineRow(ln, "data", false)))) : null;
  const goLine = (n) => { const r = $(`#line-${n}`); if (r) { r.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" }); r.classList.remove("flash"); void r.offsetWidth; r.classList.add("flash"); r.focus({ preventScroll: true }); } };
  const unit = sentences ? "sentence" : "line";
  const editAt = (n) => { goLine(n); if (openers[n]) openers[n](); };
  // Under each finding: what he can do about it, by name.
  const findingActions = (f) => {
    const btns = [];
    if (f.raw_line && f.severity !== "note") btns.push(el("button", { type: "button", class: "sm", text: `Edit ${unit} ${f.raw_line}`, onclick: () => editAt(f.raw_line) }));
    if (f.trustable && f.key) btns.push(el("button", { type: "button", class: "sm ghost", text: "It's right, let it through",
      title: "You checked the figure yourself: this stops blocking until the sentence or the workbook changes",
      onclick: async (e) => {
        const b = e.currentTarget;
        if (await askConfirm("Let this figure through?", "Only if you checked it against your workbook or the filing and it is right. It stops blocking Approve and shows as a note. If you change this sentence or upload a new workbook, it is checked again.", "It's right"))
          vRun(`/script trust ${f.key}`, b, `Let through · ${VID.t}`).then(() => loadVideo(true));
      } }));
    return btns.length ? el("div", { class: "row finding-actions" }, btns) : null;
  };
  const groups = {};
  (d.findings || []).forEach((f) => (groups[f.gate || "other"] ||= []).push(f));
  const side = [];
  const blocking = (d.findings || []).filter((f) => f.severity === "block");
  side.push(el("div", { class: "stats" },
    el("span", { title: "Share of the video with only Dennis on screen" }, "Dennis alone ", el("b", { text: d.dennis_alone >= 0 ? `${Math.round(d.dennis_alone * 100)}%` : "–" })),
    el("span", {}, "Runtime ", el("b", { text: d.est_runtime_min ? `${d.est_runtime_min.toFixed(1)} min` : "–" })),
    el("span", {}, "Render ", el("b", { text: d.est_render_min ? `~${Math.round(d.est_render_min)} min` : "–" })),
    d.words ? el("span", {}, "Words ", el("b", { text: String(d.words) })) : null));
  side.push(el("h4", { text: `What the checks found (${(d.findings || []).length})` }));
  if (!(d.findings || []).length) side.push(el("p", { class: "ok-line", text: d.lines?.length ? "Nothing. Clean." : "No script yet." }));
  Object.entries(groups).forEach(([gate, fs]) => side.push(el("details", { open: fs.some((f) => f.severity === "block") || Object.keys(groups).length < 4, class: "gate" },
    el("summary", {}, el("b", { text: gate }), el("span", { class: "meta", text: ` ${fs.length}` })),
    el("ul", { class: "findings" }, fs.map((f) => el("li", { class: f.severity === "block" ? "bad" : f.severity === "note" ? "" : "warn" },
      el("small", { class: "sev", text: SEV_WORD[f.severity] || "" }), " ",
      f.raw_line ? el("button", { type: "button", class: "link", text: `${unit} ${f.raw_line}`, onclick: () => goLine(f.raw_line) }) : null, " ", f.message,
      f.excerpt ? el("q", { text: f.excerpt }) : null,
      findingActions(f)))))));
  if ((d.claims || []).length) {
    side.push(el("details", { class: "gate" }, el("summary", {}, el("b", { text: "Claims to check" }), el("span", { class: "meta", text: ` ${d.claims.length}` })),
      el("ul", { class: "findings" }, d.claims.map((c) => el("li", {},
        c.line ? el("button", { type: "button", class: "link", text: `${unit} ${c.line}`, onclick: () => goLine(c.line) }) : null, " ", c.text, el("small", { class: "meta", text: ` (${c.why})` }))))));
  }
  // The cold read: a first-time viewer's read, from his own Claude chat.
  const cr = d.cold_read;
  side.push(el("h4", { text: "Cold read" }));
  side.push(el("p", { class: "meta", text: "Paste the prompt into a fresh Claude chat; paste its answer here. Each quote is linked to its line." }));
  if (d.cold_prompt) side.push(el("div", { class: "row" }, copyBtn("Copy the cold-read prompt", d.cold_prompt)));
  if (cr) {
    side.push(el("div", { class: `cold${cr.stale ? " stale" : ""}` },
      cr.stale ? el("p", { class: "warn-line", text: "This read is of an earlier version of the script." }) : null,
      el("ul", { class: "findings" }, (cr.quotes || []).map((q) => el("li", {},
        q.line ? el("button", { type: "button", class: "link", text: `${unit} ${q.line}`, onclick: () => goLine(q.line) }) : null, " ", el("q", { text: q.quote })))),
      el("details", {}, el("summary", { text: "The whole answer" }), el("pre", { class: "text", text: cr.text }))));
  }
  side.push(pasteBox("Paste the cold-read answer", "Save the read", (t, b) => vRun(`/script coldread ${t}`, b, `Cold read → ${VID.t}`)));
  side.push(el("h4", { text: "Why this one" }));
  const why = el("textarea", { rows: 3, placeholder: "In your own words: why this video is worth making. It prints above Approve and rides the description." });
  why.value = d.why || "";
  why.addEventListener("input", () => { why.dataset.dirty = "1"; });
  side.push(why, el("div", { class: "row end" }, el("button", { type: "button", class: "sm", text: "Save why", onclick: (e) => {
    if (why.value.trim()) vRun(`/script why ${why.value.replace(/\n+/g, " ")}`, e.currentTarget, `Why → ${VID.t}`).then(() => delete why.dataset.dirty);
  } })));
  const tools = el("div", { class: "row" },
    el("button", { type: "button", class: "sm", text: "Undo last change", title: "Puts back the script as it was before your last save, and runs the checks on it", disabled: !d.revisions,
      onclick: (e) => vRun("/script undo", e.currentTarget, `Undo · ${VID.t}`).then(() => loadVideo(true)) }),
    el("span", { class: "meta", text: d.revisions ? `${d.revisions} saved edit${d.revisions === 1 ? "" : "s"}; Undo goes back one.` : "No edits yet: this is the script as you pasted it." }));
  const stops = blocking.length ? el("div", { class: "banner bad", text: `${blocking.length} ${blocking.length === 1 ? "thing stops" : "things stop"} Approve. Fix the words with “Edit ${unit}”, or, for a fact-check whose figure you know is right, press “It's right, let it through”.` }) : null;
  return {
    main: blocking.length ? mainButton(blocking[0].raw_line ? `Fix ${unit} ${blocking[0].raw_line}` : "Fix what blocks", () => blocking[0].raw_line && editAt(blocking[0].raw_line), "danger")
      : d.lines?.length ? mainButton("Next: the proof", () => openVideo(VID.t, VID.d, "proof")) : null,
    body: [checkHowTo(blocking.length, unit), stops, el("div", { class: "check-grid" }, el("div", { class: "script-col" }, tools, lines, dataLines), el("aside", { class: "side-col" }, side))],
  };
};

// Proof: player, chapter marks, a strip of frames, and his notes.
function videoPlayer(url, chapters, onKey) {
  const video = el("video", { src: withKey(url), controls: true, preload: "metadata", playsinline: true, class: "proof-video", tabindex: "0" });
  video.addEventListener("loadedmetadata", () => video.classList.toggle("portrait", video.videoHeight > video.videoWidth));
  const marks = (chapters || []).length ? el("div", { class: "chapters" }, chapters.map((c) => el("button", { type: "button", class: "sm ghost",
    text: `${fmtTime(c.t)} ${c.title}`, onclick: () => { video.currentTime = c.t; video.focus(); } }))) : null;
  video.addEventListener("keydown", (e) => {
    if (e.key === "," || e.key === ".") { e.preventDefault(); video.pause(); video.currentTime = Math.max(0, video.currentTime + (e.key === "," ? -1 : 1) / 30); }
    else if (onKey) onKey(e, video);
  });
  return { video, marks };
}

STEPS_UI.proof = (d) => {
  const body = [];
  let main = cbButtons([d.render.map((b) => Object.assign({}, b, { text: d.url ? "Render the proof again ($0)" : "Render the free proof ($0)" }))], { nextRow: !d.url });
  if (!d.url) {
    body.push(empty("No proof yet", "A proof is free: the real visuals at full size, with the free voice.", "", "▶"));
    return { main, body };
  }
  const noteInput = el("input", { type: "text", placeholder: "What is wrong at this moment?", class: "grow" });
  const noteAt = el("span", { class: "meta", text: "" });
  const noteRow = el("div", { class: "row note-row", hidden: true }, noteAt, noteInput,
    el("button", { type: "button", class: "primary sm", text: "Add note", onclick: (e) => addNote(e.currentTarget) }));
  let at = 0;
  const { video, marks } = videoPlayer(d.url, d.chapters, (e, v) => {
    if (e.key === "n") { e.preventDefault(); v.pause(); at = v.currentTime; noteAt.textContent = fmtTime(at); noteRow.hidden = false; noteInput.dataset.dirty = "1"; noteInput.focus(); }
  });
  function addNote(btn) {
    const text = noteInput.value.trim();
    if (!text) { noteInput.focus(); return; }
    vRun(`/render notes add ${at.toFixed(2)} ${text}`, btn, `Note at ${fmtTime(at)} · ${VID.t}`).then(() => {
      noteInput.value = ""; delete noteInput.dataset.dirty; noteRow.hidden = true; video.focus(); loadVideo(true);
    });
  }
  noteInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addNote(); } if (e.key === "Escape") { noteRow.hidden = true; delete noteInput.dataset.dirty; video.focus(); } });
  body.push(el("div", { class: "player-wrap" }, video, marks,
    el("p", { class: "meta", text: "Click the video, then: n notes a fault here · , and . step one frame · space plays" }), noteRow));
  if ((d.strip || []).length) {
    body.push(el("div", { class: "strip", role: "list", "aria-label": "Frames across the proof" }, d.strip.map((f) => el("button", {
      type: "button", class: "frame", role: "listitem", title: `Go to ${fmtTime(f.t)}`, onclick: () => { video.currentTime = f.t; video.focus(); } },
      el("img", { src: withKey(f.url), alt: `frame at ${fmtTime(f.t)}`, loading: "lazy" }), el("small", { text: fmtTime(f.t) })))));
  } else {
    body.push(el("p", { class: "meta", text: "Drawing a strip of frames across the proof…" }));
  }
  if ((d.checks || []).length) {
    body.push(el("h4", { text: "What the render found" }),
      el("div", { class: "checks" }, d.checks.map((c) => el("p", { class: "banner warn pre", text: c }))));
  }
  body.push(el("h4", { text: `Your notes (${(d.notes || []).length})` }));
  if ((d.notes || []).length) {
    body.push(el("ol", { class: "notes" }, d.notes.map((n, i) => el("li", {},
      el("button", { type: "button", class: "link", text: fmtTime(n.t), onclick: () => { video.currentTime = n.t; video.focus(); } }), " ", n.text, " ",
      el("button", { type: "button", class: "ghost sm", text: "✕", "aria-label": `Drop note ${i + 1}`, title: "Drop this note",
        onclick: (e) => vRun(`/render notes drop ${i + 1}`, e.currentTarget, `Drop note ${i + 1} · ${VID.t}`).then(() => loadVideo(true)) })))));
    body.push(el("div", { class: "row" }, copyBtn("Copy the fault list", d.faults, "The numbered list with timestamps, ready to paste")));
  } else {
    body.push(el("p", { class: "meta", text: "None yet. Press n on the video where something is off." }));
  }
  return { main, body };
};

STEPS_UI.approve = (d) => {
  const body = [];
  const money = el("div", { class: "money-box" },
    el("div", {}, "The paid voice ", el("b", { text: d.cached ? "is already made ($0)" : d.est_usd != null ? `~$${d.est_usd.toFixed(2)}` : "–" })),
    d.mtd != null ? el("div", {}, "This month ", el("b", { text: `$${d.mtd.toFixed(2)} of $${Number(d.cap).toFixed(2)}` })) : null);
  body.push(money);
  if ((d.blockers || []).length) body.push(el("div", { class: "banner bad", text: "Blocking findings first, on the Check step:" }), findingList(d.blockers.map((b) => ({ message: b, severity: "block" }))));
  if (d.approved) {
    body.push(el("p", { class: "ok-line", text: `Approved (script ${d.sha8}). The free looks and the paid render:` }), cbButtons(d.buttons, { nextRow: true }));
    return { main: mainButton("Next: the render", () => openVideo(VID.t, VID.d, "render")), body };
  }
  if (!(d.buttons || []).length && !(d.blockers || []).length) body.push(el("p", { class: "meta", text: "The checks run when the script comes in; Approve appears once nothing blocks it." }));
  return { main: (d.buttons || []).length ? cbButtons(d.buttons, { nextRow: true }) : null, body };
};

// Voice: the script lit word by word as it plays, sentence redos, sayings.
STEPS_UI.voice = (d) => {
  if (!d.audio_url) return { main: null, body: [empty("No voice yet", "The paid voice is made when the final render starts. Nothing has been spent.", "", "🎙")] };
  const audio = el("audio", { src: withKey(d.audio_url), controls: true, preload: "metadata", class: "voice-audio" });
  const words = (d.words || []).map((w, i) => el("span", { class: "w", "data-i": i, text: `${w.w} `, title: `${fmtTime(w.s)} — click to play from here, double-click to fix how it is said`,
    onclick: () => { audio.currentTime = w.s; audio.play(); }, ondblclick: () => sayWord(w.w.replace(/[^\w'’-]/g, "")) }));
  const text = el("div", { class: "voice-text" }, words);
  let lit = -1;
  audio.addEventListener("timeupdate", () => {
    const t = audio.currentTime;
    let i = d.words.findIndex((w) => t >= w.s && t < w.e + 0.05);
    if (i < 0) return;
    if (i !== lit) { words[lit]?.classList.remove("lit"); words[i].classList.add("lit"); lit = i; }
  });
  const sayBox = el("div", { class: "say-row row", hidden: true });
  function sayWord(word) {
    if (!word) return;
    const said = el("input", { type: "text", placeholder: "how it should sound, e.g. ee-bit-dah", class: "grow", "data-dirty": "1" });
    setKids(sayBox, el("b", { text: word }), " is said ", said,
      el("button", { type: "button", class: "primary sm", text: "Teach it", onclick: (e) => said.value.trim() && vRun(`/voice say ${word} => ${said.value.trim()}`, e.currentTarget, `Say ${word} · ${VID.t}`).then(() => { sayBox.hidden = true; loadVideo(true); }) }),
      el("button", { type: "button", class: "ghost sm", text: "Cancel", onclick: () => { sayBox.hidden = true; } }));
    sayBox.hidden = false; said.focus();
  }
  const left = d.redos_left;
  const sentences = el("ol", { class: "sentences" }, (d.sentences || []).map((s) => el("li", {},
    el("button", { type: "button", class: "link", text: fmtTime(s.start), onclick: () => { audio.currentTime = s.start; audio.play(); } }), " ", s.text, " ",
    el("button", { type: "button", class: "sm money", text: "Redo 💰", disabled: left === 0, title: left === 0 ? "No redos left for this video" : `Speak sentence ${s.index} again (${left} left)`,
      onclick: async (e) => {
        const b = e.currentTarget;
        if (await askConfirm(`Redo sentence ${s.index}?`, `The paid voice speaks “${s.text.slice(0, 120)}” again, and a running render restarts. ${left} redos left.`, "Redo it")) vRun(`/voice redo ${s.index}`, b, `Redo ${s.index} · ${VID.t}`);
      } }))));
  const compare = (d.compare || []).length ? el("div", { class: "compare" }, el("h4", { text: "Room and de-ess compare" }),
    d.compare.map((c) => el("label", {}, el("span", { text: c.name }), el("audio", { src: withKey(c.url), controls: true, preload: "none" })))) : null;
  return {
    main: el("button", { type: "button", class: "sm", text: "Make the compare clip", title: "The same lines four ways, to decide VOICE_ROOM and VOICE_DEESS", onclick: (e) => vRun("/voice compare", e.currentTarget) }),
    body: [audio, el("p", { class: "meta", text: "Click a word to play from it; double-click to fix how it is said." }), sayBox, text,
      el("h4", { text: `Sentences${left != null ? ` · ${left} redos left` : ""}` }), sentences, compare],
  };
};

// Render: stage, share, time left, the job's last lines, and Stop.
STEPS_UI.render = (d) => {
  const body = [];
  let main = null;
  if (d.job) {
    const p = d.progress || {};
    body.push(el("div", { class: "progress-box" },
      el("div", { class: "row between" }, el("b", { text: `${d.job.kind} · ${p.stage || d.job.status}` }),
        el("span", { class: "meta", text: p.eta_s != null ? `about ${dur(p.eta_s)} left` : "" })),
      el("progress", { max: 100, value: p.pct || 0, "aria-label": "Render progress" }),
      el("div", { class: "meta", text: `${p.pct || 0}% · ${d.job.detail || d.job.status}` })));
    const logBox = el("pre", { class: "log", text: (d.log || []).join("\n") || "No log lines yet." });
    body.push(el("h4", { text: "What it is doing" }), logBox);
    VID.logTimer = setInterval(async () => {
      try { const r = await api(`/api/joblog?id=${encodeURIComponent(d.job.id)}&n=12`); logBox.textContent = r.lines.join("\n") || logBox.textContent; } catch { /* next tick */ }
    }, 3000);
    main = cbButtons([(d.cancel[0] || []).filter((b) => b.data.startsWith("j|")).map((b) => Object.assign({}, b, { text: "Stop the render 🚫" }))], {
      local: (b, btn) => { askConfirm("Stop the render?", "What is already made is kept in the caches; a re-run picks up from there.", "Stop it").then((yes) => yes && callback(b.data, "Stop · " + VID.t, btn, here())); return true; } });
  } else if (d.final_url) {
    const { video } = videoPlayer(d.final_url, []);
    body.push(el("p", { class: "ok-line", text: "The final is rendered." }), video);
    main = mainButton("Next: upload", () => openVideo(VID.t, VID.d, "upload"));
  } else if ((d.render || []).length) {
    main = cbButtons(d.render, {});
    body.push(empty("Ready to render", "Approved. This is the step that spends: the paid voice, then the cut.", "", "💰"));
  } else {
    body.push(empty("Not yet", "Approve the script first.", "", "·"));
  }
  if (d.last && !d.job && d.last.status === "failed") body.push(el("div", { class: "banner bad", text: `The last ${d.last.kind} failed: ${d.last.error}` }), el("pre", { class: "log", text: (d.log || []).join("\n") }));
  return { main, body };
};

// Upload: everything YouTube asks for, one copy button each.
function field(label, value, rows = 1) {
  const box = rows > 1 ? el("textarea", { rows, readonly: true }) : el("input", { type: "text", readonly: true });
  box.value = value || "";
  return el("div", { class: "field" }, el("div", { class: "row between" }, el("b", { text: label }), copyBtn("Copy", value || "", `Copy the ${label.toLowerCase()}`)), box);
}
STEPS_UI.upload = (d, v) => {
  if (!d.ready) return { main: null, body: [empty("Nothing to upload yet", "The final render comes first.", "", "·")] };
  const body = [];
  if (d.uploaded) body.push(el("p", { class: "ok-line" }, "Uploaded: ", el("a", { href: d.uploaded.url, target: "_blank", rel: "noopener", text: d.uploaded.url }), ` (${d.uploaded.privacy})`));
  const cols = el("div", { class: "upload-grid" });
  const left = el("div", {});
  (d.titles || []).forEach((t, i) => left.append(field(`Title ${i + 1}`, t)));
  left.append(field("Description", d.description, 10), field("Tags", (d.tags || []).join(", "), 2), field("Pinned comment", d.pinned, 3));
  if ((d.chapters || []).length) left.append(field("Chapters", d.chapters.map((c) => `${c.stamp} ${c.title}`).join("\n"), Math.min(d.chapters.length, 8)));
  const right = el("div", {});
  right.append(el("h4", { text: "In YouTube Studio" }), el("ol", { class: "checklist" }, (d.checklist || []).map((c, i) => {
    const id = `ck-${v.ticker}-${v.workdate}-${i}`;
    const box = el("input", { type: "checkbox", id });
    try { box.checked = sessionStorage.getItem(id) === "1"; } catch { /* private window */ }
    box.addEventListener("change", () => { try { sessionStorage.setItem(id, box.checked ? "1" : "0"); } catch { /* fine */ } });
    return el("li", {}, box, el("label", { for: id, text: c }));
  })));
  const th = d.thumbnail || {};
  const coverIn = el("input", { type: "file", accept: "image/png,image/jpeg", class: "sr-only" });
  coverIn.addEventListener("change", () => {
    const f = coverIn.files[0];
    if (f) sendFile(f, `/api/thumbnail?t=${encodeURIComponent(v.ticker)}&d=${encodeURIComponent(v.workdate)}&fmt=${th.fmt}`, `Cover · ${f.name} → ${v.ticker}`);
    coverIn.value = "";
  });
  right.append(el("h4", { text: "Cover" }), el("div", { class: "covers" },
    th.current ? el("figure", {}, el("img", { src: withKey(th.current), alt: "the cover the upload sends" }), el("figcaption", { text: th.his ? "Yours (this one goes up)" : "The bot's (this one goes up)" })) : el("p", { class: "meta", text: "No cover yet." }),
    th.his && th.bot ? el("figure", {}, el("img", { src: withKey(th.bot), alt: "the bot's cover" }), el("figcaption", { text: "The bot's, kept" })) : null),
  el("div", { class: "row" },
    el("label", { class: "button sm", title: "Your Figma cover; it replaces the bot's on the upload" }, coverIn, "Use my cover…"),
    th.his ? el("button", { type: "button", class: "ghost sm", text: "Back to the bot's", onclick: async (e) => {
      if (await askConfirm("Use the bot's cover again?", "Your picture is removed from this video.", "Yes")) sendFile(new Blob([]), `/api/thumbnail?t=${encodeURIComponent(v.ticker)}&d=${encodeURIComponent(v.workdate)}&fmt=${th.fmt}`, `Cover · bot's → ${v.ticker}`);
    } }) : null));
  right.append(el("h4", { text: "Downloads" }), el("ul", { class: "downloads" }, (d.downloads || []).map((f) => el("li", {}, el("a", { href: withKey(f.url), download: f.name, text: f.name })))));
  const link = el("input", { type: "url", placeholder: "https://youtu.be/…", class: "grow" });
  const priv = el("select", {}, ["unlisted", "private", "public"].map((p) => el("option", { value: p, text: p })));
  right.append(el("h4", { text: "Uploaded it yourself? Paste the link" }), el("div", { class: "row" }, link, priv,
    el("button", { type: "button", class: "sm", text: "Save the link", onclick: (e) => link.value.trim() && vRun(`${d.mark_hint}${link.value.trim()} ${priv.value}`, e.currentTarget, `Link · ${v.ticker}`) })));
  if (d.uploading) {
    // the bot is sending it: how far, and no second press meanwhile
    const pct = d.uploading.pct || 0;
    right.append(el("h4", { text: "Uploading to YouTube" }),
      el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-label": `${v.ticker} upload` },
        el("i", { style: `width:${pct}%` })),
      el("p", { class: "meta", text: `${pct}% sent. The link comes to Activity when it is done.` }));
  } else {
    right.append(el("h4", { text: "Or let the bot upload it" }), cbButtons(d.buttons, {}));
  }
  cols.append(left, right);
  body.push(cols);
  return { main: (d.titles || [])[0] ? copyBtn("Copy title 1", d.titles[0]) : null, body };
};

// Live: retention as a line, with the chapters, and the lines viewers left on.
function retentionChart(curve, chapters, duration) {
  const W = 720, H = 220, P = 28;
  const maxY = Math.max(1, ...curve.map((p) => p.y));
  const x = (r) => P + r * (W - 2 * P);
  const y = (v) => H - P - (v / maxY) * (H - 2 * P);
  const ns = "http://www.w3.org/2000/svg";
  const mk = (tag, attrs) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v2]) => n.setAttribute(k, v2)); return n; };
  const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Share of viewers still watching across the video" });
  [0, 0.25, 0.5, 0.75, 1].forEach((g) => { svg.append(mk("line", { x1: P, x2: W - P, y1: y(g * maxY), y2: y(g * maxY), class: "grid" })); const t = mk("text", { x: 2, y: y(g * maxY) + 4, class: "lbl" }); t.textContent = `${Math.round(g * maxY * 100)}%`; svg.append(t); });
  (chapters || []).forEach((c) => { if (!duration) return; const cx = x(Math.min(c.t / duration, 1)); svg.append(mk("line", { x1: cx, x2: cx, y1: P, y2: H - P, class: "mark" })); const t = mk("text", { x: cx + 3, y: P + 10, class: "lbl" }); t.textContent = c.title; svg.append(t); });
  svg.append(mk("polyline", { points: curve.map((p) => `${x(p.x)},${y(p.y)}`).join(" "), class: "line" }));
  return svg;
}
STEPS_UI.live = (d) => {
  if (!d.video) return { main: null, body: [empty("Not out yet", "Once it is uploaded, how viewers watched it shows here.", "", "·")] };
  const body = [el("p", {}, el("a", { href: d.video.url, target: "_blank", rel: "noopener", text: d.video.title || d.video.url }), el("span", { class: "meta", text: ` · ${d.video.privacy}` })),
    d.synthetic_declared === false ? el("div", { class: "banner bad", text: "YouTube did not confirm the altered or synthetic content label on this upload. Set it in Studio." }) : null,
    ...(d.upload_notes || []).filter((n) => !n.startsWith("YouTube's reply does NOT")).map((n) => el("div", { class: "banner warn", text: n }))];
  if ((d.curve || []).length) body.push(retentionChart(d.curve, d.chapters, d.duration_s));
  else body.push(el("p", { class: "meta", text: "Retention reads from 48 hours after it goes public." }));
  if ((d.lines || []).length) {
    const worst = d.lines.slice().sort((a, b) => b.drop - a.drop).slice(0, 8);
    body.push(el("h4", { text: "Where viewers left" }), el("ol", { class: "findings" }, worst.map((l) => el("li", { class: l.drop > 0.05 ? "warn" : "" },
      el("b", { text: fmtTime(l.start) }), ` lost ${Math.round(l.drop * 100)}% · `, l.text))));
  }
  if ((d.corrections || []).length) body.push(el("h4", { text: "Corrections pinned" }), el("ul", {}, d.corrections.map((c) => el("li", { text: `${(c.at || "").slice(0, 10)} ${c.text || c}` }))));
  return { main: cbButtons([[(d.buttons[0] || [])[0]].filter(Boolean)], {}), body: body.concat([cbButtons(d.buttons, { sm: true })]) };
};

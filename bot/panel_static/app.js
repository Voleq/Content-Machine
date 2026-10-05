// Dennis control panel — no framework, no build step. Every action posts to
// the bot, which runs it through the same code the Telegram chat uses.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const KEY_STORE = "dennis.panel.key";
let KEY = "";
let REGISTRY = null;
let STATE = null;
let FEED_SEQ = 0;
let UNREAD = 0;
let BUSY = 0;

// ------------------------------------------------------------------ helpers
function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function readStore(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } }
function writeStore(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } }

function when(ts) {
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d)) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function isVideo(name) { return /\.(mp4|mov|webm|mkv)$/i.test(name); }
function isImage(name) { return /\.(png|jpe?g|webp|gif)$/i.test(name); }
function fileUrl(path) { return `/api/file?path=${encodeURIComponent(path)}&k=${encodeURIComponent(KEY)}`; }

// --------------------------------------------------------------------- api
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Panel-Key": KEY }, opts.headers || {});
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { showLogin(); throw new Error("the panel key is missing or wrong"); }
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// ------------------------------------------------------------------ login
function showLogin() {
  $("#app").hidden = true;
  $("#login").hidden = false;
}

function boot() {
  const m = location.hash.match(/k=([^&]+)/);
  if (m) {
    KEY = decodeURIComponent(m[1]);
    writeStore(KEY_STORE, KEY);
    history.replaceState(null, "", location.pathname + location.search);   // the key leaves the URL bar
  } else {
    KEY = readStore(KEY_STORE);
  }
  if (!KEY) return showLogin();
  start();
}

$("#login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  KEY = $("#key").value.trim();
  writeStore(KEY_STORE, KEY);
  start();
});

async function start() {
  try {
    REGISTRY = await api("/api/registry");
  } catch (e) {
    return;
  }
  $("#login").hidden = true;
  $("#app").hidden = false;
  renderCommands();
  repliesHint();
  const tab = new URLSearchParams(location.search).get("tab");
  if (tab) showTab(tab);
  await refresh();
  const feed = await api("/api/feed?since=0");
  feed.events.forEach((ev) => addFeed(ev, false));
  FEED_SEQ = feed.seq;
  setInterval(refresh, 5000);
  setInterval(pollFeed, 2500);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { refresh(); pollFeed(); }
  });
}

// ------------------------------------------------------------------- tabs
function showTab(name) {
  const b = document.querySelector(`#tabs button[data-tab="${name}"]`);
  if (!b) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${name}`));
  if (name === "activity") { UNREAD = 0; badge(); }
  const url = new URL(location.href);
  url.searchParams.set("tab", name);
  url.hash = "";
  history.replaceState(null, "", url);
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) showTab(b.dataset.tab);
});

function badge() {
  const u = $("#unread");
  u.hidden = UNREAD === 0;
  u.textContent = UNREAD > 99 ? "99+" : String(UNREAD);
}

// ----------------------------------------------------------------- replies
function buttonsBlock(rows, origin) {
  if (!rows || !rows.length) return null;
  return el("div", { class: "buttons" }, rows.map((row) =>
    el("div", { class: "row" }, row.map((b) =>
      el("button", {
        class: /💰/.test(b.text) ? "money" : "",
        text: b.text,
        onclick: () => callback(b.data, b.text, origin),
      })))));
}

function filesBlock(files) {
  if (!files || !files.length) return null;
  return el("div", { class: "files" }, files.map((f) => {
    const url = f.url || fileUrl(f.path || f);
    const name = f.name || String(f).split("/").pop();
    if (isImage(name)) return el("a", { href: url, target: "_blank" }, el("img", { src: url, alt: name, loading: "lazy" }));
    if (isVideo(name)) return el("video", { src: url, controls: true, preload: "metadata" });
    return el("a", { href: url, target: "_blank", download: name, text: `📎 ${name}` });
  }));
}

function addReply(origin) {
  $("#replies").querySelector(".hint")?.remove();
  const box = el("div", { class: "reply pending" },
    el("div", { class: "origin" }, el("span", { text: origin }), el("span", { text: "⏳ working…" })),
    el("pre", { class: "text" }));
  $("#replies").prepend(box);
  return box;
}

// `replaceChildren` writes a null as the text "null"; `el` already skips them.
const setKids = (node, ...kids) => node.replaceChildren(...kids.filter((k) => k));

function fillReply(box, reply, origin) {
  box.classList.remove("pending");
  setKids(box,
    el("div", { class: "origin" }, el("span", { text: origin }), el("span", { text: when(Date.now() / 1000) })),
    el("pre", { class: "text", text: reply.text || "" }),
    filesBlock(reply.files),
    buttonsBlock(reply.buttons, origin));
}

function failReply(box, err, origin) {
  box.classList.remove("pending");
  box.classList.add("error");
  setKids(box, el("div", { class: "origin" }, el("span", { text: origin })),
    el("pre", { class: "text", text: `⛔ ${err.message || err}` }));
}

async function act(origin, fn) {
  const box = addReply(origin);
  BUSY++;
  try {
    const data = await fn();
    fillReply(box, data.reply, origin);
  } catch (e) {
    failReply(box, e, origin);
  } finally {
    BUSY--;
    refresh();
  }
}

const runCommand = (text) => act(text, () => post("/api/run", { text }));
// A reply is labelled with the button that was tapped, and the video it is
// about when the button does not say.
const callback = (data, label) => {
  const ticker = (data.split("|").find((p) => /^[A-Z0-9.\-]{1,15}$/.test(p) && /[A-Z]/.test(p)) || "");
  const named = ticker && label.includes(ticker);
  return act(named || !ticker ? label : `${label} · ${ticker}`, () => post("/api/callback", { data }));
};

function repliesHint() {
  if ($("#replies").children.length) return;
  $("#replies").append(el("div", { class: "hint" },
    "What the bot answers to anything you run, tap or send lands here — with its files and its buttons, ",
    "which work exactly like the ones in Telegram."));
}
$("#clear-replies").addEventListener("click", () => { $("#replies").replaceChildren(); repliesHint(); });

// ------------------------------------------------------------------- state
async function refresh() {
  if (document.hidden && STATE) return;   // a background tab polls nothing
  try {
    STATE = await api("/api/state");
  } catch (e) {
    return;
  }
  renderHeader();
  renderInbox();
  renderJobs();
  renderVideos();
}

function renderHeader() {
  const a = STATE.active;
  $("#active").textContent = a ? `📁 ${a.ticker} · ${a.workdate}` : "no active video";
  $("#active").onclick = a ? () => callback(`c|${a.ticker}|${a.workdate}`, `card ${a.ticker}`) : null;
  const s = STATE.spend;
  $("#spend").textContent = s.mtd === null
    ? "⚠️ spend ledger unreadable"
    : `💵 $${s.mtd.toFixed(2)} / $${s.cap.toFixed(2)}`;
  const quiet = STATE.notify === "quiet";
  $("#notify").textContent = quiet ? "🔕 quiet" : "🔔 all pushes";
  $("#notify").onclick = () => runCommand(`/admin quiet ${quiet ? "off" : "on"}`);
  $("#mock").hidden = !STATE.mock;
  $("#mock").textContent = STATE.mock || "";
  $("#queue-note").textContent = STATE.queue_running ? "" : "⚠️ the render queue is not running in this process";
}

const SECTION_TITLES = {
  approve: "📝 Waiting for your approval",
  blocked: "⛔ Blocked — needs an edit",
  render: "🎬 Approved, not rendered",
  upload: "📤 Rendered, not uploaded",
  scheduled: "📅 Going public in the next 48 h",
  retention: "📊 Retention ready to read",
  failed: "❌ Failed",
};

function renderInbox() {
  const box = $("#inbox");
  const items = STATE.inbox;
  if (!items.length) {
    box.replaceChildren(el("div", { class: "empty", text: "📥 Inbox zero — nothing is waiting on you." }));
    return;
  }
  const out = [];
  let section = "";
  for (const it of items) {
    if (it.section !== section) {
      section = it.section;
      out.push(el("div", { class: "section-title", text: SECTION_TITLES[section] || section }));
    }
    out.push(el("div", { class: "item" },
      el("div", { class: "what" }, el("b", { text: it.ticker }), " ",
        el("span", { class: "muted", text: it.workdate || "" }), el("div", { text: it.text })),
      buttonsBlock(it.buttons, it.ticker)));
  }
  box.replaceChildren(...out);
}

function renderJobs() {
  const box = $("#jobs");
  if (!STATE.jobs.length) {
    box.replaceChildren(el("div", { class: "empty", text: "No jobs yet." }));
    return;
  }
  box.replaceChildren(...STATE.jobs.map((j) => {
    const active = j.status === "queued" || j.status === "running";
    return el("div", { class: "item" },
      el("div", { class: "what" },
        el("span", { class: `job-status ${j.status}`, text: j.status }), " ",
        el("b", { text: j.ticker }), " ", el("span", { text: j.kind.replace(/_/g, " ") }),
        " ", el("span", { class: "muted", text: `${j.workdate} · ${when(j.updated_at)}` }),
        j.detail ? el("div", { class: "muted", text: j.detail }) : null,
        j.error ? el("div", { class: "muted", text: j.error }) : null,
        j.link ? el("div", { class: "muted", text: j.link }) : null),
      active ? el("button", { text: "Cancel 🚫", onclick: () => callback(`j|${j.ticker}|${j.workdate}`, `cancel ${j.ticker}`) }) : null);
  }));
}

function stagesOf(v) {
  const s = [];
  const add = (label, cls) => s.push(el("span", { class: `stage ${cls || ""}`, text: label }));
  add(v.data_file ? "data ✓" : "data", v.data_file ? "ok" : "");
  if (v.lane === "long" && !v.update) add(v.angle ? "angle ✓" : "angle", v.angle ? "ok" : "");
  add(v.script ? `script ✓${v.revisions ? ` r${v.revisions + 1}` : ""}` : "script", v.script ? "ok" : "");
  if (v.report_ok === true) add("gates ✓", "ok");
  else if (v.report_ok === false) add(`gates ⛔ ${v.blocking}`, "bad");
  add(v.approved ? "approved ✓" : "approval", v.approved ? "ok" : "");
  for (const k of ["draft", "proof", "final"]) if (v.renders[k]) add(`${k} ✓`, "ok");
  if (v.active_job) add(`⏳ ${v.active_job.detail || v.active_job.status}`, "run");
  if (v.uploaded) add(v.uploaded.privacy === "scheduled" ? "scheduled ✓" : "uploaded ✓", "ok");
  return el("div", { class: "stages" }, s);
}

function renderVideos() {
  const filter = $("#video-filter").value.trim().toUpperCase();
  const box = $("#videos");
  const vids = STATE.videos.filter((v) => !filter || v.ticker.includes(filter));
  if (!vids.length) {
    box.replaceChildren(el("div", { class: "empty", text: "No videos in the last 14 days. Start one on Home." }));
    return;
  }
  const a = STATE.active;
  // Keep open details open across refreshes.
  const open = new Set([...box.querySelectorAll("details[open]")].map((d) => d.dataset.key));
  box.replaceChildren(...vids.map((v) => {
    const isActive = a && a.ticker === v.ticker && a.workdate === v.workdate;
    const lane = v.update ? "UPDATE" : (v.lane || "no lane").toUpperCase();
    return el("div", { class: `card video${isActive ? " is-active" : ""}` },
      el("h2", {}, el("span", { text: v.ticker }), el("span", { class: "lane", text: `${lane} · ${v.workdate}` })),
      stagesOf(v),
      el("div", { class: "next" }, "→ ", el("b", { text: v.next_step })),
      buttonsBlock(v.buttons, v.ticker),
      el("div", { class: "row wrap", style: "margin-top:.5em" },
        isActive ? el("span", { class: "muted", text: "★ active — pastes and uploads land here" })
          : el("button", { class: "ghost", text: "Work on this", onclick: () => setActive(v) })),
      v.media.length ? el("div", { class: "media" }, v.media.map((m) => isImage(m.name)
        ? el("img", { src: m.url, alt: m.name, title: m.name, loading: "lazy", onclick: () => window.open(m.url, "_blank") })
        : el("button", { text: `▶ ${m.name}`, onclick: () => play(m) }))) : null,
      el("details", { "data-key": v.key, open: open.has(v.key) },
        el("summary", { text: "card" }), el("pre", { class: "text", text: v.card_text })));
  }));
}
$("#video-filter").addEventListener("input", () => STATE && renderVideos());

function setActive(v) {
  act(`work on ${v.ticker} ${v.workdate}`, () => post("/api/active", { ticker: v.ticker, workdate: v.workdate }));
}

function play(m) {
  $("#player-title").textContent = m.name;
  $("#player-video").src = m.url;
  $("#player").showModal();
}
$("#player").addEventListener("close", () => { $("#player-video").pause(); $("#player-video").removeAttribute("src"); });

// ----------------------------------------------------------------- home
$("#start-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target;
  const ticker = f.ticker.value.trim().toUpperCase();
  if (!ticker) return;
  runCommand(`/${f.lane.value} ${ticker}`);
  f.ticker.value = "";
});

$("#send-paste").addEventListener("click", () => {
  const text = $("#paste").value;
  if (!text.trim()) return;
  const label = text.length > 60 ? `paste · ${text.length.toLocaleString()} chars` : `“${text.trim()}”`;
  act(label, () => post("/api/text", { text })).then(() => { $("#paste").value = ""; });
});

function upload(file) {
  const bar = $("#upload-progress");
  const box = addReply(`upload · ${file.name}`);
  bar.hidden = false;
  bar.value = 0;
  BUSY++;
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/upload?name=${encodeURIComponent(file.name)}`);
  xhr.setRequestHeader("X-Panel-Key", KEY);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = e.loaded / e.total; };
  xhr.onloadend = () => {
    BUSY--;
    bar.hidden = true;
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch { /* empty */ }
    if (xhr.status === 200 && data.reply) fillReply(box, data.reply, `upload · ${file.name}`);
    else failReply(box, new Error(data.error || `upload failed (${xhr.status})`), `upload · ${file.name}`);
    refresh();
  };
  xhr.send(file);
}
$("#file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) upload(f); e.target.value = ""; });
const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });

// --------------------------------------------------------------- commands
function renderCommands() {
  const box = $("#commands");
  const filter = $("#cmd-filter").value.trim().toLowerCase();
  const out = [];
  for (const fam of REGISTRY.families) {
    const cmds = REGISTRY.commands.filter((c) => c.family === fam.name && (!filter
      || `${c.name} ${c.help} ${c.doc} ${c.aliases.join(" ")}`.toLowerCase().includes(filter)));
    if (!cmds.length) continue;
    const single = REGISTRY.commands.filter((c) => c.family === fam.name).length === 1;
    out.push(el("div", { class: "card family" },
      el("div", { class: "card-head" }, el("h2", { text: `/${fam.name} — ${fam.title}` }),
        single ? null : el("span", { class: "muted", text: fam.blurb })),
      cmds.map(commandRow)));
  }
  box.replaceChildren(...(out.length ? out : [el("div", { class: "empty", text: "No command matches." })]));
}

function commandRow(c) {
  const input = el("input", {
    placeholder: c.usage || "(no arguments)", autocomplete: "off", spellcheck: "false",
    disabled: !c.usage,
  });
  const run = () => {
    const args = input.value.trim();
    if (c.spends && !confirm(`/${c.name} spends money. Run it?`)) return;
    runCommand(`/${c.name}${args ? ` ${args}` : ""}`);
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  const hint = c.ticker && c.ticker !== "optional"
    ? " The ticker defaults to the active video."
    : "";
  return el("div", { class: "cmd" },
    el("div", { class: "name" }, el("code", { text: `/${c.name}` }), c.spends ? el("span", { class: "tag-money", text: " 💰" }) : null),
    el("div", { class: "help", title: c.doc }, c.help + hint,
      c.aliases.length ? el("span", { class: "aka", text: `was ${c.aliases.map((a) => `/${a}`).join(", ")}` }) : null),
    el("div", { class: "args" }, input),
    el("button", { class: c.spends ? "money" : "", text: "Run", onclick: run }));
}
$("#cmd-filter").addEventListener("input", renderCommands);
$("#cmd-run").addEventListener("click", () => {
  const t = $("#cmd-line").value.trim();
  if (t) runCommand(t.startsWith("/") ? t : `/${t}`);
});
$("#cmd-line").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#cmd-run").click(); });

// ------------------------------------------------------------------- feed
function addFeed(ev, live) {
  const item = el("div", { class: "feed-item" },
    el("div", { class: "when", text: `${when(ev.at)} · ${ev.kind}` }),
    el("pre", { class: "text", text: ev.text || "" }),
    filesBlock(ev.files.map((p) => ({ path: p, name: p.split("/").pop() }))),
    buttonsBlock(ev.buttons, "activity"));
  $("#feed").prepend(item);
  if (live && !$("#tab-activity").classList.contains("on")) { UNREAD++; badge(); }
}

async function pollFeed() {
  if (document.hidden) return;
  try {
    const data = await api(`/api/feed?since=${FEED_SEQ}`);
    data.events.forEach((ev) => addFeed(ev, true));
    if (data.events.length && BUSY === 0) refresh();
    FEED_SEQ = data.seq;
  } catch { /* the next poll tries again */ }
}

boot();

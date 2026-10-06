// Dennis control panel — no framework, no build step. Every action posts to
// the bot, which runs it through the same code the Telegram chat uses.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const KEY_STORE = "dennis.panel.key";
const FEED_STORE = "dennis.panel.feed";
const NARROW = matchMedia("(max-width: 900px)");
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
const MONEY_TTL_S = 600;          // a Confirm 💰 older than this is stale
const KEEP_OPEN = 3;              // replies shown in full; older ones fold
const MAX_REPLIES = 30;

let KEY = "";
let REGISTRY = null;
let STATE = null;
let LAST_RAW = "";
let FEED_SEQ = 0;
let FEED = [];                    // every event since boot, oldest first
let FEED_FILTER = "pushes";
let UNREAD = 0;
let BUSY = 0;
let SHOW_ALL_JOBS = false;
const INFLIGHT = new Set();       // callback data with a request running

// ------------------------------------------------------------------ helpers
function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
// `replaceChildren` writes a null as the text "null"; `el` already skips them.
const setKids = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k));

function readStore(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } }
function writeStore(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } }

const toDate = (ts) => (typeof ts === "number" ? new Date(ts * 1000) : new Date(ts));
function when(ts) {
  const d = toDate(ts);
  if (isNaN(d)) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function clock(ts) {
  const d = toDate(ts);
  return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function ago(ts) {
  const d = toDate(ts);
  if (isNaN(d)) return "";
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return when(ts);
}
const isVideo = (name) => /\.(mp4|mov|webm|mkv)$/i.test(name);
const isImage = (name) => /\.(png|jpe?g|webp|gif)$/i.test(name);
const fileUrl = (path) => `/api/file?path=${encodeURIComponent(path)}&k=${encodeURIComponent(KEY)}`;
const isMoney = (text) => /💰/.test(text || "");
const notToday = (d) => (d && STATE && d !== STATE.today ? d : "");
function empty(title, sub, tone = "", icon = "·", extra = null) {
  return el("div", { class: `empty ${tone}` },
    el("div", { class: "empty-icon", "aria-hidden": "true", text: icon }),
    el("div", { class: "empty-title", text: title }),
    sub ? el("div", { class: "empty-sub", text: sub }) : null, extra);
}
function say(text) { $("#sr-status").textContent = text; }
function alarm(text) { $("#sr-alert").textContent = text; }
function scrollTo(node) {
  node?.scrollIntoView({ block: "center", behavior: REDUCED.matches ? "auto" : "smooth" });
}

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
  $("#status").hidden = true;
  $("#login").hidden = false;
  $("#key").focus();
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
  const f = readStore(FEED_STORE);
  if (["pushes", "replies", "all"].includes(f)) FEED_FILTER = f;
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
  renderFeedFilter();
  repliesEmpty();
  const tab = new URLSearchParams(location.search).get("tab");
  if (tab) showTab(tab, false);
  await refresh();
  const feed = await api("/api/feed?since=0");
  feed.events.forEach((ev) => FEED.push(ev));
  FEED_SEQ = feed.seq;
  renderFeed();
  setInterval(refresh, 5000);
  setInterval(pollFeed, 2500);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { refresh(); pollFeed(); }
  });
}

// ------------------------------------------------------------------- tabs
function showTab(name, focus = false) {
  const b = document.querySelector(`#tabs [data-tab="${name}"]`);
  if (!b) return;
  $$("#tabs [role=tab]").forEach((x) => {
    const on = x === b;
    x.classList.toggle("on", on);
    x.setAttribute("aria-selected", on ? "true" : "false");
    x.tabIndex = on ? 0 : -1;
  });
  $$("main > .tab").forEach((t) => {
    const on = t.id === `tab-${name}`;
    t.classList.toggle("on", on);
    t.hidden = !on;
  });
  if (focus) b.focus();
  if (name === "activity") { UNREAD = 0; badge(); }
  const url = new URL(location.href);
  url.searchParams.set("tab", name);
  url.hash = "";
  history.replaceState(null, "", url);
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) showTab(b.dataset.tab);
});
$("#tabs").addEventListener("keydown", (e) => {
  const tabs = $$("#tabs [role=tab]");
  let i = tabs.indexOf(document.activeElement);
  if (i < 0) return;
  if (e.key === "ArrowRight") i = (i + 1) % tabs.length;
  else if (e.key === "ArrowLeft") i = (i - 1 + tabs.length) % tabs.length;
  else if (e.key === "Home") i = 0;
  else if (e.key === "End") i = tabs.length - 1;
  else return;
  e.preventDefault();
  showTab(tabs[i].dataset.tab, true);
});

function badge() {
  const u = $("#unread");
  u.hidden = UNREAD === 0;
  u.textContent = UNREAD > 99 ? "99+" : String(UNREAD);
  $("#unread-sr").textContent = UNREAD ? ` ${UNREAD} unread` : "";
}

// Press "/" anywhere (outside a field) to type a command.
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t.closest && t.closest("input, textarea, select, [contenteditable]")) return;
  if ($("#app").hidden) return;
  e.preventDefault();
  showTab("commands");
  $("#cmd-line").focus();
});

// ----------------------------------------------------------------- buttons
// One builder for every bot keyboard the panel shows. Money buttons go last
// in their row with room before them, and never take the next-step colour;
// a button is locked while its request runs, so a double click cannot pay
// twice; `once` disables a whole block after one answer (replies, feed);
// `staleAfter` disables money buttons once a decision has gone cold.
function buttonsBlock(rows, opts = {}) {
  const shown = (rows || [])
    .map((row) => row.filter((b) => !(opts.drop && opts.drop(b))))
    .filter((row) => row.length);
  if (!shown.length) return null;
  const block = el("div", { class: "buttons" });
  const stale = opts.staleAfter && Date.now() / 1000 > opts.staleAfter;
  shown.forEach((row, ri) => {
    const sorted = row.slice().sort((a, b) => isMoney(a.text) - isMoney(b.text));
    block.append(el("div", { class: "row" }, sorted.map((b, bi) => {
      const money = isMoney(b.text);
      const label = opts.relabel ? opts.relabel(b) : b.text;
      let cls = money ? "money"
        : /🚫|^Cancel\b/.test(b.text) ? "danger"
          : opts.nextRow && ri === 0 && !(/^Refresh/.test(b.text)) ? "next" : "";
      if (opts.sm) cls += " sm";
      const busy = INFLIGHT.has(b.data);
      const dead = money && stale;
      const node = el("button", {
        type: "button", class: cls.trim(), text: label, "data-cb": b.data,
        disabled: busy || dead, "aria-busy": busy ? "true" : null,
        title: dead ? "Expired — press Render on the card again" : null,
        "aria-label": money ? `${label.replace(/💰/g, "").replace(/\s+/g, " ").trim()} (costs money)` : null,
        onclick: (e) => {
          const btn = e.currentTarget;
          if (btn.disabled || INFLIGHT.has(b.data)) return;
          if (opts.once) {
            $$("button", block).forEach((x) => { x.disabled = true; });
            btn.classList.add("chosen");
          }
          if (opts.local && opts.local(b, btn)) return;
          INFLIGHT.add(b.data);
          callback(b.data, b.text, btn).finally(() => INFLIGHT.delete(b.data));
        },
      });
      void bi;
      return node;
    })));
  });
  if (opts.staleAfter && !stale && shown.flat().some((b) => isMoney(b.text))) {
    setTimeout(() => {
      $$("button.money", block).forEach((x) => {
        x.disabled = true;
        x.title = "Expired — press Render on the card again";
      });
    }, Math.max(0, (opts.staleAfter - Date.now() / 1000) * 1000));
  }
  return block;
}

function filesBlock(files) {
  if (!files || !files.length) return null;
  return el("div", { class: "files" }, files.map((f) => {
    const url = f.url || fileUrl(f.path || f);
    const name = f.name || String(f.path || f).split("/").pop();
    if (isImage(name)) return el("a", { href: url, target: "_blank", rel: "noopener", class: "thumb" }, el("img", { src: url, alt: name, loading: "lazy" }));
    if (isVideo(name)) return el("video", { src: url, controls: true, preload: "metadata", "aria-label": name });
    return el("a", { href: url, target: "_blank", rel: "noopener", download: name, text: `${name}` });
  }));
}

// ----------------------------------------------------------------- replies
const panel = () => $("#replies-panel");
function openSheet(open) {
  if (!NARROW.matches) return;
  panel().classList.toggle("open", open);
  $("#sheet-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  $("#sheet-toggle").setAttribute("aria-label", open ? "Hide replies" : "Show replies");
}
$("#replies-head").addEventListener("click", (e) => {
  if (!NARROW.matches || e.target.closest("#clear-replies")) return;
  openSheet(!panel().classList.contains("open"));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && panel().classList.contains("open")) openSheet(false);
});

function repliesEmpty() {
  if ($("#replies").querySelector(".reply")) return;
  setKids($("#replies"), empty("Replies land here",
    "Anything you run, tap or send — with its files and working buttons.", "", "↩"));
  $("#reply-peek").textContent = "";
  $("#reply-count").hidden = true;
}
$("#clear-replies").addEventListener("click", () => { $("#replies").replaceChildren(); repliesEmpty(); });

function peek(text) {
  $("#reply-peek").textContent = text;
  const n = $$("#replies .reply").length;
  $("#reply-count").hidden = n === 0;
  $("#reply-count").textContent = String(n);
}

function foldOlder() {
  $$("#replies .reply").forEach((r, i) => {
    if (i >= KEEP_OPEN && !r.classList.contains("pending")) r.classList.add("collapsed");
    if (i >= MAX_REPLIES) r.remove();
  });
}

function addReply(origin) {
  $("#replies .empty")?.remove();
  const box = el("div", { class: "reply pending", "aria-busy": "true" },
    el("div", { class: "origin" }, el("span", { text: origin }), el("span", { class: "working", text: "working…" })),
    el("pre", { class: "text" }));
  box.querySelector(".origin").addEventListener("click", () => box.classList.toggle("collapsed"));
  $("#replies").prepend(box);
  foldOlder();
  peek(`${origin} — working…`);
  openSheet(true);
  return box;
}

function fillReply(box, reply, origin) {
  box.classList.remove("pending");
  box.removeAttribute("aria-busy");
  const money = (reply.buttons || []).flat().some((b) => isMoney(b.text));
  box.classList.toggle("has-money", money);
  setKids(box,
    el("div", { class: "origin" }, el("span", { text: origin }), el("time", { text: clock(Date.now() / 1000) })),
    el("pre", { class: "text", text: reply.text || "" }),
    filesBlock(reply.files),
    buttonsBlock(reply.buttons, { once: true, staleAfter: Date.now() / 1000 + MONEY_TTL_S }));
  box.classList.add("new");
  setTimeout(() => box.classList.remove("new"), 1500);
  const first = (reply.text || "").split("\n")[0];
  peek(`${origin}: ${first}`);
  say(`${origin}: ${first.slice(0, 120)}${money ? " — needs your answer" : ""}`);
}

function failReply(box, err, origin) {
  box.classList.remove("pending");
  box.removeAttribute("aria-busy");
  box.classList.add("error");
  setKids(box, el("div", { class: "origin" }, el("span", { text: origin })),
    el("pre", { class: "text", text: `⛔ ${err.message || err}` }));
  peek(`${origin} failed`);
  alarm(`${origin} failed: ${err.message || err}`);
}

async function act(origin, fn, btn) {
  if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
  const box = addReply(origin);
  BUSY++;
  try {
    const data = await fn();
    fillReply(box, data.reply, origin);
  } catch (e) {
    failReply(box, e, origin);
  } finally {
    BUSY--;
    if (btn && btn.isConnected && !btn.classList.contains("chosen")) {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
    refresh(true);
  }
}

const runCommand = (text, btn) => act(text, () => post("/api/run", { text }), btn);
// A reply is labelled with the button that was tapped, and the video it is
// about when the button does not say.
function callback(data, label, btn) {
  const ticker = data.split("|").find((p) => /^[A-Z0-9.\-]{1,15}$/.test(p) && /[A-Z]/.test(p)) || "";
  const named = ticker && label.includes(ticker);
  return act(named || !ticker ? label : `${label} · ${ticker}`, () => post("/api/callback", { data }), btn);
}

// ------------------------------------------------------------------- state
async function refresh(force = false) {
  if (document.hidden && STATE && !force) return;   // a background tab polls nothing
  let next;
  try {
    next = await api("/api/state");
  } catch (e) {
    return;
  }
  // Nothing changed: re-rendering would only drop keyboard focus.
  const raw = JSON.stringify(next);
  if (raw === LAST_RAW) return;
  LAST_RAW = raw;
  STATE = next;
  const f = document.activeElement;
  const zone = f?.closest?.("#inbox, #jobs, #videos, #summary")?.id;
  const cb = f?.dataset?.cb;
  const dk = f?.tagName === "SUMMARY" ? f.parentElement?.dataset?.key : null;
  renderHeader();
  renderSummary();
  renderInbox();
  renderJobs();
  renderVideos();
  const back = cb && zone
    ? document.querySelector(`#${zone} [data-cb="${CSS.escape(cb)}"]`)
    : dk ? document.querySelector(`#videos details[data-key="${CSS.escape(dk)}"] > summary`) : null;
  back?.focus({ preventScroll: true });
}

function renderHeader() {
  $("#status").hidden = false;
  const a = STATE.active;
  const act_ = $("#active");
  setKids(act_, el("span", { class: "k", text: "Active" }),
    el("b", { text: a ? a.ticker : "none" }),
    a ? el("span", { class: "date meta", text: a.workdate }) : null);
  act_.title = a ? `${a.ticker} · ${a.workdate} — open its card` : "No active video";
  act_.setAttribute("aria-label", a ? `Active video ${a.ticker} ${a.workdate}, open its card` : "No active video");
  act_.onclick = a ? () => openCard(`${a.ticker}@${a.workdate}`) : null;

  const s = STATE.spend;
  const sp = $("#spend");
  sp.classList.remove("hot", "bad");
  if (s.mtd === null) {
    setKids(sp, el("span", { class: "k", text: "Spend" }), "unreadable");
    sp.classList.add("bad");
    sp.setAttribute("aria-label", "Spend ledger unreadable");
  } else {
    const pct = s.cap ? Math.min(100, (s.mtd / s.cap) * 100) : 0;
    setKids(sp, el("span", { class: "k", text: "Spend" }), `$${s.mtd.toFixed(2)} / $${s.cap.toFixed(0)}`);
    sp.style.setProperty("--pct", `${pct}%`);
    if (pct >= 85) sp.classList.add("bad");
    else if (pct >= 60) sp.classList.add("hot");
    sp.setAttribute("aria-label", `Spent this month $${s.mtd.toFixed(2)} of $${s.cap.toFixed(2)} cap`);
  }

  const quiet = STATE.notify === "quiet";
  const nt = $("#notify");
  setKids(nt, quiet ? "🔕" : "🔔", el("span", { class: "lbl", text: quiet ? " quiet" : " all pushes" }));
  nt.setAttribute("aria-label", quiet ? "Pushes are quiet. Turn all pushes on" : "All pushes on. Switch to quiet");
  nt.onclick = (e) => runCommand(`/admin quiet ${quiet ? "off" : "on"}`, e.currentTarget);

  const mock = STATE.mock || "";
  $("#mock").hidden = !mock;
  const i = mock.indexOf(" — ");
  $("#mock-text").textContent = i >= 0 ? mock.slice(i + 3) : mock;
  $("#mock").title = mock;

  $("#queue-banner").hidden = !!STATE.queue_running;
  renderTarget();
}

// "Send to": which video a paste or an upload lands in, and the switch.
function renderTarget() {
  const sel = $("#target");
  const a = STATE.active;
  if (document.activeElement !== sel) {
    const opts = [el("option", { value: "", text: "— no active video —" })];
    for (const v of STATE.videos) {
      const lane = v.update ? "UPDATE" : (v.lane || "?").toUpperCase();
      opts.push(el("option", { value: v.key, text: `${v.ticker} · ${lane} · ${v.workdate}` }));
    }
    if (a && !STATE.videos.some((v) => v.ticker === a.ticker && v.workdate === a.workdate)) {
      opts.push(el("option", { value: `${a.ticker}@${a.workdate}`, text: `${a.ticker} · ${a.workdate}` }));
    }
    sel.replaceChildren(...opts);
    sel.value = a ? `${a.ticker}@${a.workdate}` : "";
  }
  sel.classList.toggle("none", !a);
  $("#send-paste").textContent = a ? `Send to ${a.ticker}` : "Send";
}
$("#target").addEventListener("change", (e) => {
  const key = e.target.value;
  if (!key) return;
  const [ticker, workdate] = key.split("@");
  setActive({ ticker, workdate });
});

// ----------------------------------------------------------------- summary
function renderSummary() {
  const items = STATE.inbox;
  const waiting = items.filter((i) => i.section !== "scheduled");
  const counts = {};
  waiting.forEach((i) => { counts[i.section] = (counts[i.section] || 0) + 1; });
  const hot = (counts.blocked || 0) + (counts.failed || 0);
  const detail = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(" · ") || "nothing to do";

  const jobs = STATE.jobs.filter((j) => j.status === "running" || j.status === "queued");
  const run = jobs.find((j) => j.status === "running");
  const prog = run && /(\d+)\s*\/\s*(\d+)/.exec(run.detail || "");
  const uploads = items.filter((i) => i.section === "upload");

  const s = STATE.spend;
  const pct = s.mtd === null || !s.cap ? 0 : Math.min(100, (s.mtd / s.cap) * 100);

  const tile = (key, label, value, sub, tone, onclick, meter) => el("button", {
    type: "button", class: `stat ${tone ? `tone-${tone}` : ""} ${value === 0 || value === "0" ? "zero" : ""}`,
    "data-cb": `stat:${key}`, onclick,
    "aria-label": `${label}: ${value}. ${sub}`,
  }, el("span", { class: "k", text: label }), el("b", { text: String(value) }), el("small", { text: sub }), meter);

  setKids($("#summary"),
    tile("waiting", "Waiting on you", waiting.length, detail,
      waiting.length ? (hot ? "bad" : "accent") : "", () => scrollTo($("#inbox"))),
    tile("rendering", "Rendering", jobs.length,
      run ? `${run.ticker} ${prog ? `${prog[1]}/${prog[2]}` : run.detail || "running"}` : (jobs.length ? "queued" : "queue idle"),
      jobs.length ? "warn" : "", () => scrollTo($("#jobs")),
      prog ? el("div", { class: "meter warn" }, el("i", { style: `width:${Math.round((prog[1] / prog[2]) * 100)}%` })) : null),
    tile("upload", "Ready to upload", uploads.length,
      uploads.map((u) => u.ticker).join(", ") || "nothing rendered and waiting",
      uploads.length ? "ok" : "", () => scrollTo($("#inbox .section-title[data-s=upload]") || $("#inbox"))),
    tile("spend", "Spend this month", s.mtd === null ? "—" : `$${s.mtd.toFixed(2)}`,
      s.mtd === null ? "ledger unreadable" : `of $${s.cap.toFixed(0)} cap`,
      s.mtd === null || pct >= 85 ? "bad" : pct >= 60 ? "money" : "",
      (e) => runCommand("/admin cost", e.currentTarget),
      el("div", { class: `meter ${pct >= 85 ? "bad" : pct >= 60 ? "warn" : ""}` }, el("i", { style: `width:${pct}%` }))));

  const hc = $("#home-count");
  hc.hidden = waiting.length === 0;
  hc.textContent = String(waiting.length);
  hc.setAttribute("aria-label", `${waiting.length} waiting`);
}

// ------------------------------------------------------------------- inbox
const SECTIONS = {
  failed: ["Failed", "var(--bad)"],
  blocked: ["Blocked — needs an edit", "var(--bad)"],
  approve: ["Waiting for your approval", "var(--accent)"],
  render: ["Approved, not rendered", "var(--money-line)"],
  upload: ["Rendered, not uploaded", "var(--ok)"],
  retention: ["Retention ready to read", "var(--muted)"],
  scheduled: ["Coming up — going public within 48 h", "var(--ok)"],
};
const SECTION_ORDER = Object.keys(SECTIONS);

const videoFor = (t, d) => STATE.videos.find((v) => v.ticker === t && v.workdate === d);

// The inbox's own button opens the card in the chat; here it opens the card
// on the Videos tab instead of posting a copy into Replies.
function cardLocal(b) {
  if (!b.data.startsWith("c|")) return false;
  const [, t, d] = b.data.split("|");
  openCard(`${t}@${d}`);
  return true;
}

function renderInbox() {
  const box = $("#inbox");
  const items = STATE.inbox.slice().sort((a, b) => SECTION_ORDER.indexOf(a.section) - SECTION_ORDER.indexOf(b.section));
  const waiting = items.filter((i) => i.section !== "scheduled").length;
  $("#inbox-count").textContent = waiting ? `${waiting} waiting` : "";
  if (!items.length) {
    setKids(box, empty("Inbox zero", "Nothing is waiting on you.", "ok", "✓"));
    return;
  }
  const out = [];
  let section = "";
  for (const it of items) {
    if (it.section !== section) {
      section = it.section;
      const [title, tone] = SECTIONS[section] || [section, "var(--muted)"];
      const n = items.filter((x) => x.section === section).length;
      out.push(el("div", { class: "section-title", "data-s": section, style: `--tone:${tone}` },
        el("span", { class: "dot", "aria-hidden": "true" }), title, el("span", { class: "count", text: String(n) })));
    }
    const v = it.workdate ? videoFor(it.ticker, it.workdate) : null;
    let rows = it.buttons;
    let next = true;
    if (v && it.action && v.next_action === it.action && v.buttons.length > 1) {
      rows = [v.buttons[0]];               // the card's own next step, priced
    } else if (it.section === "scheduled") {
      rows = [];
    }
    const date = notToday(it.workdate);
    out.push(el("div", { class: `item ${it.section === "scheduled" ? "info" : ""}` },
      el("div", { class: "what" },
        el("b", { text: it.ticker }), date ? el("span", { class: "meta", text: `  ${date}` }) : null,
        el("div", { class: "desc", text: it.text })),
      buttonsBlock(rows, {
        nextRow: next, sm: true, local: cardLocal,
        relabel: (b) => (b.data.startsWith("c|") ? "Open card" : b.text.replace(/^[A-Z0-9.\-]+:\s*/, "")),
      })));
  }
  setKids(box, out);
}

// -------------------------------------------------------------------- jobs
const JOB_RANK = { running: 0, queued: 1, failed: 2, interrupted: 3, cancelled: 4, done: 5 };

function renderJobs() {
  const box = $("#jobs");
  const jobs = STATE.jobs.slice().sort((a, b) =>
    (JOB_RANK[a.status] ?? 9) - (JOB_RANK[b.status] ?? 9) || String(b.updated_at).localeCompare(String(a.updated_at)));
  if (!jobs.length) {
    setKids(box, empty("The queue is idle", "Renders you start show up here with their progress."));
    return;
  }
  const live = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const rest = jobs.filter((j) => !live.includes(j));
  const shown = SHOW_ALL_JOBS ? jobs : live.concat(rest.slice(0, 5));
  const media = new Map();
  STATE.videos.forEach((v) => v.media.forEach((m) => media.set(`${v.ticker}@${v.workdate}/${m.name}`, m)));
  const rows = shown.map((j) => {
    const active = j.status === "running" || j.status === "queued";
    const prog = /(\d+)\s*\/\s*(\d+)/.exec(j.detail || "");
    const kind = j.kind.replace(/^render_/, "").replace(/_/g, " ");
    const date = notToday(j.workdate);
    const file = j.link ? j.link.split("/").pop() : "";
    const m = file && media.get(`${j.ticker}@${j.workdate}/${file}`);
    return el("div", { class: "job" },
      el("span", { class: `job-status ${j.status}`, text: j.status }),
      el("div", { class: "what" },
        el("div", {}, el("b", { text: j.ticker }), ` ${kind}`, date ? el("span", { class: "meta", text: `  ${date}` }) : null),
        prog ? el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": prog[2], "aria-valuenow": prog[1], "aria-label": `${j.ticker} ${kind}` },
          el("i", { style: `width:${Math.round((prog[1] / prog[2]) * 100)}%` })) : null,
        j.detail ? el("div", { class: "meta", text: j.detail }) : null,
        j.status === "failed" && j.error ? el("div", { class: "err", text: j.error }) : null,
        j.status === "done" && file ? el("div", { class: "meta", text: file }) : null),
      el("time", { datetime: j.updated_at, title: when(j.updated_at), text: ago(j.updated_at) }),
      active ? el("button", {
        type: "button", class: "danger sm", text: "Cancel", "data-cb": `j|${j.ticker}|${j.workdate}`,
        "aria-label": `Cancel ${j.ticker} ${kind}`,
        onclick: (e) => callback(`j|${j.ticker}|${j.workdate}`, `Cancel ${j.ticker}`, e.currentTarget),
      }) : m ? el("button", { type: "button", class: "ghost sm", text: "▶ Play", onclick: () => play(m) }) : el("span"));
  });
  if (rest.length > 5) {
    rows.push(el("div", { class: "more-row" }, el("button", {
      type: "button", class: "ghost sm",
      text: SHOW_ALL_JOBS ? "Show fewer" : `Show ${rest.length - 5} older`,
      onclick: () => { SHOW_ALL_JOBS = !SHOW_ALL_JOBS; renderJobs(); },
    })));
  }
  setKids(box, rows);
}

// ------------------------------------------------------------------ videos
// The same road on every card: done, you-are-here, not yet.
const NOW_STEP = { prompt: "script", angle: "angle", edit: "gates", approve: "approval", render: "final", upload: "upload" };

function stagesOf(v) {
  const steps = [];
  const add = (key, label, cls, aria) => steps.push(el("li", { class: `stage ${cls}`, "data-k": key, "aria-label": aria || label }, label));
  const now = NOW_STEP[v.next_action] || (!v.data_file ? "data" : "");
  const st = (key, done) => (done ? "ok" : key === now ? "now" : "");
  add("data", "data", st("data", !!v.data_file), `data ${v.data_file ? "done" : "to do"}`);
  if (v.lane === "long" && !v.update) add("angle", "angle", st("angle", !!v.angle || v.script));
  add("script", "script", st("script", v.script));
  if (v.report_ok === false) add("gates", `gates ${v.blocking}`, "bad", `gates blocked: ${v.blocking} finding(s)`);
  else add("gates", "gates", st("gates", v.report_ok === true));
  add("approval", "approved", st("approval", v.approved || !!v.renders.final));
  for (const k of ["draft", "proof"]) if (v.renders[k]) add(k, k, "ok");
  if (v.active_job) {
    add("run", `${v.active_job.kind.replace(/^render_/, "").replace(/_/g, " ")} · ${v.active_job.detail || v.active_job.status}`, "run",
      `running: ${v.active_job.detail || v.active_job.status}`);
  }
  add("final", "final", st("final", !!v.renders.final));
  const up = v.uploaded;
  add("upload", up && up.privacy === "scheduled" ? "scheduled" : "published", st("upload", !!up));
  return el("ol", { class: "stages", "aria-label": "Progress" }, steps);
}

const URGENCY = { edit: 0, approve: 1, angle: 2, prompt: 2, render: 3, upload: 4, retention: 5, "": 7 };
const urgency = (v) => (v.active_job ? 6 : URGENCY[v.next_action] ?? 7);

function renderVideos() {
  const filter = $("#video-filter").value.trim().toUpperCase();
  const box = $("#videos");
  const vids = STATE.videos
    .filter((v) => !filter || v.ticker.includes(filter))
    .sort((a, b) => urgency(a) - urgency(b) || String(b.workdate).localeCompare(String(a.workdate)));
  if (!vids.length) {
    setKids(box, empty(filter ? "No video matches" : "No videos in the last 14 days",
      filter ? `Nothing with “${filter}” in its ticker.` : "Start one on Home.", "", "·",
      filter ? null : el("button", { type: "button", class: "ghost sm", text: "Start one", onclick: () => { showTab("home"); $("#start-ticker").focus(); } })));
    return;
  }
  const a = STATE.active;
  // Keep open details open across refreshes.
  const open = new Set($$("details[open]", box).map((d) => d.dataset.key));
  setKids(box, vids.map((v) => {
    const isActive = a && a.ticker === v.ticker && a.workdate === v.workdate;
    const lane = v.update ? "update" : (v.lane || "no lane");
    // The tail row is Refresh (the page refreshes itself) plus Proof/Cancel.
    const nextRows = v.buttons.slice(0, -1);
    const tail = (v.buttons.at(-1) || []).filter((b) => !b.data.startsWith("c|"));
    return el("article", { class: `card video${isActive ? " is-active" : ""}`, "data-key": v.key, "aria-label": `${v.ticker} ${lane} ${v.workdate}` },
      el("div", { class: "video-head" },
        el("span", { class: "tk", text: v.ticker }),
        el("span", { class: "lane", text: lane }),
        el("span", { class: "date", text: v.workdate }),
        isActive
          ? el("span", { class: "active-badge", title: "Pastes and uploads land here", text: "Active" })
          : el("button", { type: "button", class: "ghost sm", text: "Make active", "data-cb": `active:${v.key}`,
            "aria-label": `Make ${v.ticker} ${v.workdate} the active video`, onclick: (e) => setActive(v, e.currentTarget) })),
      stagesOf(v),
      el("p", { class: "next-line" }, "Next: ", el("b", { text: v.next_step })),
      buttonsBlock(nextRows, { nextRow: !!v.next_action }),
      el("div", { class: "video-foot" },
        buttonsBlock([tail], { sm: true }),
        v.media.map((m) => (isImage(m.name)
          ? el("a", { href: m.url, target: "_blank", rel: "noopener", class: "thumb" }, el("img", { src: m.url, alt: `${v.ticker} ${m.name}`, loading: "lazy" }))
          : el("button", { type: "button", class: "sm", text: `▶ ${m.name}`, onclick: () => play(m) }))),
        el("details", { "data-key": v.key, open: open.has(v.key) },
          el("summary", { text: "Card text" }), el("pre", { class: "text", text: v.card_text }))));
  }));
}
$("#video-filter").addEventListener("input", () => STATE && renderVideos());

function openCard(key) {
  showTab("videos");
  const node = document.querySelector(`#videos [data-key="${CSS.escape(key)}"]`);
  if (!node) return;
  scrollTo(node);
  node.classList.remove("flash");
  void node.offsetWidth;
  node.classList.add("flash");
}

function setActive(v, btn) {
  act(`Work on ${v.ticker} ${v.workdate}`, () => post("/api/active", { ticker: v.ticker, workdate: v.workdate }), btn);
}

function play(m) {
  $("#player-title").textContent = m.name;
  $("#player").classList.remove("portrait");
  $("#player-video").src = m.url;
  $("#player").showModal();
}
$("#player-video").addEventListener("loadedmetadata", (e) =>
  $("#player").classList.toggle("portrait", e.target.videoHeight > e.target.videoWidth));
$("#player").addEventListener("click", (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.currentTarget.close();
});
$("#player").addEventListener("close", () => { $("#player-video").pause(); $("#player-video").removeAttribute("src"); });

// -------------------------------------------------------------------- home
$("#start-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target;
  const ticker = f.ticker.value.trim().toUpperCase();
  if (!ticker) return;
  runCommand(`/${f.lane.value} ${ticker}`, e.submitter);
  f.ticker.value = "";
});

$("#send-paste").addEventListener("click", (e) => {
  const text = $("#paste").value;
  if (!text.trim()) { $("#paste").focus(); return; }
  const who = STATE?.active ? ` → ${STATE.active.ticker}` : "";
  const label = text.length > 60 ? `Paste · ${text.length.toLocaleString()} chars${who}` : `“${text.trim()}”${who}`;
  $("#paste").readOnly = true;
  act(label, () => post("/api/text", { text }), e.currentTarget).then(() => {
    $("#paste").readOnly = false;
    if (!$("#replies .reply.error")) $("#paste").value = "";
  });
});

function upload(file) {
  const bar = $("#upload-progress");
  const who = STATE?.active ? ` → ${STATE.active.ticker}` : "";
  const origin = `Upload · ${file.name}${who}`;
  const box = addReply(origin);
  bar.hidden = false;
  bar.value = 0;
  $("#drop").setAttribute("aria-disabled", "true");
  BUSY++;
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/upload?name=${encodeURIComponent(file.name)}`);
  xhr.setRequestHeader("X-Panel-Key", KEY);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = e.loaded / e.total; };
  xhr.onloadend = () => {
    BUSY--;
    bar.hidden = true;
    $("#drop").removeAttribute("aria-disabled");
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch { /* empty */ }
    if (xhr.status === 200 && data.reply) fillReply(box, data.reply, origin);
    else failReply(box, new Error(data.error || `upload failed (${xhr.status})`), origin);
    refresh(true);
  };
  xhr.send(file);
}
$("#file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) upload(f); e.target.value = ""; });
const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });

// --------------------------------------------------------------- commands
function cmdQuery() {
  return $("#cmd-line").value.replace(/^\//, "").trim().toLowerCase();
}

function renderCommands() {
  const q = cmdQuery();
  const matches = (c) => !q || `${c.name} ${c.help} ${c.doc} ${c.aliases.join(" ")}`.toLowerCase().includes(q)
    || q.startsWith(c.name);
  const sizes = {};
  REGISTRY.commands.forEach((c) => { sizes[c.family] = (sizes[c.family] || 0) + 1; });
  const singles = REGISTRY.families.filter((f) => sizes[f.name] === 1);
  const groups = [{ name: "everyday", title: "Everyday", blurb: "", cmds: REGISTRY.commands.filter((c) => sizes[c.family] === 1) }]
    .concat(REGISTRY.families.filter((f) => sizes[f.name] > 1)
      .map((f) => ({ name: f.name, title: f.title, blurb: f.blurb, cmds: REGISTRY.commands.filter((c) => c.family === f.name) })));
  void singles;
  const out = [];
  const nav = [];
  for (const g of groups) {
    const cmds = g.cmds.filter(matches);
    if (!cmds.length) continue;
    nav.push(el("a", { href: `#fam-${g.name}`, onclick: (e) => { e.preventDefault(); scrollTo($(`#fam-${g.name}`)); } },
      g.name === "everyday" ? "everyday" : `/${g.name}`, el("small", { text: String(cmds.length) })));
    out.push(el("section", { class: "card family", id: `fam-${g.name}`, "aria-label": g.title },
      el("div", { class: "card-head" },
        el("h2", {}, g.name === "everyday" ? null : el("code", { class: "fam", text: `/${g.name}` }), g.title),
        g.blurb ? el("span", { class: "meta", text: g.blurb }) : null),
      cmds.map(commandRow)));
  }
  setKids($("#fam-nav"), nav);
  setKids($("#commands"), out.length ? out : [el("div", { class: "card" }, empty("No command matches", "Press Enter to run it anyway, exactly as typed."))]);
}

function commandRow(c) {
  const input = c.usage ? el("input", {
    placeholder: c.usage, autocomplete: "off", spellcheck: "false", "aria-label": `Arguments for /${c.name}`,
  }) : null;
  const run = (e) => {
    const args = input ? input.value.trim() : "";
    if (c.spends && !confirm(`/${c.name} spends money. Run it?`)) return;
    runCommand(`/${c.name}${args ? ` ${args}` : ""}`, e?.currentTarget || btn);
  };
  const btn = el("button", {
    type: "button", class: `${c.spends ? "money" : ""} sm run`, text: "Run",
    "aria-label": c.spends ? `Run /${c.name} (spends money)` : `Run /${c.name}`, onclick: run,
  });
  if (input) input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  const hint = c.ticker && c.ticker !== "optional" ? " The ticker defaults to the active video." : "";
  return el("div", { class: `cmd${c.usage ? "" : " noargs"}${c.spends ? " spends" : ""}`, "data-name": c.name },
    el("div", { class: "name" },
      el("code", { text: `/${c.name}`, title: "Put it on the command line", onclick: () => { $("#cmd-line").value = `/${c.name} `; $("#cmd-line").focus(); } }),
      c.spends ? el("span", { class: "tag-money", text: "spends" }) : null),
    el("div", { class: "help", title: c.doc }, c.help + hint,
      c.aliases.length ? el("span", { class: "aka", text: `was ${c.aliases.map((x) => `/${x}`).join(", ")}` }) : null),
    input ? el("div", { class: "args" }, input) : null,
    btn);
}

// One line both filters the list and runs: "/…" + Enter runs it exactly as
// in Telegram; plain words filter, and Enter moves into the first match.
function rowTargets() {
  return $$("#commands .cmd").map((r) => r.querySelector(".args input") || r.querySelector("button.run"));
}
$("#cmd-line").addEventListener("input", renderCommands);
$("#cmd-line").addEventListener("keydown", (e) => {
  const t = $("#cmd-line").value.trim();
  if (e.key === "Enter") {
    e.preventDefault();
    if (t.startsWith("/")) $("#cmd-run").click();
    else rowTargets()[0]?.focus();
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    rowTargets()[0]?.focus();
  } else if (e.key === "Escape") {
    $("#cmd-line").value = "";
    renderCommands();
  }
});
$("#commands").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const targets = rowTargets();
  const i = targets.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const j = e.key === "ArrowDown" ? Math.min(i + 1, targets.length - 1) : i - 1;
  (j < 0 ? $("#cmd-line") : targets[j]).focus();
});
$("#cmd-run").addEventListener("click", (e) => {
  const t = $("#cmd-line").value.trim();
  if (!t) { $("#cmd-line").focus(); return; }
  runCommand(t.startsWith("/") ? t : `/${t}`, e.currentTarget);
});

// -------------------------------------------------------------------- feed
const isPush = (ev) => ev.kind !== "reply";
function toneOf(text) {
  const t = (text || "").trimStart();
  if (/^(✅|📤|📅|📺|💾)/.test(t)) return "ok";
  if (/^(❌|⛔|💥)/.test(t)) return "bad";
  if (/^(⚠️|🎬|⏳|🚫)/.test(t)) return "warn";
  return "";
}
function dayLabel(ts) {
  const d = toDate(ts);
  const today = new Date();
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function feedItem(ev) {
  const [head, ...rest] = (ev.text || "").split("\n");
  const body = rest.join("\n").trim();
  const pre = body ? el("pre", { class: `text${body.split("\n").length > 5 ? " clip" : ""}`, text: body }) : null;
  const more = pre && pre.classList.contains("clip")
    ? el("button", { type: "button", class: "ghost sm", text: "More", onclick: (e) => { pre.classList.toggle("clip"); e.currentTarget.textContent = pre.classList.contains("clip") ? "More" : "Less"; } })
    : null;
  return el("div", { class: `feed-item tone-${toneOf(ev.text)}` },
    el("time", { title: when(ev.at), text: clock(ev.at) }),
    el("div", {},
      el("div", { class: "head" }, head || "(file)", ev.kind !== "notice" ? el("span", { class: "kind", text: ev.kind }) : null),
      pre, more,
      filesBlock(ev.files.map((p) => ({ path: p, name: p.split("/").pop() }))),
      buttonsBlock(ev.buttons, { once: true, sm: true, staleAfter: ev.at + MONEY_TTL_S })));
}

function renderFeed() {
  const shown = FEED.filter((ev) => FEED_FILTER === "all" || (FEED_FILTER === "pushes") === isPush(ev)).slice().reverse();
  if (!shown.length) {
    setKids($("#feed"), empty(FEED_FILTER === "replies" ? "No replies yet" : "Nothing pushed yet",
      "Renders finishing, failures and storyboards show up here as they happen."));
    return;
  }
  const out = [];
  let day = "";
  for (const ev of shown.slice(0, 300)) {
    const d = dayLabel(ev.at);
    if (d !== day) { day = d; out.push(el("div", { class: "day", text: d })); }
    out.push(feedItem(ev));
  }
  setKids($("#feed"), out);
}

function renderFeedFilter() {
  $$("#feed-filter button").forEach((b) => {
    b.setAttribute("aria-pressed", b.dataset.f === FEED_FILTER ? "true" : "false");
  });
}
$("#feed-filter").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-f]");
  if (!b) return;
  FEED_FILTER = b.dataset.f;
  writeStore(FEED_STORE, FEED_FILTER);
  renderFeedFilter();
  renderFeed();
});

async function pollFeed() {
  if (document.hidden) return;
  try {
    const data = await api(`/api/feed?since=${FEED_SEQ}`);
    if (data.events.length) {
      data.events.forEach((ev) => FEED.push(ev));
      if (FEED.length > 600) FEED = FEED.slice(-600);
      const pushes = data.events.filter(isPush).length;
      if (pushes && !$("#tab-activity").classList.contains("on")) { UNREAD += pushes; badge(); }
      renderFeed();
      if (BUSY === 0) refresh(true);
    }
    FEED_SEQ = data.seq;
  } catch { /* the next poll tries again */ }
}

boot();

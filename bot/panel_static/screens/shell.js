// The frame around every screen: the top bar's queue, theme and desktop
// alerts, the Ctrl+K finder, and Home's "next up" and "this week".
// Loaded after app.js and uses its helpers.

const THEME_STORE = "dennis.panel.theme";
const ALERT_STORE = "dennis.panel.alerts";
// Which workspace step each card action is.
const ACTION_STEP = { prompt: "write", angle: "angle", edit: "check", approve: "approve", render: "render", upload: "upload", retention: "live" };

// ------------------------------------------------------------------ theme
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  const b = $("#theme");
  const dark = t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
  b.textContent = dark ? "☾" : "☀";
  b.title = t ? `${t === "dark" ? "Dark" : "Light"}, chosen here. Click for ${t === "dark" ? "light" : "the computer's setting"}` : "Follows the computer. Click for dark";
  b.setAttribute("aria-label", b.title);
}
$("#theme").addEventListener("click", () => {
  const now = readStore(THEME_STORE);
  const next = !now ? "dark" : now === "dark" ? "light" : "";
  writeStore(THEME_STORE, next);
  applyTheme(next);
});
applyTheme(readStore(THEME_STORE));

// ---------------------------------------------------------- desktop alerts
// A render finishing or failing, or the bot needing him, while the page is
// in another tab or behind another window.
const ALERT_RE = /(✅|❌|⛔|needs you|failed|done|is up|went public|🎬)/;
function alertsOn() { return readStore(ALERT_STORE) === "1" && "Notification" in window && Notification.permission === "granted"; }
function renderAlerts() {
  const b = $("#alerts");
  const on = alertsOn();
  setKids(b, "🖥", el("span", { class: "lbl", text: on ? " alerts on" : " alerts off" }));
  b.classList.toggle("off", !on);
  b.title = !("Notification" in window) ? "This browser cannot show desktop alerts"
    : on ? "Desktop alerts on: a finished or failed render, or the bot needing you. Click to stop"
      : "Desktop alerts off. Click to get one when a render finishes or the bot needs you";
  b.setAttribute("aria-label", b.title);
}
$("#alerts").addEventListener("click", async () => {
  if (!("Notification" in window)) return;
  if (alertsOn()) { writeStore(ALERT_STORE, ""); renderAlerts(); return; }
  const p = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  writeStore(ALERT_STORE, p === "granted" ? "1" : "");
  renderAlerts();
});
function alertPushes(events) {
  if (!alertsOn() || !document.hidden) return;
  events.filter((ev) => ALERT_RE.test(ev.text || "")).slice(-3).forEach((ev) => {
    const [title, ...rest] = (ev.text || "").split("\n");
    try { new Notification(title.slice(0, 80) || "Dennis", { body: rest.join(" ").slice(0, 160), tag: `dennis-${ev.seq || ev.at}` }); } catch { /* blocked */ }
  });
}
renderAlerts();

// ------------------------------------------------------------ the top bar
function renderShell() {
  $("#search").hidden = false;
  const run = (STATE.jobs || []).find((j) => j.status === "running") || (STATE.jobs || []).find((j) => j.status === "queued");
  const q = $("#queue-pill");
  q.hidden = !run;
  if (!run) return;
  const p = run.progress || {};
  const waiting = (STATE.jobs || []).filter((j) => j.status === "queued").length - (run.status === "queued" ? 1 : 0);
  setKids(q, el("span", { class: "k", text: run.status === "running" ? "Rendering" : "Queued" }),
    el("b", { text: run.ticker }),
    run.status === "running" ? el("span", { class: "meta", text: ` ${Math.round(p.pct || 0)}%${p.eta_s != null ? ` · ${dur(p.eta_s)} left` : ""}` }) : null,
    waiting > 0 ? el("span", { class: "meta", text: ` +${waiting}` }) : null);
  q.style.setProperty("--pct", `${p.pct || 0}%`);
  q.title = `${run.kind} ${run.ticker} — ${run.detail || run.status}. Click to open it`;
  q.onclick = () => openVideo(run.ticker, run.workdate, "render");
}

// ------------------------------------------------------------- next up
function renderNextUp() {
  const box = $("#next-up");
  const vids = (STATE.videos || []).filter((v) => !v.active_job && v.next_action && ACTION_STEP[v.next_action]);
  vids.sort((a, b) => urgency(a) - urgency(b) || String(b.workdate).localeCompare(String(a.workdate)));
  const v = vids[0];
  if (!v) { setKids(box); box.hidden = true; return; }
  box.hidden = false;
  const step = ACTION_STEP[v.next_action];
  const more = vids.length - 1;
  setKids(box,
    el("div", { class: "what" }, el("span", { class: "k", text: "Next up" }),
      el("b", { text: `${v.ticker} · ${v.next_step}` }),
      el("span", { class: "meta", text: `${v.update ? "update" : v.lane} · ${v.workdate}${more > 0 ? ` · ${more} more waiting` : ""}` })),
    el("button", { type: "button", class: "primary big", text: "Open it →", "data-cb": `next:${v.key}`, title: "Opens the video at this step",
      onclick: () => openVideo(v.ticker, v.workdate, step) }));
}

// ------------------------------------------------------------ this week
function renderWeek() {
  const box = $("#week");
  const rows = STATE.week || [];
  if (!rows.length) { setKids(box, empty("Nothing out this week", "Nothing went out in the last seven days, and nothing is scheduled for the next seven.", "", "·")); return; }
  const today = STATE.today;
  setKids(box, rows.map((r) => {
    const day = (r.when || "").slice(0, 10);
    const t = new Date(r.when);
    const label = isNaN(t) ? day : t.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return el("div", { class: `item${day >= today ? "" : " info"}` },
      el("div", { class: "what" }, el("b", { text: r.ticker }), el("span", { class: "meta", text: `  ${r.fmt} · ${r.pending ? "scheduled" : r.privacy}` }),
        el("div", { class: "desc" }, el("a", { href: r.url, target: "_blank", rel: "noopener", text: r.title || r.url }))),
      el("time", { class: "meta", text: label }),
      r.workdate ? el("button", { type: "button", class: "ghost sm", text: "Open", onclick: () => openVideo(r.ticker, r.workdate, "live") }) : null);
  }));
}

// ------------------------------------------------- the finder (Ctrl+K)
const SCREENS = [["home", "Home"], ["videos", "Videos"], ["ideas", "Ideas"], ["calendar", "Calendar"], ["stats", "Stats"], ["library", "Library"], ["settings", "Settings"], ["activity", "Activity"], ["commands", "Commands"]];
let PAL = [];
let PAL_I = 0;
function paletteItems(q) {
  q = q.trim().toLowerCase().replace(/^\//, "");
  const out = [];
  SCREENS.forEach(([id, name]) => out.push({ kind: "screen", label: name, sub: "screen", go: () => showTab(id, true) }));
  (STATE?.videos || []).forEach((v) => out.push({ kind: "video", label: `${v.ticker} · ${v.update ? "update" : v.lane || "?"} · ${v.workdate}`, sub: v.next_step,
    go: () => openVideo(v.ticker, v.workdate) }));
  (REGISTRY?.commands || []).forEach((c) => out.push({ kind: "command", label: `/${c.name}${c.usage ? " " + c.usage : ""}`, sub: c.help, cmd: c,
    go: () => {
      // Words it cannot run without: type them, then Enter runs it.
      const needs = !!c.usage && !c.usage.startsWith("[");
      if (needs) { $("#palette-input").value = `/${c.name} `; renderPalette(); return false; }
      runCommand(`/${c.name}`);
    } }));
  (window.EXTRA_FINDS || []).forEach((f) => out.push(f));
  if (!q) return out.filter((i) => i.kind !== "command").slice(0, 30);
  const words = q.split(/\s+/);
  const scored = out.map((i) => {
    const hay = `${i.label} ${i.sub || ""}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) return null;
    const head = i.label.toLowerCase().replace(/^\//, "");
    return [head.startsWith(q) ? 0 : head.includes(words[0]) ? 1 : 2, i];
  }).filter(Boolean).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
  // A typed command with its arguments runs as typed.
  const text = $("#palette-input").value.trim();
  if (text.startsWith("/") && /\s\S/.test(text)) {
    scored.unshift({ kind: "run", label: `Run ${text}`, sub: "Enter runs it as typed", go: () => runCommand(text) });
  } else if (text) {
    // Anything else can be asked: first when it reads like a question.
    const ask = { kind: "ask", label: `Ask: ${text}`, sub: "the local AI answers on Home", go: () => { showTab("home", true); askBot(text); } };
    if (/\?$/.test(text) || text.split(/\s+/).length >= 3) scored.unshift(ask); else scored.push(ask);
  }
  return scored.slice(0, 40);
}

// ------------------------------------------------- ask the bot
async function askBot(q) {
  q = (q || "").trim();
  if (!q) return;
  const box = $("#ask-answer"), btn = $("#ask-form button");
  $("#ask-q").value = q;
  box.hidden = false;
  setKids(box, [el("p", { class: "meta", text: "Reading the records and the bot's state. The local AI can take a minute." })]);
  btn.disabled = true;
  try {
    const r = await post("/api/ask", { question: q });
    setKids(box, [el("p", { class: "ask-q", text: `You asked: ${q}` }),
      el("pre", { class: "ask-text", text: r.reply?.text || "No answer came back." })]);
  } catch (e) {
    setKids(box, [el("p", { class: "bad", text: String(e.message || e) })]);
  } finally {
    btn.disabled = false;
  }
}
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); askBot($("#ask-q").value); });
function renderPalette() {
  PAL = paletteItems($("#palette-input").value);
  PAL_I = Math.min(PAL_I, Math.max(PAL.length - 1, 0));
  setKids($("#palette-list"), PAL.length ? PAL.map((i, n) => el("li", {
    role: "option", class: `pal ${i.kind}${n === PAL_I ? " on" : ""}`, "aria-selected": n === PAL_I ? "true" : "false",
    onmousemove: () => { if (PAL_I !== n) { PAL_I = n; renderPalette(); } },
    onclick: () => choose(n),
  }, el("span", { class: "kind", text: i.kind }), el("b", { text: i.label }), i.sub ? el("small", { text: i.sub }) : null))
    : [el("li", { class: "pal none", text: "Nothing matches. A command with its words runs as typed." })]);
  $("#palette-list .on")?.scrollIntoView({ block: "nearest" });
}
function choose(n) {
  const item = PAL[n];
  if (!item) return;
  const keep = item.go() === false;
  if (!keep) $("#palette").close();
  else $("#palette-input").focus();
}
function openPalette() {
  if ($("#app").hidden) return;
  $("#palette-input").value = "";
  PAL_I = 0;
  renderPalette();
  $("#palette").showModal();
  $("#palette-input").focus();
}
$("#search").addEventListener("click", openPalette);
$("#palette-input").addEventListener("input", () => { PAL_I = 0; renderPalette(); });
$("#palette-input").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); PAL_I = Math.min(PAL_I + 1, PAL.length - 1); renderPalette(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); PAL_I = Math.max(PAL_I - 1, 0); renderPalette(); }
  else if (e.key === "Enter") { e.preventDefault(); choose(PAL_I); }
});
$("#palette").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
});

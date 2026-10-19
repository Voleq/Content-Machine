// Ideas, Calendar and Stats: the screens that are not one video. Each reads
// its own endpoint (bot/panel_pages) when it opens and acts through the
// bot's commands. Loaded after app.js and uses its helpers.

const SCREEN_LOAD = {};
const pageRun = (text, btn, label) => act(label || text, () => post("/api/run", { text }), btn);
const reload = (name) => () => SCREEN_LOAD[name]?.();
function card(title, meta, ...kids) {
  return el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", { text: title }), meta ? el("span", { class: "meta", text: meta }) : null), ...kids);
}
function table(head, rows) {
  return el("div", { class: "table-wrap" }, el("table", { class: "tbl" },
    el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows)));
}
const pct = (x) => (x == null ? "–" : `${(x * 100).toFixed(1)}%`);
function sectionError(d) { return d && d.error ? el("div", { class: "banner bad", text: `Could not be read: ${d.error}` }) : null; }

// Horizontal bars, one per row; values are shares (0..1) unless `fmt` says.
function bars(rows, { label, value, fmt = pct, max = null, signed = false, note = null }) {
  if (!rows.length) return null;
  const vals = rows.map(value);
  const top = max ?? Math.max(...vals.map((v) => Math.abs(v)), 0.0001);
  return el("div", { class: `bars${signed ? " signed" : ""}` }, rows.map((r, i) => {
    const v = vals[i];
    const w = Math.min(100, (Math.abs(v) / top) * (signed ? 50 : 100));
    return el("div", { class: "bar-row", title: note ? note(r) : "" },
      el("span", { class: "bar-label", text: label(r) }),
      el("span", { class: "bar-track" }, el("i", { class: v < 0 ? "neg" : "", style: signed
        ? `width:${w}%;${v < 0 ? `right:50%` : `left:50%`}` : `width:${w}%` })),
      el("span", { class: "bar-val", text: fmt(v) }));
  }));
}
const textReport = (text) => (text ? el("details", { class: "report" }, el("summary", { text: "The text report" }), el("pre", { class: "text", text })) : null);

// ------------------------------------------------------------------ Ideas
SCREEN_LOAD.ideas = async () => {
  const box = $("#ideas-screen");
  let d;
  try { d = await api("/api/ideas"); } catch (e) { setKids(box, empty("Could not load ideas", e.message, "bad", "!")); return; }
  const start = (t, lane) => el("button", { type: "button", class: "sm next", text: `Start ${lane.toUpperCase()}`, title: `Open ${t} as a ${lane}`,
    onclick: (e) => pageRun(`/new ${lane} ${t}`, e.currentTarget, `Start ${t} ${lane}`) });
  // Backlog
  const add = el("form", { class: "row inline-form" },
    el("input", { name: "t", placeholder: "TICKER", class: "ticker", required: true, autocomplete: "off", size: 8 }),
    el("input", { name: "why", placeholder: "why this one", class: "grow", required: true }),
    el("button", { type: "submit", class: "primary sm", text: "Add idea" }));
  add.addEventListener("submit", (e) => { e.preventDefault(); const f = e.target; pageRun(`/ideas add ${f.t.value.trim().toUpperCase()} ${f.why.value.trim()}`, e.submitter).then(reload("ideas")); });
  const backlog = Array.isArray(d.backlog) ? d.backlog : [];
  const backlogCard = card("Backlog", `${backlog.length} ranked`, sectionError(d.backlog), add,
    backlog.length ? table(["Ticker", "Why", "From", "Score", ""], backlog.map((i) => el("tr", {},
      el("td", {}, el("b", { text: i.ticker }), i.lane ? el("span", { class: "meta", text: ` ${i.lane}` }) : null),
      el("td", { text: i.reason }), el("td", { class: "meta", text: i.source }), el("td", { class: "num", text: i.score.toFixed(1) }),
      el("td", { class: "acts" }, start(i.ticker, i.lane || "short"), i.lane ? null : start(i.ticker, "long"),
        el("button", { type: "button", class: "ghost sm", text: "Drop", onclick: async (e) => {
          const b = e.currentTarget;
          if (await askConfirm(`Drop ${i.ticker}?`, "It leaves the backlog; a later screen can bring it back.", "Drop")) pageRun(`/ideas drop ${i.ticker}`, b).then(reload("ideas"));
        } })))))
      : empty("The backlog is empty", "Screens and moving theses fill it; add one by hand above.", "", "·"));
  // Last screen
  const sc = d.screen && !d.screen.error ? d.screen : { rows: [] };
  const when = sc.ts ? ago(sc.ts) : "never run";
  const screenCard = card("Last screen", when, sectionError(d.screen),
    el("div", { class: "row" }, el("button", { type: "button", class: "sm", text: "Run the screener", title: "Trending names for SHORTs, value names for LONGs. Takes a minute or two",
      onclick: (e) => pageRun("/ideas screen all", e.currentTarget, "Screener").then(reload("ideas")) })),
    sc.rows.length ? table(["Ticker", "Lane", "Move", "Price", "Why", ""], sc.rows.map((r) => el("tr", {},
      el("td", {}, el("b", { text: r.ticker })), el("td", { text: r.lane }),
      el("td", { class: `num ${r.pct_change > 0 ? "up" : r.pct_change < 0 ? "down" : ""}`, text: r.pct_change == null ? "–" : `${r.pct_change > 0 ? "+" : ""}${r.pct_change.toFixed(1)}%` }),
      el("td", { class: "num", text: r.price == null ? "–" : `$${Number(r.price).toFixed(2)}` }),
      el("td", { class: "meta", text: (r.reasons || []).join(" · ") }),
      el("td", { class: "acts" }, start(r.ticker, r.lane === "value" ? "long" : "short"),
        el("button", { type: "button", class: "ghost sm", text: "To backlog", onclick: (e) => pageRun(`/ideas add ${r.ticker} ${(r.reasons || []).join("; ") || "from the screen"}`, e.currentTarget).then(reload("ideas")) })))))
      : empty("No screen on file", "Run the screener to see this morning's candidates.", "", "·"));
  // Watch and earnings
  const watch = Array.isArray(d.watch) ? d.watch : [];
  const wForm = el("form", { class: "row inline-form" }, el("input", { name: "t", placeholder: "TICKER", class: "ticker", required: true, size: 8 }),
    el("button", { type: "submit", class: "sm", text: "Watch" }));
  wForm.addEventListener("submit", (e) => { e.preventDefault(); pageRun(`/ideas watch ${e.target.t.value.trim().toUpperCase()}`, e.submitter).then(reload("ideas")); });
  const watchCard = card("Watch list", "intraday moves; published names join by themselves", sectionError(d.watch),
    el("div", { class: "chips" }, watch.map((t) => el("span", { class: "chip" }, t,
      el("button", { type: "button", class: "ghost sm", text: "✕", "aria-label": `Stop watching ${t}`, title: "Stop watching (a name with a thesis stays on)",
        onclick: (e) => pageRun(`/ideas watch drop ${t}`, e.currentTarget).then(reload("ideas")) })))), wForm);
  const earn = Array.isArray(d.earnings) ? d.earnings : [];
  const eForm = el("form", { class: "row inline-form" }, el("input", { name: "t", placeholder: "TICKER", class: "ticker", required: true, size: 8 }),
    el("input", { name: "d", type: "date", required: true }),
    el("select", { name: "w" }, [["", "time?"], ["bmo", "before the open"], ["amc", "after the close"]].map(([v, t]) => el("option", { value: v, text: t }))),
    el("button", { type: "submit", class: "sm", text: "Add the date" }));
  eForm.addEventListener("submit", (e) => { e.preventDefault(); const f = e.target; pageRun(`/ideas earnings ${f.t.value.trim().toUpperCase()} ${f.d.value} ${f.w.value}`.trim(), e.submitter).then(reload("ideas")); });
  const earnCard = card("Earnings dates", "the bot flags both sides of a print", sectionError(d.earnings),
    earn.length ? table(["Date", "Ticker", "When"], earn.map((r) => el("tr", {}, el("td", { text: r.date }), el("td", {}, el("b", { text: r.ticker })), el("td", { class: "meta", text: r.when || "" })))) : null, eForm);
  setKids(box, el("div", { class: "page-head" }, el("h2", { text: "Ideas" })),
    el("div", { class: "grid" }, el("div", { class: "span2" }, backlogCard), el("div", { class: "span2" }, screenCard), watchCard, earnCard));
};

// --------------------------------------------------------------- Calendar
let CAL_MONTH = "";
SCREEN_LOAD.calendar = async () => {
  const box = $("#calendar-screen");
  let d;
  try { d = await api(`/api/calendar?m=${encodeURIComponent(CAL_MONTH)}`); } catch (e) { setKids(box, empty("Could not load the calendar", e.message, "bad", "!")); return; }
  CAL_MONTH = d.month;
  const go = (m) => { CAL_MONTH = m; SCREEN_LOAD.calendar(); };
  const head = el("div", { class: "page-head" },
    el("h2", {}, d.title, el("span", { class: "meta", text: `times in ${d.timezone}` })),
    el("div", { class: "row" }, el("button", { type: "button", class: "sm", text: "←", "aria-label": "Previous month", onclick: () => go(d.prev) }),
      el("button", { type: "button", class: "sm", text: "Today", onclick: () => go("") }),
      el("button", { type: "button", class: "sm", text: "→", "aria-label": "Next month", onclick: () => go(d.next) })));
  const names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const cells = [];
  for (let i = 0; i < (d.days[0]?.weekday || 0); i++) cells.push(el("div", { class: "cal-cell blank" }));
  d.days.forEach((day) => {
    const isToday = day.date === d.today;
    cells.push(el("div", { class: `cal-cell${day.past ? " past" : ""}${day.gap ? " gap" : ""}${isToday ? " today" : ""}` },
      el("div", { class: "cal-date" }, el("b", { text: String(Number(day.date.slice(8))) }), day.gap ? el("span", { class: "free", text: "nothing out" }) : null),
      day.items.map((it) => el("a", { class: `cal-item ${it.fmt}${it.pending ? " pending" : ""}`, href: it.url, target: "_blank", rel: "noopener",
        title: `${it.title} — ${it.pending ? "scheduled" : it.privacy} ${it.time}` }, el("b", { text: it.ticker }), el("span", { text: `${it.time} · ${it.fmt}${it.pending ? " · scheduled" : ""}` }))),
      day.gap && d.ready.length ? el("button", { type: "button", class: "ghost sm", text: "+ schedule", title: "Schedule a finished video for this day",
        onclick: (e) => scheduleOn(day.date, d, e.currentTarget) }) : null));
  });
  const gaps = d.days.filter((x) => x.gap).length;
  setKids(box, head,
    el("p", { class: "meta", text: `${gaps} day${gaps === 1 ? "" : "s"} left this month with nothing going out. ${d.ready.length ? `${d.ready.length} finished video${d.ready.length === 1 ? "" : "s"} not uploaded yet.` : "No finished video is waiting for a slot."}` }),
    sectionError(d),
    el("div", { class: "cal" }, names.map((n) => el("div", { class: "cal-head", text: n })), cells));
};
async function scheduleOn(day, d, btn) {
  const dlg = $("#schedule");
  const pick = $("#schedule-video");
  pick.replaceChildren(...d.ready.map((r) => el("option", { value: `${r.ticker}@${r.workdate}|${r.fmt}`, text: `${r.ticker} · ${r.fmt} · rendered ${r.workdate}` })));
  $("#schedule-day").textContent = day;
  $("#schedule-time").value = `${String(d.publish_hour).padStart(2, "0")}:00`;
  dlg.returnValue = "";
  dlg.showModal();
  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "ok") return;
    const [key, fmt] = pick.value.split("|");
    const when = `${day} ${$("#schedule-time").value}`;
    if (await askConfirm("Upload it to YouTube?", `${key.split("@")[0]} ${fmt} goes up private now and turns public on ${when} (${d.timezone}).`, "Schedule it")) {
      pageRun(`/publish ${key} ${fmt} ${when}`, btn, `Schedule ${key.split("@")[0]} · ${when}`).then(reload("calendar"));
    }
  }, { once: true });
}

// ------------------------------------------------------------------ Stats
SCREEN_LOAD.stats = async () => {
  const box = $("#stats-screen");
  setKids(box, el("p", { class: "meta", text: "Reading the evidence…" }));
  let d;
  try { d = await api("/api/stats"); } catch (e) { setKids(box, empty("Could not load the stats", e.message, "bad", "!")); return; }
  const none = (what) => el("p", { class: "meta", text: `No ${what} yet.` });
  const hooks = ["short", "long"].map((fmt) => {
    const h = d.hooks?.[fmt] || { rows: [] };
    return card(`Openers that held (${fmt})`, "the share still watching after the opening seconds", sectionError(d.hooks),
      bars(h.rows.slice(0, 12), { label: (r) => r.ticker, value: (r) => r.hold, note: (r) => r.text }) || none("openers with retention"), h.rows.length ? textReport(h.text) : null);
  });
  const rules = d.rules?.rows || [];
  const run = d.runtime?.rows || [];
  const chap = d.chapters?.rows || [];
  const exps = d.experiments?.rows || [];
  const sb = d.scoreboard && !d.scoreboard.error ? d.scoreboard : null;
  const anything = ["short", "long"].some((f) => d.hooks?.[f]?.rows?.length) || rules.length || run.length || chap.length || exps.length;
  setKids(box, el("div", { class: "page-head" }, el("h2", { text: "Stats" })),
    anything ? null : el("div", { class: "banner", text: "Nothing has retention yet. YouTube sends it about 48 hours after a video goes public, and these fill in as it does." }),
    el("div", { class: "grid" },
      ...hooks,
      card("The writing rules, against the videos", "points of hold with the feature minus without", sectionError(d.rules),
        bars(rules, { label: (r) => r.rule, value: (r) => r.points, fmt: (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`, signed: true, note: (r) => `${r.verdict} (n=${r.n_with}/${r.n_without})` }) || none("rule evidence"),
        rules.length ? textReport(d.rules?.text) : null),
      card("Length and hold", "mean hold by runtime", sectionError(d.runtime),
        bars(run, { label: (r) => `${r.label} (${r.videos})`, value: (r) => r.mean_hold }) || none("runtime evidence"), run.length ? textReport(d.runtime?.text) : null),
      card("Chapter types", "average share watched, weakest first", sectionError(d.chapters),
        bars(chap, { label: (r) => `${r.type} (${r.videos})`, value: (r) => r.avg_watch_ratio, note: (r) => (r.titles || []).slice(0, 4).join(" · ") }) || none("chapters with retention")),
      card("Clip experiments", "two clips off one long", sectionError(d.experiments),
        exps.length ? table(["Pair", "Clips", "Better"], exps.map((x) => el("tr", {}, el("td", { text: x.pair }),
          el("td", {}, x.arms.map((a) => el("div", { text: `${a.start_s.toFixed(0)}s · ${a.hold == null ? "no views yet" : pct(a.hold)} · ${a.title}` }))),
          el("td", { text: x.winner || "–" })))) : none("experiments"), exps.length ? textReport(d.experiments?.text) : null),
      el("div", { class: "span2" }, card("Calls scoreboard", sb ? sb.quarter : "", sectionError(d.scoreboard),
        sb ? el("p", { text: sb.headline }) : null,
        sb && sb.rows.length ? table(["Ticker", "Date", "Status", "What"], sb.rows.map((r) => el("tr", {},
          el("td", {}, el("b", { text: r.ticker })), el("td", { class: "meta", text: r.workdate }), el("td", { text: r.verdict || r.status }), el("td", { text: r.summary })))) : null,
        sb && sb.rows.length ? textReport(sb.text) : null))));
};

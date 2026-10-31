// Chat: the local AI, as a conversation, with every conversation kept.
// His ask (30 Oct 2026): "the ai still doesn't answer on the website, there's
// nowhere to find the answer, maybe just make it an llm chat with history".
// The bot keeps the conversations and answers on its own thread, one
// question at a time (bot/chat.py); this page asks, then looks again every
// second while the answer is written, so a reload, a closed tab or a restart
// of the page loses nothing. Loaded after app.js, guide.js and pages.js.

const CHAT_STORE = "dennis.panel.chat";
const CHAT_POLL_MS = 1000;
const CHAT_LIST_MS = 5000;
const CHAT_PENDING = ["queued", "waiting", "thinking"];
const CHAT_IDEAS = [
  "What's waiting on me right now?",
  "Why did the last render fail?",
  "Which memes do we have, and which are used least?",
  "What did we say about margins in the last video?",
];
let CHATS = null;                 // the list, newest first (null until read)
let CHAT = null;                  // the conversation on screen
let CHAT_ID = readStore(CHAT_STORE);
let CHAT_LIST_AT = 0;
let CHAT_SEQ = 0;                 // a conversation opened later wins over one still loading
const CHAT_DONE = new Set();      // answers already announced
const chatPending = (c) => (c?.messages || []).some((m) => CHAT_PENDING.includes(m.status));
const chatOpen = () => !$("#tab-chat").hidden;
const secs = (s) => (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`);

// ------------------------------------------------------------- markdown
// What the model writes, drawn without innerHTML: paragraphs, lists,
// headings, **bold**, *italic*, `code`, code blocks and the [n] that name a
// record it read (a hover says which).
function md(text, cites = {}) {
  const frag = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let list = null, para = [];
  const flushPara = () => { if (para.length) { frag.append(el("p", {}, inline(para.join(" "), cites))); para = []; } };
  const flushList = () => { if (list) { frag.append(list); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flushPara(); flushList();
      const code = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      frag.append(el("pre", { class: "md-code", text: code.join("\n") }));
      continue;
    }
    const bullet = /^\s*(?:[-*•])\s+(.*)$/.exec(line);
    const num = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    const head = /^\s*#{1,4}\s+(.*)$/.exec(line);
    if (bullet || num) {
      flushPara();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) { flushList(); list = el(tag, num && num[1] !== "1" ? { start: num[1] } : {}); }
      list.append(el("li", {}, inline(bullet ? bullet[1] : num[2], cites)));
    } else if (head) {
      flushPara(); flushList();
      frag.append(el("h4", {}, inline(head[1], cites)));
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else if (list && /^\s{2,}\S/.test(line)) {
      list.lastElementChild.append(" ", inline(line.trim(), cites));
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara(); flushList();
  return frag;
}
function inline(text, cites) {
  const out = [];
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\s][^*\n]*\*|\[\d+(?:\s*[,–-]\s*\d+)*\])/g;
  let at = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > at) out.push(text.slice(at, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(el("strong", { text: t.slice(2, -2) }));
    else if (t.startsWith("`")) out.push(el("code", { text: t.slice(1, -1) }));
    else if (t.startsWith("*")) out.push(el("em", { text: t.slice(1, -1) }));
    else {
      const ns = t.slice(1, -1).split(/\s*[,–-]\s*/);
      out.push(el("sup", { class: "cite", text: t, title: ns.map((n) => cites[n] ? `[${n}] ${cites[n]}` : "").filter(Boolean).join("\n") || null }));
    }
    at = m.index + t.length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

// ------------------------------------------------------------- the list
async function loadChats() {
  try { CHATS = (await api("/api/chats")).chats || []; } catch { return; }
  CHAT_LIST_AT = Date.now();
  announce();
  renderChatList();
  renderChatBadge();
  renderHomeChats();
}
// An answer that came while he was elsewhere: a dot on Chat, and a desktop
// alert when the page is in the background and alerts are on.
function announce() {
  (CHATS || []).forEach((c) => {
    if (!c.unread || CHAT_DONE.has(c.id + c.updated)) return;
    CHAT_DONE.add(c.id + c.updated);
    if (typeof alertsOn === "function" && alertsOn() && document.hidden) {
      try { new Notification("Dennis answered", { body: c.title, tag: `dennis-chat-${c.id}` }); } catch { /* blocked */ }
    }
  });
}
function renderChatBadge() {
  const b = $("#chat-count");
  const unread = (CHATS || []).filter((c) => c.unread && c.id !== (chatOpen() ? CHAT_ID : "")).length;
  const busy = (CHATS || []).some((c) => c.pending);
  b.hidden = !unread && !busy;
  b.textContent = unread ? String(unread) : "…";
  b.classList.toggle("soft", !unread);
  b.setAttribute("aria-label", unread ? `${unread} new answer${unread === 1 ? "" : "s"}` : "an answer is being written");
}
const PENDING_WORDS = { thinking: "answering…", queued: "in line", waiting: "waits for the render" };
function renderChatList() {
  const box = $("#chat-list");
  if (!box) return;
  const rows = CHATS || [];
  $("#chat-list-count").textContent = rows.length ? String(rows.length) : "";
  if (!rows.length) { setKids(box, el("li", { class: "chat-none meta", text: "No conversations yet. Ask something and it is kept here." })); return; }
  setKids(box, rows.map((c) => el("li", {},
    el("button", { type: "button", class: `chat-item${c.id === CHAT_ID ? " on" : ""}${c.unread && c.id !== CHAT_ID ? " unread" : ""}`,
      "aria-current": c.id === CHAT_ID ? "true" : null, onclick: () => openChat(c.id) },
    el("span", { class: "chat-item-title", text: c.title }),
    el("span", { class: "chat-item-sub" },
      c.pending ? el("span", { class: "chat-busy", text: PENDING_WORDS[c.pending] || "answering…" }) : null,
      el("span", { text: c.pending ? "" : c.last || "" }),
      el("time", { text: ago(c.updated) }))))));
}

// --------------------------------------------------- one conversation
async function openChat(id, { quiet = false } = {}) {
  const seq = ++CHAT_SEQ;
  let c = null;
  try { c = (await api(`/api/chat?id=${encodeURIComponent(id)}`)).chat; } catch (e) { if (!quiet) say(`Could not open it: ${e.message}`); return; }
  if (seq !== CHAT_SEQ) return;
  if (!c) { newChat({ quiet }); return; }
  CHAT = c;
  CHAT_ID = c.id;
  writeStore(CHAT_STORE, c.id);
  renderChat(true);
  renderChatList();
  pollChat();
  if (!quiet) $("#chat-q").focus();
}
function newChat({ quiet = false } = {}) {
  CHAT_SEQ++;
  CHAT = null;
  CHAT_ID = "";
  writeStore(CHAT_STORE, "");
  renderChat(true);
  renderChatList();
  if (!quiet) $("#chat-q").focus();
}

// Looks again while an answer is still to come, once a second, one look at
// a time; stops when it is in or the Chat screen is left.
let CHAT_TIMER = 0;
const pollChat = single(async () => {
  clearTimeout(CHAT_TIMER);
  if (!CHAT || !chatPending(CHAT) || !chatOpen() || document.hidden) return;
  const id = CHAT.id;
  let c;
  try { c = (await api(`/api/chat?id=${encodeURIComponent(id)}`)).chat; } catch { c = undefined; }
  if (CHAT?.id !== id) return;
  if (c === null) { newChat({ quiet: true }); return; }
  if (c) {
    const was = chatPending(CHAT);
    CHAT = c;
    renderChat();
    if (was && !chatPending(c)) {
      const last = [...c.messages].reverse().find((m) => m.role === "assistant");
      say(`Answered: ${(last?.text || "").split("\n")[0].slice(0, 140)}`);
      loadChats();
    }
  }
  if (chatPending(CHAT)) CHAT_TIMER = setTimeout(pollChat, CHAT_POLL_MS);
});

function renderChat(top = false) {
  const log = $("#chat-log");
  const c = CHAT;
  $("#chat-title").textContent = c ? c.title : "New conversation";
  $("#chat-rename").hidden = !c;
  $("#chat-delete").hidden = !c;
  if (!c || !c.messages.length) {
    setKids(log, el("div", { class: "chat-empty" },
      el("div", { class: "empty-icon", "aria-hidden": "true", text: "?" }),
      el("div", { class: "empty-title", text: "Ask the bot anything about itself" }),
      el("div", { class: "empty-sub", text: "It reads the bot's own records (scripts, filing briefs, check reports, jobs, uploads, the journal) and how the bot is right now, then answers with the records it used. Follow-up questions read the conversation. It never changes anything." }),
      el("div", { class: "chat-ideas" }, CHAT_IDEAS.map((q) => el("button", { type: "button", class: "sm", text: q, onclick: () => sendChat(q) })))));
    return;
  }
  const near = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  log.querySelector(".chat-empty")?.remove();
  const keep = new Map($$(".msg", log).map((n) => [n.dataset.id, n]));
  let prev = null;
  c.messages.forEach((m) => {
    // a waiting answer names the render it waits for, and its time left
    const run = m.status === "waiting" ? (STATE?.jobs || []).find((j) => j.status === "running") : null;
    const sig = `${m.status || ""}|${(m.text || "").length}|${m.stage || ""}|${m.thinking ? 1 : 0}|${m.ahead ?? ""}|${m.note ? 1 : 0}|${run ? `${run.id}${Math.round((run.progress?.eta_s || 0) / 60)}` : ""}`;
    let node = keep.get(m.id);
    if (!node || node.dataset.sig !== sig) {
      const fresh = m.role === "user" ? userMsg(m) : aiMsg(m);
      fresh.dataset.sig = sig;
      if (node) node.replaceWith(fresh); else if (prev) prev.after(fresh); else log.prepend(fresh);
      node = fresh;
    }
    keep.delete(m.id);
    prev = node;
  });
  keep.forEach((n) => n.remove());
  if (top) log.scrollTop = log.scrollHeight;
  else if (near) log.scrollTop = log.scrollHeight;
  tickChat();
}

function userMsg(m) {
  return el("article", { class: "msg me", "data-id": m.id },
    el("div", { class: "bubble", text: m.text }),
    el("time", { class: "meta", text: clock(m.at) }));
}

function aiMsg(m) {
  const pending = CHAT_PENDING.includes(m.status);
  // "is-" because .waiting, .done and the like already style other things
  const node = el("article", { class: `msg ai is-${m.status || "done"}${m.answered === "none" ? " is-fallback" : ""}`, "data-id": m.id,
    "aria-busy": pending ? "true" : null, "data-started": String(((m.started || m.at) || Date.now() / 1000) * 1000) });
  const who = m.answered === "code" ? "Counted by the bot's code" : m.answered === "none" ? "The bot (no AI answer)" : "Local AI";
  const bits = [m.answered === "model" && m.model ? m.model : null, m.answered === "model" && m.provider && m.provider !== "ollama" ? "HOSTED" : null,
    m.seconds != null && !pending ? `took ${secs(m.seconds)}` : null, m.finished ? clock(m.finished) : null].filter(Boolean);
  node.append(el("div", { class: "msg-head" }, el("span", { class: "who", text: who }), bits.length ? el("span", { class: "meta", text: bits.join(" · ") }) : null));
  if (pending) node.append(stageLine(m));
  if (m.status === "waiting" && m.note) {
    node.append(el("details", { class: "msg-note" }, el("summary", { text: "While it waits: what the search found on file" }), el("pre", { class: "text", text: m.note })));
  }
  const cites = {};
  (m.cited || []).forEach((s) => { cites[s.n] = `${s.title}${s.about ? ` — ${s.about}` : ""}`; });
  if (m.answered === "none") {
    const [first, ...rest] = (m.text || "").split("\n");
    node.append(el("p", { class: "msg-why", text: first }), el("pre", { class: "text", text: rest.join("\n").trim() }));
    node.append(el("p", { class: "meta", text: "This is what the bot found without the AI. Ask again once it is fixed; Settings shows whether the local AI is reachable." }));
  } else if (m.text) {
    const body = el("div", { class: "md" }, md(m.text, cites));
    if (m.status === "thinking") {
      // at the end of the last line written, not on a line of its own
      let at = body.lastElementChild || body;
      while (at.lastElementChild && /^(UL|OL)$/.test(at.tagName)) at = at.lastElementChild;
      at.append(el("span", { class: "caret", "aria-hidden": "true" }));
    }
    node.append(body);
  }
  if (m.status === "failed") node.append(el("p", { class: "msg-why", text: `It broke while answering: ${m.error || "no reason given"}. Ask again; if it keeps failing, the bot's log has the details.` }));
  if (m.status === "stopped") node.append(el("p", { class: "meta", text: m.text ? "You stopped it here." : "You stopped this question before it was answered." }));
  if (m.loose?.length) {
    node.append(el("p", { class: "msg-warn", text: `⚠ Not in anything it read: ${m.loose.join(", ")}. Treat those numbers as the AI's guesses.` }));
  }
  if (m.status === "done" && m.answered === "model") {
    node.append(m.cited?.length
      ? el("details", { class: "msg-src" }, el("summary", { text: `It read ${m.read} record${m.read === 1 ? "" : "s"} and used ${m.cited.length}` }),
        el("ol", {}, m.cited.map((s) => el("li", { value: String(s.n) }, el("b", { text: s.title }), s.about ? ` — ${s.about}` : "", s.where ? el("span", { class: "meta", text: ` · on ${s.where}` }) : null))))
      : el("p", { class: "meta", text: `It read ${m.read || 0} records and named none of them, so check what it says. /find in Commands lists what is on file.` }));
  }
  const acts = el("div", { class: "msg-acts" });
  if (pending) acts.append(el("button", { type: "button", class: "ghost sm", text: m.status === "thinking" ? "Stop" : "Don't answer it", title: m.status === "thinking" ? "Ends the answer where it has got to" : "Drops this question from the line", onclick: (e) => chatAct("/api/chat/stop", m, e.currentTarget) }));
  else {
    if (m.text && m.answered !== "none") acts.append(el("button", { type: "button", class: "ghost sm", text: "Copy", onclick: (e) => copyText(m.text, e.currentTarget) }));
    acts.append(el("button", { type: "button", class: "ghost sm", text: "Ask again", title: "The same question, read fresh: the bot's state may have moved", onclick: (e) => chatAct("/api/chat/retry", m, e.currentTarget) }));
  }
  node.append(acts);
  return node;
}

// What a pending answer is doing, in words, and for how long.
function stageLine(m) {
  let words = m.stage || "Starting";
  let hint = "";
  if (m.status === "queued") {
    words = m.ahead ? `In line: ${m.ahead} question${m.ahead === 1 ? "" : "s"} asked before it go first` : m.stage || "Next in line";
    hint = "The local AI answers one question at a time, in the order they were asked.";
  } else if (m.status === "waiting") {
    const run = (STATE?.jobs || []).find((j) => j.status === "running");
    const left = run?.progress?.eta_s;
    words = "Waiting for the render to finish";
    hint = `A render is using the graphics card, so the local AI answers once the queue is empty${run ? ` (${run.ticker} ${run.kind.replace(/^render_/, "").replace(/_/g, " ")}${left != null ? `, about ${dur(left)} left` : ""})` : ""}. It answers here even if you close the page.`;
  } else if (m.thinking) {
    hint = "This model thinks before it writes; the words appear here as they come.";
  } else if (!m.text) {
    hint = "The first answer after a while is the slowest: the model has to load onto the graphics card. A minute or two is normal on the render box.";
  }
  return el("div", { class: "msg-stage" },
    el("span", { class: "spin", "aria-hidden": "true" }),
    el("span", { class: "words", text: words }),
    el("span", { class: "secs meta" }),
    hint ? el("div", { class: "msg-hint meta", text: hint }) : null);
}
// Once a second (app.js `tick`): how long each pending answer has been.
function tickChat() {
  $$("#chat-log .msg.ai[aria-busy=true]").forEach((n) => {
    const s = Math.max(0, Math.round((Date.now() - Number(n.dataset.started)) / 1000));
    const t = n.querySelector(".msg-stage .secs");
    if (t) t.textContent = ` · ${secs(s)}`;
  });
}

// Copying an answer uses video.js's `copyText`, the page's one copy helper.
// A second one declared here replaced it for every screen, being loaded
// last: the workspace's copy buttons came back reading "Copy", whatever they
// said before, and lost the copy that works without the clipboard API.

async function chatAct(path, m, btn) {
  if (!CHAT) return;
  btn.disabled = true;
  try {
    CHAT = (await post(path, { id: CHAT.id, message: m.id })).chat || CHAT;
    renderChat();
    pollChat();
    loadChats();
  } catch (e) { alarm(e.message); btn.disabled = false; }
}

// ------------------------------------------------------------- asking
let SENDING = false;
async function sendChat(text) {
  text = String(text || "").trim();
  if (!text || SENDING) return;
  SENDING = true;
  const btn = $("#chat-send");
  btn.disabled = true;
  const seq = ++CHAT_SEQ;
  try {
    const c = (await post("/api/chat", CHAT ? { id: CHAT.id, text } : { text })).chat;
    $("#chat-q").value = "";
    if (seq !== CHAT_SEQ) { loadChats(); return; }   // he opened another meanwhile
    sizeBox();
    CHAT = c;
    CHAT_ID = c.id;
    writeStore(CHAT_STORE, c.id);
    renderChat(true);
    pollChat();
    loadChats();
  } catch (e) {
    alarm(`Not sent: ${e.message}`);
    $("#chat-error").textContent = `Not sent: ${e.message}. Your question is still in the box.`;
    $("#chat-error").hidden = false;
    setTimeout(() => { $("#chat-error").hidden = true; }, 8000);
  } finally {
    SENDING = false;
    btn.disabled = false;
    $("#chat-q").focus();
  }
}
// From Home's box and Ctrl+K: a new conversation, on the Chat screen.
function askInChat(text) {
  CHAT = null;
  CHAT_ID = "";
  writeStore(CHAT_STORE, "");
  showTab("chat", false);
  sendChat(text);
}

function sizeBox() {
  const q = $("#chat-q");
  q.style.height = "auto";
  q.style.height = `${Math.min(q.scrollHeight + 2, 220)}px`;
}
$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-q").value); });
$("#chat-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat($("#chat-q").value); }
});
$("#chat-q").addEventListener("input", sizeBox);
$("#chat-new").addEventListener("click", newChat);
$("#chat-delete").addEventListener("click", async () => {
  if (!CHAT) return;
  if (!(await askConfirm("Delete this conversation?", `“${CHAT.title}” and its answers go for good.`, "Delete it"))) return;
  try { await post("/api/chat/delete", { id: CHAT.id }); } catch (e) { alarm(e.message); return; }
  newChat();
  loadChats();
});
$("#chat-rename").addEventListener("click", () => {
  if (!CHAT) return;
  const h = $("#chat-title");
  const input = el("input", { class: "grow", value: CHAT.title, "aria-label": "The conversation's name", maxlength: "120" });
  let over = false;
  const done = async (save) => {
    if (over) return;
    over = true;
    const title = input.value.trim();
    input.replaceWith(h);
    if (!save || !title || title === CHAT.title) return;
    try { CHAT = (await post("/api/chat/rename", { id: CHAT.id, title })).chat; } catch (e) { alarm(e.message); }
    renderChat();
    loadChats();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") done(false); });
  input.addEventListener("blur", () => done(true), { once: true });
  h.replaceWith(input);
  input.focus();
  input.select();
});

// ------------------------------------------------------------- Home
// Home keeps a box: a question there starts a conversation on Chat, and the
// last few conversations are one click away.
$("#ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#ask-q").value.trim();
  if (!q) return;
  $("#ask-q").value = "";
  askInChat(q);
});
function renderHomeChats() {
  const box = $("#ask-recent");
  if (!box) return;
  const rows = (CHATS || []).slice(0, 3);
  box.hidden = !rows.length;
  setKids(box, rows.length ? [el("span", { class: "meta", text: "Recent:" }), ...rows.map((c) => el("button", { type: "button", class: `ghost sm${c.unread ? " unread" : ""}`,
    text: `${c.title}${c.pending ? " (answering…)" : ""}`, onclick: () => { showTab("chat", false); openChat(c.id); } }))] : []);
}

// ------------------------------------------------------------- the screen
SCREEN_LOAD.chat = () => {
  sizeBox();
  renderChat(true);
  loadChats();
  if (CHAT_ID) openChat(CHAT_ID, { quiet: true }); else newChat({ quiet: true });
};
// The list is read now and then: often while an answer is being written or
// Chat is open, rarely otherwise (another tab may have asked).
function chatBoot() {
  loadChats();
  every(CHAT_LIST_MS, async () => {
    const busy = (CHATS || []).some((c) => c.pending);
    if (chatOpen() || busy || Date.now() - CHAT_LIST_AT > 30000) await loadChats();
    if (chatOpen() && chatPending(CHAT)) pollChat();
  });
}

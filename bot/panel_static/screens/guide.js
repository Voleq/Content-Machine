// What every screen and every step of a video is for, why it is there, and
// how to use it. He worked the page "like a blind guy walking on a path"
// (30 Oct 2026). Loaded after app.js and uses its helpers.
//
// ONE ENTRY PER SCREEN OR STEP. A screen's key is its tab (`tab-<key>`), a
// step's is its id in the video view (bot/panel_views STEPS). `how` is the
// list in the "How this works" box: what it does, why, how, what comes next.
// A new screen, step or data source adds its entry here and gets the same
// box: `howTo(key)` builds it, folded away once he folds it.

const GUIDE = {
  // ------------------------------------------------------------ the screens
  home: {
    title: "How Home works",
    how: [
      "Home is your desk. Inbox lists every video waiting on you, the most urgent first, each with its next step on a button. “Next up” at the top is the one to do now.",
      "Start a video: type a ticker and pick a lane. Guided SHORT walks you through one SHORT and asks for one thing at a time. SHORT is the 9:16 clip on a stock that moved today. LONG is the 16:9 deep dive on a value name. UPDATE is a LONG that follows up a name you already covered: what the last video said, and what has moved since.",
      "Send to says which video a dropped file or a paste goes to. Drop your Capital IQ workbook, a screengrab or a script file on the box; paste a script, an angle pick, or the answer to a question the bot asked (the yellow “Waiting for” line under the top bar says what it is waiting for).",
      "Everything you press answers in Replies on the right. A slow one shows “working…” with a timer and what the bot says on the way; you can keep using the page, and the answer arrives there, or in Activity if you left.",
      "Ask the bot opens a conversation with the local AI in Chat, where every conversation is kept; the last few are one click away under the box.",
      "The Render queue runs one render at a time. Each row says what it is doing in words (making the voice, drawing Dennis in 3D, putting the frames together) and how far it is.",
      "Today's movers are the day's gainers and losers (and before the open, after the close) from stockanalysis.com, kept to the screener's price and size floors. Click a ticker to open a SHORT on it; Read again fetches the lists (or /movers in the chat). A live screen adds the names Yahoo's lists missed.",
    ],
  },
  chat: {
    title: "How Chat works",
    how: [
      "What: a conversation with the local AI (Gemma, on the render box) about the bot itself: what is waiting on you, why a render failed, what an earlier script said, which memes there are, what a switch does.",
      "Why: the answers come from the bot's own records and how it is right now, not from the AI's memory, so it can tell you what the bot did and where to look. It never changes anything.",
      "How: type a question and press Enter. You see what it is doing (searching, reading, writing) and the answer appears as it is written; under it, the records it used. A follow-up such as “and the one before?” reads the conversation. Every conversation is kept on the left: rename one, delete one, or start a new one.",
      "Good to know: it answers one question at a time, and waits while a render is using the graphics card; the answer still lands here, even if you close the page. The first question after a while takes longest, while the model loads. Counts and totals (“how many shorts this month?”) are worked out by the bot's code, never by the AI.",
    ],
  },
  videos: {
    title: "How Videos works",
    how: [
      "Every video from the last 14 days, the one that needs you most first.",
      "The row of steps on each card is the road every video takes: ✓ is done, the highlighted one is what it is waiting for, a red one is blocked.",
      "Open walks you through the video's steps one screen at a time. Make active sends Home's drops and pastes (and Telegram's) to that video.",
    ],
  },
  ideas: {
    title: "How Ideas works",
    how: [
      "Where the next video comes from. The backlog is your list, ranked by the bot; add a name by hand or from the screen.",
      "Run the screener for this morning's candidates: names moving today for SHORTs, beaten-down value names for LONGs. It takes a minute or two.",
      "The watch list is the names whose intraday moves the bot tells you about; ones you have published join it by themselves. Earnings dates are flagged on both sides of the print.",
      "Start on any row opens that name as a new video, ready for its workbook.",
    ],
  },
  calendar: {
    title: "How Calendar works",
    how: [
      "What went out, what is scheduled to go public, and the days with nothing on them.",
      "On a free day, “+ schedule” offers the finished videos not yet uploaded and the time it goes public.",
      "Reporting today is stockanalysis.com's earnings calendar: the biggest names reporting, before the open or after the close, and how many report on the days after. Click one to open a SHORT on it; Read again fetches it.",
    ],
  },
  stats: {
    title: "How Stats works",
    how: [
      "What held viewers across your videos: which openers kept people, which writing rules helped, how length and chapter types did, and how Dennis's calls have aged.",
      "It reads YouTube's retention from 48 hours after a video goes public, so it fills in as videos age. The writer's prompt draws on it.",
    ],
  },
  library: {
    title: "How Library works",
    how: [
      "What the writer and the render draw on. The writing files (the voice bible, the rules) go into every prompt: edit one here and your version is used from the next prompt on; Reset puts the shipped one back.",
      "What Dennis remembers: the facts he has said about himself and the jokes already used, so the writer keeps to them and the checks flag a re-tell.",
      "The memes, your own b-roll clips (they win over Pexels), the sounds and the 3D room's camera angles.",
    ],
  },
  settings: {
    title: "How Settings works",
    how: [
      "The switches: each says what it changes. They take effect at once and survive a restart.",
      "Health checks the render box before a real video: the keys, the tools, the disk. Anything listed there stops a real render until it is fixed.",
    ],
  },
  activity: {
    title: "How Activity works",
    how: [
      "Everything the bot said, newest first. Pushes are what it tells you on its own: a render started, finished or failed, a storyboard, a reminder.",
      "Replies are the answers to what you pressed, including ones that finished after you left the page, and the steps a slow action reported on its way.",
    ],
  },
  commands: {
    title: "How Commands works",
    how: [
      "Every command the Telegram bot knows, as a form. You rarely need it: every step of a video has its own buttons.",
      "Type / anywhere on the page to come here. A command runs exactly as it would in Telegram, and answers in Replies.",
    ],
  },

  // ------------------------------------------------------- a video's steps
  data: {
    how: [
      "What: the workbook you fill in your Capital IQ terminal (dennis_data.xlsx), one per video.",
      "Why: every figure Dennis says comes from it, and the checks compare the script with it line by line. For a SHORT it also tells the bot what kind of day it is (an earnings print, news, or just a move), which decides what the script argues.",
      "How: drop the file here or press Upload. The bot checks the ticker matches, the numbers are recent (10 days at most by default), and the figures it needs are filled in. Problems are listed here; red ones stop the video until a fixed workbook is uploaded.",
      "From stockanalysis.com: when the prompt is made, the bot also reads the news and press releases around the move (outlet and minute), the earnings date, twenty quarters of statements, the company's own KPIs, the analysts' target changes, who runs it, and the latest earnings call, with the passages the writer is shown (the local AI picks them; the words stay the call's). A LONG also gets the call a year earlier, for said against did. Each part says when it was read; Fetch again reads it all again, and the next prompt uses it.",
      "The quarter check: where the workbook's last five quarters and the site's disagree, it is listed here and on the Check step, so you can fix the workbook before a wrong figure goes on screen. A quarter the workbook left blank is filled from the site, and named here.",
      "Next: the bot writes the prompt for your Claude chat. A LONG goes to Angle first; a SHORT or an UPDATE goes straight to Write.",
    ],
  },
  angle: {
    how: [
      "What: LONG only. The first of two prompts: your Claude chat reads the workbook and proposes ranked angles, the one argument the video makes.",
      "Why: a long has to carry one story for many minutes. Picking the angle before anything is written keeps the script on it.",
      "How: Copy the angle prompt, paste it into a new Claude chat, copy its whole answer, paste it here and press Send the angles. Then pick one with its button, or send a tweak in your own words.",
      "Next: the bot writes the writing prompt for that angle, on the Write step.",
    ],
  },
  write: {
    how: [
      "What: the script is written in your own Claude chat, from the bot's prompt. Nothing here calls a paid model.",
      "Why: the prompt carries your workbook's numbers, Dennis's voice and story, the rules the checks will hold the script to, and the pictures the video can show, so the chat writes something the bot can render.",
      "How: Copy the prompt, paste it into a new Claude chat, copy the chat's whole answer, paste it in the box and press Send the script (or drop the .txt). An unsent paste is kept in this browser until the bot takes it.",
      "Next: the bot reads the script, plans the shots and runs every check. That takes a few seconds to a minute (your Replies box shows it working), then the Check step opens with what it found. Pasting a new script later replaces this one.",
    ],
  },
  proof: {
    how: [
      "What: a full render of the video, free: the real pictures, rooms and Dennis at full size, with a stand-in voice made on your computer instead of the paid one.",
      "Why: you see what the final will look like before anything is paid for, and fix the script while it costs nothing. The stand-in voice guesses where each word falls inside a sentence, so small timing slips here are not faults; the final is timed to the real voice.",
      "How: press Render the free proof. It joins the render queue, and this step shows what it is doing and how far it is. Most of the time goes on drawing Dennis in 3D. You can leave the page; it carries on. Then watch it: click the video and press n where something is wrong to note it with its time; Copy the fault list gives you the numbered list.",
      "Next: fix what you noted on the Check step (each save runs the checks again), render another proof if you want to see it, then Approve.",
    ],
  },
  approve: {
    how: [
      "What: approving fixes this exact version of the script for the paid render.",
      "Why: the paid voice is made once, from exactly what you approved. If you change the script afterwards the approval is withdrawn, and you approve the new version.",
      "How: press Approve. The bot runs every check again first; nothing red may be left. Nothing is spent at this step.",
      "Next: the Render step, which is the one that spends (the voice estimate is shown here).",
    ],
  },
  voice: {
    how: [
      "What: the paid voice for this script, word by word, once the final render has made it.",
      "Why: a wrong name or figure in the voice is the one fault you cannot fix in the pictures.",
      "How: click a word to play from there. Double-click a word to teach how it is said; the next voice made uses it. Redo speaks one sentence again (it costs a little, up to 10 per video, and restarts a render under way).",
      "Next: the render uses this voice; nothing more to do here unless a word is wrong.",
    ],
  },
  render: {
    how: [
      "What: the final video. The paid voice is made first (once; a re-render reuses it), then Dennis is drawn in 3D, every frame is put together, and the video is encoded with its captions.",
      "Why: this is the video that goes to YouTube.",
      "How: press Render the final and confirm. It joins the queue; this step shows each stage in words, how far it is and roughly how long is left. Stop stops it at the next frame and keeps what is drawn, so running it again picks up from there.",
      "Next: Upload, once it says the final is rendered.",
    ],
  },
  upload: {
    how: [
      "What: everything YouTube Studio asks for, each with a Copy button: titles, description, tags, pinned comment, chapters, the cover.",
      "Why by hand: YouTube keeps every upload from the bot's API project private until Google has audited it, so videos go up by hand in Studio for now. The bot can still send a private copy.",
      "How: follow the checklist on the right, top to bottom. Mark the AI voice as altered or synthetic content. Then paste the video's link back here so the bot knows it is out.",
      "Next: Live, which reads how viewers watched it.",
    ],
  },
  live: {
    how: [
      "What: how viewers watched the video: the share still watching at each moment, and the lines they left on.",
      "Why: it is how the writing gets better; Stats and the next prompts learn from it.",
      "How: nothing to do until 48 hours after it goes public. Then read where viewers left, and correct a figure here if one was wrong.",
    ],
  },
};

// The "How this works" box for one screen or step; null when it has none.
function howTo(key) {
  const g = GUIDE[key];
  if (!g) return null;
  const store = `dennis.panel.howto.${key}`;
  const box = el("details", { class: "how-to", "data-guide": key, open: readStore(store) !== "closed" },
    el("summary", { text: g.title || "How this step works" }),
    el("ul", {}, g.how.map((t) => el("li", { text: t }))));
  box.addEventListener("toggle", () => writeStore(store, box.open ? "" : "closed"));
  return box;
}

// Each screen's box, once, at its top: the screens redraw what is under it.
(function placeScreenGuides() {
  const at = { home: "#next-up", videos: "#videos", activity: ".feed-card", commands: ".cmdbar", chat: ".chat-layout" };
  Object.keys(GUIDE).forEach((key) => {
    const tab = $(`#tab-${key}`);
    if (!tab || !GUIDE[key].title) return;
    const before = at[key] ? $(at[key], tab) : tab.firstElementChild;
    tab.insertBefore(howTo(key), before || null);
  });
})();

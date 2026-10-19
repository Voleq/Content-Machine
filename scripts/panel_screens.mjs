// Screenshots of the web panel, for looking at it without a browser open.
//
//   node scripts/panel_screens.mjs "http://127.0.0.1:8765/#k=KEY" OUT_DIR route [route…]
//
// A route is the part after the key: "" for Home, "?tab=videos",
// "#/video/EXMPL/2026-10-18/check". Each is shot at 1440x900 in light and in
// dark, as OUT_DIR/<name>-light.png and -dark.png. It starts nothing itself:
// run `python scripts/panel_demo.py` first. Uses the Playwright that ships
// with the machine's node tools (NODE_PATH=$(npm root -g)).
import { createRequire } from "module";
import path from "path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [link, out, ...routes] = process.argv.slice(2);
const base = link.split("/#")[0];
const key = decodeURIComponent(link.split("#k=")[1] || "");
const launch = {};
if (process.env.CHROMIUM) launch.executablePath = process.env.CHROMIUM;
const browser = await chromium.launch(launch);
const errors = [];
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: scheme });
  await ctx.addInitScript((k) => localStorage.setItem("dennis.panel.key", k), key);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${scheme}: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${scheme} console: ${m.text()}`); });
  for (const route of routes.length ? routes : [""]) {
    await page.goto(base + "/" + route, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const name = (route.replace(/^[#?/]+/, "").replace(/[^A-Za-z0-9-]+/g, "_") || "home").slice(0, 60);
    await page.screenshot({ path: path.join(out, `${name}-${scheme}.png`), fullPage: true });
  }
  await ctx.close();
}
await browser.close();
if (errors.length) { console.log(errors.join("\n")); process.exitCode = 1; }

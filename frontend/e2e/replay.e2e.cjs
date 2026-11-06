// End-to-end check of the replay page (needs the API on :8000 and `vite preview` on :4173).
// Covers the spec's "before calling a screen done" list: advance days, accept + reject with reasons by
// keyboard, undo, map and table views, URL state survives reload, reduced motion, no console errors,
// and an axe accessibility scan with zero serious/critical issues.
const { chromium } = require("playwright");
const { readFileSync } = require("node:fs");
const AXE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const BASE = process.env.CASEWEB_URL || "http://localhost:4173";

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1600, height: 960 } });
  const errors = [];
  p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  p.on("pageerror", (e) => errors.push(String(e)));
  const fail = (msg) => { console.error("FAIL:", msg); process.exitCode = 1; };

  await p.goto(`${BASE}/?s=E2E-${Date.now()}&analyst=anon-9&tab=series&view=web`);
  await p.getByText("Day 1 ·").waitFor();
  for (let i = 0; i < 14; i++) { await p.getByRole("button", { name: /Advance day/ }).click(); await p.waitForTimeout(200); }
  await p.locator("nav .row").first().click();
  await p.getByText("Uses only place, time and method").waitFor();
  await p.waitForTimeout(800);

  await p.keyboard.press("1"); await p.keyboard.press("1"); await p.keyboard.press("Enter");
  await p.getByText(/Saved\. Undo within/).waitFor();
  await p.waitForTimeout(600);
  if (!(await p.locator("nav .tag", { hasText: "Active" }).count())) fail("accepted link did not make the series Active");
  await p.keyboard.press("z"); await p.waitForTimeout(600);
  if (await p.locator(".undo-bar").count()) fail("Z did not undo");
  await p.keyboard.press("2"); await p.keyboard.press("2"); await p.keyboard.press("Enter");
  await p.getByText(/Saved\. Undo within/).waitFor();

  await p.getByRole("tab", { name: "Map" }).click(); await p.waitForTimeout(1200);
  const mapH = await p.locator(".maplibregl-canvas").evaluate((c) => c.getBoundingClientRect().height);
  if (mapH < 100) fail(`map canvas too small (${mapH}px)`);
  await p.getByRole("tab", { name: "Table" }).click(); await p.waitForTimeout(400);
  await p.reload(); await p.getByText("Uses only place, time and method").waitFor();
  if (!(await p.getByRole("tab", { name: "Table", selected: true }).count())) fail("view not restored from URL");

  await p.emulateMedia({ reducedMotion: "reduce" });
  await p.getByRole("tab", { name: "Web of cases" }).click(); await p.waitForTimeout(800);

  await p.addScriptTag({ content: AXE });
  const axe = await p.evaluate(async () => {
    const r = await window.axe.run(document, { resultTypes: ["violations"] });
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help }));
  });
  const serious = axe.filter((v) => ["serious", "critical"].includes(v.impact));
  if (serious.length) fail("axe serious/critical: " + JSON.stringify(serious));
  if (errors.length) fail("console errors: " + errors.join(" | "));
  console.log(JSON.stringify({ axe, errors }, null, 1));
  await b.close();
  if (!process.exitCode) console.log("replay e2e: passed");
})().catch((e) => { console.error("FAIL", e.message); process.exit(1); });

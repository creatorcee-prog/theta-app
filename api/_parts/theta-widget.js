// Theta's Home Screen widget, for the free Scriptable app (scriptable.app).
// Settings → Home Screen widget → Copy the script. Or paste this whole file into a new script in Scriptable and run it once:
// it asks for your ASK_KEY (kept in the iPhone's Keychain, never in this file).
// Run it again in Scriptable any time to change the address or key. Then long-press the Home Screen → + →
// Scriptable → pick Small or Medium → tap the widget → Script: this one.
// Tapping the widget opens the Head page. iOS refreshes it about every 15 minutes.

const CYAN = new Color("#4fd3ff"), BG = new Color("#05080c"), DIM = new Color("#8fa3b3");

const DEFAULT_URL = "__ORIGIN__"; // filled in by Theta when you copy the script from Settings

function cleanUrl(v) { // "theta.vercel.app/settings " -> "https://theta.vercel.app"
  v = (v || "").trim();
  if (!v) return "";
  if (!/^https?:\/\//i.test(v)) v = "https://" + v;
  const m = v.match(/^(https?:\/\/[^\/?#\s]+)/i);
  return m ? m[1].toLowerCase() : "";
}

async function ask(key, prompt, placeholder, current) {
  const a = new Alert(); a.title = "Theta widget"; a.message = prompt;
  a.addTextField(placeholder, current || ""); a.addAction("Save"); a.addCancelAction("Cancel");
  if (await a.present() === -1) return current || null;
  let v = a.textFieldValue(0).trim();
  if (key === "theta:url") v = cleanUrl(v);
  if (v) Keychain.set(key, v);
  return v || current || null;
}

async function setting(key, prompt, placeholder, fallback) {
  if (Keychain.contains(key)) return key === "theta:url" ? cleanUrl(Keychain.get(key)) : Keychain.get(key).trim();
  if (fallback && !fallback.startsWith("__")) { Keychain.set(key, fallback); return fallback; }
  if (config.runsInWidget) return null;
  return ask(key, prompt, placeholder);
}

async function fetchTheta(base, key) { // {data} or {error: what to tell you}
  const r = new Request(base + "/api/phone/widget"); r.headers = {"x-ask-key": key}; r.timeoutInterval = 10;
  let text;
  try { text = await r.loadString(); }
  catch (e) { return {error: "Can't reach " + base.replace(/^https?:\/\//, "") + ". Open Scriptable and run Theta to check the address."}; }
  const code = r.response && r.response.statusCode;
  let d = null;
  try { d = JSON.parse(text); } catch (e) { d = null; }
  if (d && d.ok) return {data: d};
  if (d && code === 401) return {error: "Wrong ASK_KEY. Open Scriptable, run Theta, tap Change key."};
  if (d) return {error: d.error || "Theta said no (" + code + ")."};
  return {error: "That address isn't Theta's main one (got " + code + "). Run Theta in Scriptable and use the address Safari shows."};
}

function rings(size) { // Theta's Rings avatar, drawn like the Head page
  const d = new DrawContext(); d.size = new Size(size, size); d.opaque = false; d.respectScreenScale = true;
  const c = size / 2, t = Date.now() / 1000;
  [[0.40, 0.020, 3, 0.35, 0.5], [0.32, 0.030, 5, -0.6, 0.35], [0.24, 0.016, 8, 0.95, 0.25]].forEach(([r, w, segs, sp, gap]) => {
    const rr = size * r, step = Math.PI * 2 / segs, rot = t * sp * 0.05;
    d.setStrokeColor(CYAN); d.setLineWidth(size * w);
    for (let k = 0; k < segs; k++) {
      const p = new Path(), a0 = rot + k * step, a1 = a0 + step - gap, pts = [];
      for (let i = 0; i <= 16; i++) { const a = a0 + (a1 - a0) * i / 16; pts.push(new Point(c + Math.cos(a) * rr, c + Math.sin(a) * rr)); }
      p.addLines(pts); d.addPath(p); d.strokePath();
    }
  });
  [[0.16, "#4fd3ff", 0.25], [0.10, "#bff0ff", 0.6], [0.05, "#ffffff", 1]].forEach(([r, col, alpha]) => {
    const color = new Color(col, alpha); d.setFillColor(color);
    d.fillEllipse(new Rect(c - size * r, c - size * r, size * r * 2, size * r * 2));
  });
  return d.getImage();
}

function text(stack, value, size, color, lines, weight) {
  const t = stack.addText(value); t.font = weight === "bold" ? Font.boldSystemFont(size) : Font.systemFont(size);
  t.textColor = color; t.lineLimit = lines; t.minimumScaleFactor = 0.8; return t;
}

async function build() {
  const base = await setting("theta:url", "Your Theta address", "https://your-app.vercel.app", DEFAULT_URL);
  const key = await setting("theta:key", "Your ASK_KEY (the same one as in Vercel)", "ASK_KEY");
  const w = new ListWidget(); w.backgroundColor = BG; w.setPadding(12, 12, 12, 12);
  w.refreshAfterDate = new Date(Date.now() + 15 * 60e3);
  const got = base && key ? await fetchTheta(base, key) : {error: "Run Theta once in Scriptable to set me up."};
  const d = got.data || {line: got.error, at: "", next: null, focus: null, waiting: 0, reminders: 0, url: "/head"};
  w.url = (base || "") + (d.url || "/head");
  const small = config.widgetFamily === "small";
  if (small) {
    const top = w.addStack(); top.centerAlignContent();
    top.addImage(rings(40)).imageSize = new Size(40, 40); top.addSpacer(6);
    const name = top.addStack(); name.layoutVertically();
    text(name, "Theta", 13, Color.white(), 1, "bold");
    text(name, d.focus ? "focusing" : (d.at || ""), 10, CYAN, 1);
    w.addSpacer(6);
    text(w, d.focus ? "On " + d.focus : d.line, 12, Color.white(), 3);
    w.addSpacer();
    text(w, d.next ? "Next: " + d.next : (d.waiting ? d.waiting + " waiting for you" : ""), 10, DIM, 1);
  } else {
    const row = w.addStack(); row.centerAlignContent();
    row.addImage(rings(84)).imageSize = new Size(84, 84); row.addSpacer(12);
    const col = row.addStack(); col.layoutVertically();
    const head = col.addStack(); head.centerAlignContent();
    text(head, "Theta", 14, Color.white(), 1, "bold"); head.addSpacer(6);
    text(head, d.focus ? "focusing" : (d.at || ""), 10, CYAN, 1);
    col.addSpacer(3);
    text(col, d.line, 13, Color.white(), 3);
    col.addSpacer(5);
    const bits = [d.focus ? "⏱ " + d.focus : null, d.next ? "Next: " + d.next : null,
      d.waiting ? d.waiting + " waiting for you" : null, d.reminders ? d.reminders + " reminder" + (d.reminders === 1 ? "" : "s") + " today" : null].filter(Boolean);
    text(col, bits.slice(0, 2).join("  ·  ") || "Nothing pressing", 10, DIM, 1);
  }
  return w;
}

if (config.runsInWidget) {
  Script.setWidget(await build());
} else { // run in the app: change the address or key, or see the widget
  const base = Keychain.contains("theta:url") ? cleanUrl(Keychain.get("theta:url")) : "";
  const m = new Alert(); m.title = "Theta widget";
  m.message = "Address: " + (base || "not set") + "\nKey: " + (Keychain.contains("theta:key") ? "saved" : "not set");
  m.addAction("Show the widget"); m.addAction("Change address"); m.addAction("Change key"); m.addCancelAction("Done");
  const pick = await m.present();
  if (pick === 1) await ask("theta:url", "Your Theta address (the one in Safari when Theta is open)", "https://your-app.vercel.app", base);
  if (pick === 2) await ask("theta:key", "Your ASK_KEY (the same one as in Vercel)", "ASK_KEY");
  if (pick >= 0) await (await build()).presentMedium();
}
Script.complete();

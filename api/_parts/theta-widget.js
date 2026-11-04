// Theta's Home Screen widget, for the free Scriptable app (scriptable.app). Shows Theta's avatar (Urchin Pour) in its mood's color.
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

function urchin(size, hex) { // Theta's avatar, Urchin Pour: a still frame of the 3D dot globe, in its mood's color
  const d = new DrawContext(); d.size = new Size(size, size); d.opaque = false; d.respectScreenScale = true;
  const c = size / 2, R = size * 0.36, N = 260, t = Date.now() / 60000, pts = [];
  const yaw = t * 0.7, pitch = 0.32, cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  let seed = Math.floor(t) * 7919 + 13;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.39996, s = rnd();
    const lon = Math.atan2(Math.sin(th) * r, Math.cos(th) * r), spike = s > 0.8 ? 0.25 * Math.abs(Math.sin(lon * 5 + y * 3 + t)) * (s - 0.8) * 5 : 0;
    const k = 1 + spike, x = Math.cos(th) * r * k, yy = y * k, z = Math.sin(th) * r * k;
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy, y2 = yy * cp - z1 * sp, z2 = yy * sp + z1 * cp, pr = 3.2 / (3.2 + z2);
    pts.push([c + x1 * R * pr, c + y2 * R * pr, z2, pr]);
  }
  pts.sort((p, q) => q[2] - p[2]);
  let coreDone = false;
  const glow = () => [[0.2, 0.18], [0.12, 0.45], [0.06, 1]].forEach(([r, a], i) => {
    d.setFillColor(new Color(i === 2 ? "#ffffff" : hex, a)); d.fillEllipse(new Rect(c - size * r, c - size * r, size * r * 2, size * r * 2)); });
  for (const [x, y, z, pr] of pts) {
    if (!coreDone && z < 0) { glow(); coreDone = true; }
    const fog = Math.max(0.15, Math.min(1, 0.65 - z * 0.55)), rr = size * 0.011 * pr * pr;
    d.setFillColor(new Color(hex, fog)); d.fillEllipse(new Rect(x - rr, y - rr, rr * 2, rr * 2));
  }
  if (!coreDone) glow();
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
    top.addImage(urchin(44, d.color || "#4fd3ff")).imageSize = new Size(44, 44); top.addSpacer(6);
    const name = top.addStack(); name.layoutVertically();
    text(name, "Theta", 13, Color.white(), 1, "bold");
    text(name, d.focus ? "focusing" : (d.at || ""), 10, CYAN, 1);
    w.addSpacer(6);
    text(w, d.focus ? "On " + d.focus : d.line, 12, Color.white(), 3);
    w.addSpacer();
    text(w, d.next ? "Next: " + d.next : (d.waiting ? d.waiting + " waiting for you" : ""), 10, DIM, 1);
  } else {
    const row = w.addStack(); row.centerAlignContent();
    row.addImage(urchin(90, d.color || "#4fd3ff")).imageSize = new Size(90, 90); row.addSpacer(12);
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

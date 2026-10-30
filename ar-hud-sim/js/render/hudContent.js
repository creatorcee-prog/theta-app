// What the Micro-OLED displays. One renderer feeds both the emitting
// surface in 3D and the first-person view, at the display's own aspect
// ratio. Content is visual only: rays are traced per pixel position, so the
// optics do not depend on what is shown.

const imageCache = new Map(); // dataURL -> HTMLImageElement
let onImageReady = null;
export function setImageReadyHandler(fn) { onImageReady = fn; }

function getImage(src) {
  if (!src) return null;
  let img = imageCache.get(src);
  if (!img) {
    img = new Image();
    img.onload = () => onImageReady?.();
    img.src = src;
    imageCache.set(src, img);
  }
  return img.complete && img.naturalWidth ? img : null;
}

// Canvas size: the display's pixel grid, scaled down to at most 1024 px wide.
export function hudCanvasSize(oled) {
  const s = Math.min(1, 1024 / oled.resX);
  return { w: Math.max(16, Math.round(oled.resX * s)), h: Math.max(10, Math.round(oled.resY * s)) };
}

// The part of the display that actually reaches the pupil (traced), as a
// rectangle in display coordinates u, v in [-1, 1] (u right, v up), or null.
export function visibleViewport(pixelResults) {
  const vis = pixelResults.filter((p) => p.imaged ?? p.visible);
  if (!vis.length || vis.length === pixelResults.length) return null;
  const us = vis.map((p) => p.u), vs = vis.map((p) => p.v);
  return { u0: Math.min(...us), u1: Math.max(...us), v0: Math.min(...vs), v1: Math.max(...vs) };
}

export function renderHud(canvas, hud, oled, { mirrored = false, viewport = null, shear = 0 } = {}) {
  let { w, h } = hudCanvasSize(oled);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = hud.background;
  ctx.fillRect(0, 0, w, h);
  // keystone pre-correction in the driver: the optics shift the image
  // horizontally in proportion to height (angle h = a u + b v); drawing the
  // content slanted by -b/a cancels it. The slanted frame is narrowed so the
  // corners stay on the panel (that width is the price in pixels).
  if (shear && hud.keystone !== false) {
    const k = -shear * (w / h); // canvas x shift per canvas y (y down = v down)
    const span = Math.abs(k) * h, sx = w / (w + span);
    ctx.translate(w / 2, h / 2); ctx.transform(1, 0, -k, 1, 0, 0); ctx.scale(sx, 1); ctx.translate(-w / 2, -h / 2);
  }
  if (mirrored) { ctx.translate(w, 0); ctx.scale(-1, 1); }
  // fit the layout to the visible part of the display, so content is as large
  // as possible without being cut off (pixels outside stay black = off)
  if (viewport && hud.fitVisible !== false) {
    let x0 = ((viewport.u0 + 1) / 2) * w, x1 = ((viewport.u1 + 1) / 2) * w;
    if (mirrored) [x0, x1] = [w - x1, w - x0];
    const y0 = ((1 - viewport.v1) / 2) * h, y1 = ((1 - viewport.v0) / 2) * h;
    if (x1 - x0 > 8 && y1 - y0 > 8) {
      ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
      ctx.translate(x0, y0); w = x1 - x0; h = y1 - y0;
    }
  }
  const s = Math.min(w / 640, h / 400);
  const color = hud.color;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;

  if (hud.mode === 'image') {
    const img = getImage(hud.image);
    if (img) {
      const ar = img.naturalWidth / img.naturalHeight;
      let dw = w, dh = h;
      if (hud.imageFit === 'contain' ? ar > w / h : ar < w / h) dh = w / ar; else dw = h * ar;
      if (hud.imageFit === 'stretch') { dw = w; dh = h; }
      ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
    } else {
      ctx.font = `500 ${Math.round(34 * s)}px "IBM Plex Mono", ui-monospace, monospace`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(hud.image ? 'Loading image…' : 'No image: upload one', w / 2, h / 2);
    }
  } else if (HUD_STYLES[hud.mode]) {
    HUD_STYLES[hud.mode].draw(ctx, w, h, s, hud);
  } else if (hud.mode === 'grid') {
    // test pattern: 1:10 grid, centre cross, corner tags, scale bar
    ctx.lineWidth = Math.max(1, 2 * s);
    const n = 8;
    for (let i = 0; i <= n; i++) {
      ctx.beginPath(); ctx.moveTo((i * (w - 1)) / n, 0); ctx.lineTo((i * (w - 1)) / n, h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, (i * (h - 1)) / n); ctx.lineTo(w, (i * (h - 1)) / n); ctx.stroke();
    }
    ctx.lineWidth = Math.max(2, 5 * s);
    ctx.beginPath(); ctx.moveTo(w / 2, h / 2 - 40 * s); ctx.lineTo(w / 2, h / 2 + 40 * s); ctx.moveTo(w / 2 - 40 * s, h / 2); ctx.lineTo(w / 2 + 40 * s, h / 2); ctx.stroke();
    ctx.font = `700 ${Math.round(40 * s)}px "IBM Plex Mono", ui-monospace, monospace`;
    ctx.textBaseline = 'top';
    ctx.fillText('TL', 10 * s, 10 * s);
    ctx.textAlign = 'right'; ctx.fillText('TR', w - 10 * s, 10 * s);
    ctx.textBaseline = 'bottom'; ctx.fillText('BR', w - 10 * s, h - 10 * s);
    ctx.textAlign = 'left'; ctx.fillText('BL', 10 * s, h - 10 * s);
  } else {
    if (hud.border) {
      ctx.lineWidth = 6 * s;
      ctx.strokeRect(6 * s, 6 * s, w - 12 * s, h - 12 * s);
    }
    const textRight = hud.arrow ? w * 0.68 : w - 30 * s;
    const fit = (text, weight, px, maxW) => {
      let size = px;
      ctx.font = `${weight} ${size}px "IBM Plex Mono", ui-monospace, monospace`;
      const tw = ctx.measureText(text).width;
      if (tw > maxW) { size = Math.max(8, Math.floor((size * maxW) / tw)); ctx.font = `${weight} ${size}px "IBM Plex Mono", ui-monospace, monospace`; }
      return size;
    };
    ctx.textBaseline = 'top';
    const x0 = 40 * s, maxW = textRight - x0;
    let y = 36 * s;
    const big = fit(hud.line1, 700, Math.round(hud.textSize * 1.0 * s), maxW);
    ctx.fillText(hud.line1, x0, y);
    y += big * 1.1 + 18 * s;
    for (const line of [hud.line2, hud.line3]) {
      if (!line) continue;
      const sz = fit(line, 500, Math.round(hud.textSize * 0.4 * s), maxW);
      ctx.fillText(line, x0 + 4 * s, y);
      y += sz * 1.4;
    }
    if (hud.arrow) {
      const cx = w * 0.82, top = h * 0.2, bot = h * 0.82, hw = w * 0.055;
      ctx.beginPath();
      ctx.moveTo(cx - hw / 2, bot); ctx.lineTo(cx - hw / 2, top + hw * 1.5); ctx.lineTo(cx - hw * 1.2, top + hw * 1.5);
      ctx.lineTo(cx, top); ctx.lineTo(cx + hw * 1.2, top + hw * 1.5); ctx.lineTo(cx + hw / 2, top + hw * 1.5); ctx.lineTo(cx + hw / 2, bot);
      ctx.closePath(); ctx.fill();
    }
    // orientation markers (read the mirror state at a glance)
    ctx.font = `700 ${Math.round(30 * s)}px "IBM Plex Mono", ui-monospace, monospace`;
    ctx.textBaseline = 'bottom';
    ctx.fillText('1', 16 * s, h - 14 * s);
    ctx.textAlign = 'right'; ctx.fillText('R', w - 16 * s, h - 14 * s);
  }
  ctx.restore();
}

// ---------------------------------------------------------------- HUD styles
// Layouts for a small monochrome see-through HUD: black is transparent, so
// they use few, bold, high-contrast elements and large type (a 0.23" panel
// behind a long-focal-length lens spans only ~5-7 degrees).

const FONT = '"IBM Plex Mono", ui-monospace, monospace';
const font = (ctx, weight, px) => { ctx.font = `${weight} ${Math.max(8, Math.round(px))}px ${FONT}`; };
function fitText(ctx, text, weight, px, maxW) {
  font(ctx, weight, px);
  const tw = ctx.measureText(text).width;
  if (tw > maxW) font(ctx, weight, Math.max(8, (px * maxW) / tw));
}
function wrap(ctx, text, maxW) {
  const words = String(text ?? '').split(/\s+/).filter(Boolean), lines = [];
  let cur = '';
  for (const wd of words) { const t = cur ? `${cur} ${wd}` : wd; if (ctx.measureText(t).width > maxW && cur) { lines.push(cur); cur = wd; } else cur = t; }
  if (cur) lines.push(cur);
  return lines;
}
function arrow(ctx, cx, cy, size, turn) {
  ctx.save(); ctx.translate(cx, cy);
  ctx.rotate(turn === 'left' ? -Math.PI / 2 : turn === 'right' ? Math.PI / 2 : turn === 'uturn' ? Math.PI : 0);
  const hw = size * 0.16;
  ctx.beginPath();
  ctx.moveTo(-hw, size * 0.5); ctx.lineTo(-hw, -size * 0.1); ctx.lineTo(-hw * 2.6, -size * 0.1);
  ctx.lineTo(0, -size * 0.5); ctx.lineTo(hw * 2.6, -size * 0.1); ctx.lineTo(hw, -size * 0.1); ctx.lineTo(hw, size * 0.5);
  ctx.closePath(); ctx.fill(); ctx.restore();
}

export const HUD_STYLES = {
  glance: {
    sample: { line1: '12:45', line2: 'Meeting in 15 min', line3: '' },
    label: 'Glance (time + one line)',
    draw(ctx, w, h, s, hud) {
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      fitText(ctx, hud.line1, 700, 230 * s, w * 0.9); ctx.fillText(hud.line1, w / 2, h * 0.42);
      if (hud.line2) { fitText(ctx, hud.line2, 600, 64 * s, w * 0.9); ctx.fillText(hud.line2, w / 2, h * 0.82); }
    },
  },
  nav: {
    sample: { line1: '', line2: '200 m', line3: 'Main St' },
    label: 'Navigation (turn + distance)',
    draw(ctx, w, h, s, hud) {
      arrow(ctx, w * 0.24, h * 0.5, h * 0.78, hud.turn ?? 'right');
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      fitText(ctx, hud.line2, 700, 150 * s, w * 0.52); ctx.fillText(hud.line2, w * 0.45, h * 0.38);
      if (hud.line3) { fitText(ctx, hud.line3, 500, 60 * s, w * 0.52); ctx.fillText(hud.line3, w * 0.45, h * 0.74); }
    },
  },
  notify: {
    sample: { line1: 'Maya', line2: 'Running 5 min late, can you order me a latte?', line3: '' },
    label: 'Notification card',
    draw(ctx, w, h, s, hud) {
      const r = h * 0.17;
      ctx.lineWidth = 6 * s; ctx.beginPath(); ctx.arc(w * 0.1 + r, h * 0.25, r, 0, Math.PI * 2); ctx.stroke();
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; font(ctx, 700, r * 1.2);
      ctx.fillText((hud.line1 || '?').trim()[0]?.toUpperCase() ?? '?', w * 0.1 + r, h * 0.25 + r * 0.05);
      ctx.textAlign = 'left'; fitText(ctx, hud.line1, 700, 80 * s, w * 0.62); ctx.fillText(hud.line1, w * 0.1 + 2.5 * r, h * 0.25);
      font(ctx, 500, 62 * s);
      wrap(ctx, hud.line2, w * 0.86).slice(0, 2).forEach((ln, i) => ctx.fillText(ln, w * 0.07, h * (0.6 + i * 0.24)));
    },
  },
  fitness: {
    sample: { line1: '142', line2: '5:12 /km', line3: '6.4 km' },
    label: 'Workout (heart rate, pace, zone)',
    draw(ctx, w, h, s, hud) {
      ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
      fitText(ctx, hud.line1, 700, 190 * s, w * 0.6); ctx.fillText(hud.line1, w * 0.06, h * 0.55);
      font(ctx, 600, 46 * s); ctx.fillText('BPM', w * 0.06, h * 0.7);
      ctx.textAlign = 'right';
      fitText(ctx, hud.line2, 600, 64 * s, w * 0.36); ctx.fillText(hud.line2, w * 0.95, h * 0.3);
      fitText(ctx, hud.line3, 600, 64 * s, w * 0.36); ctx.fillText(hud.line3, w * 0.95, h * 0.55);
      // 5-zone bar, current zone filled
      const zone = Math.max(1, Math.min(5, hud.zone ?? 3)), bw = (w * 0.88) / 5;
      ctx.lineWidth = 4 * s;
      for (let i = 0; i < 5; i++) { const x = w * 0.06 + i * bw; if (i < zone) ctx.fillRect(x + 3 * s, h * 0.8, bw - 6 * s, h * 0.12); else ctx.strokeRect(x + 3 * s, h * 0.8, bw - 6 * s, h * 0.12); }
    },
  },
  captions: {
    sample: { line1: 'Le train part à 14 h 20, quai 3.', line2: '', line3: '→ The train leaves at 2:20 pm, platform 3.' },
    label: 'Live captions / translation',
    draw(ctx, w, h, s, hud) {
      font(ctx, 600, 66 * s); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      const text = [hud.line1, hud.line2, hud.line3].filter(Boolean).join(' ');
      const lines = wrap(ctx, text, w * 0.9).slice(-3);
      lines.forEach((ln, i) => ctx.fillText(ln, w * 0.05, h * 0.92 - (lines.length - 1 - i) * 82 * s));
    },
  },
  teleprompter: {
    sample: { line1: 'Thanks for coming tonight.', line2: 'Our first slide shows', line3: 'last year\'s results.' },
    label: 'Teleprompter (current line highlighted)',
    draw(ctx, w, h, s, hud) {
      font(ctx, 600, 60 * s); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const lines = [hud.line1, hud.line2, hud.line3].filter(Boolean);
      lines.forEach((ln, i) => {
        const y = h * (0.2 + i * 0.3);
        if (i === 1) { ctx.fillRect(w * 0.03, y - 44 * s, w * 0.94, 88 * s); ctx.save(); ctx.fillStyle = hud.background; ctx.fillText(ln, w * 0.06, y); ctx.restore(); }
        else { ctx.globalAlpha = 0.55; ctx.fillText(ln, w * 0.06, y); ctx.globalAlpha = 1; }
      });
    },
  },
  compass: {
    sample: { line1: '', line2: '', line3: '' },
    label: 'Compass heading tape',
    draw(ctx, w, h, s, hud) {
      const hd = ((hud.heading ?? 72) % 360 + 360) % 360, span = 90, pxPerDeg = w / span;
      ctx.lineWidth = 4 * s; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      for (let d = Math.ceil((hd - span / 2) / 5) * 5; d <= hd + span / 2; d += 5) {
        const x = w / 2 + (d - hd) * pxPerDeg, major = d % 15 === 0;
        ctx.beginPath(); ctx.moveTo(x, h * 0.12); ctx.lineTo(x, h * (major ? 0.32 : 0.22)); ctx.stroke();
        const n = ((d % 360) + 360) % 360, card = { 0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW' }[n];
        if (card) { font(ctx, 700, 54 * s); ctx.fillText(card, x, h * 0.36); } else if (major) { font(ctx, 500, 34 * s); ctx.fillText(String(n), x, h * 0.36); }
      }
      ctx.beginPath(); ctx.moveTo(w / 2, h * 0.58); ctx.lineTo(w / 2 - 20 * s, h * 0.7); ctx.lineTo(w / 2 + 20 * s, h * 0.7); ctx.closePath(); ctx.fill();
      font(ctx, 700, 80 * s); ctx.textBaseline = 'alphabetic'; ctx.fillText(`${Math.round(hd)}°`, w / 2, h * 0.95);
    },
  },
  speed: {
    sample: { line1: '', line2: '', line3: 'km/h' },
    label: 'Speed gauge (cycling / driving)',
    draw(ctx, w, h, s, hud) {
      const v = hud.speed ?? 24, vmax = hud.speedMax ?? 50, cx = w / 2, cy = h * 0.86, r = Math.min(w * 0.42, h * 0.72);
      const a0 = Math.PI, a1 = Math.PI + Math.PI * Math.max(0, Math.min(1, v / vmax));
      ctx.lineWidth = 10 * s; ctx.globalAlpha = 0.35; ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI); ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 22 * s; ctx.beginPath(); ctx.arc(cx, cy, r, a0, a1); ctx.stroke();
      ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      font(ctx, 700, 150 * s); ctx.fillText(String(Math.round(v)), cx, cy - 10 * s);
      font(ctx, 600, 40 * s); ctx.fillText(hud.line3 || 'km/h', cx, cy + 0 * s + 2);
    },
  },
};

// default text for the plain text style (restored when it is picked again)
export const TEXT_SAMPLE = { line1: '12:45', line2: 'NEXT 200 m', line3: '64 BPM' };

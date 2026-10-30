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

export function renderHud(canvas, hud, oled, { mirrored = false } = {}) {
  const { w, h } = hudCanvasSize(oled);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = hud.background;
  ctx.fillRect(0, 0, w, h);
  if (mirrored) { ctx.translate(w, 0); ctx.scale(-1, 1); }
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

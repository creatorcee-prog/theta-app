// First-person view from the right entrance pupil, drawn in head-fixed
// angular coordinates (linear in degrees). The HUD is placed only where the
// tracer found rays entering the pupil; clipped regions are shown as such.

import { renderHud } from './hudContent.js';

const H_MIN = -55, H_MAX = 75, V_MIN = -42, V_MAX = 48;

export class FirstPersonView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.mode = 'hud'; // normal | hud | off | overlay
    this.hud = document.createElement('canvas');
    this.lastResults = null;
    this.lastCoverage = null;
    new ResizeObserver(() => this.draw()).observe(canvas);
  }

  // canvas client coordinates -> head-fixed angles (degrees)
  toAngles(clientX, clientY) {
    if (!this.map) return null;
    const r = this.canvas.getBoundingClientRect();
    const x = (clientX - r.left) * this.map.dpr, y = (clientY - r.top) * this.map.dpr;
    return { h: (x - this.map.ox) / this.map.scale + H_MIN, v: V_MAX - (y - this.map.oy) / this.map.scale };
  }

  set(results, coverage, diagnostics) {
    this.lastResults = results; this.lastCoverage = coverage; this.lastDiag = diagnostics;
    this.draw();
  }

  draw() {
    const c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const ctx = this.ctx;
    // keep aspect: fit angular window
    const spanH = H_MAX - H_MIN, spanV = V_MAX - V_MIN;
    const scale = Math.min(w / spanH, h / spanV);
    const ox = (w - spanH * scale) / 2, oy = (h - spanV * scale) / 2;
    const X = (hd) => ox + (hd - H_MIN) * scale;
    const Y = (vd) => oy + (V_MAX - vd) * scale;
    this.map = { X, Y, scale, ox, oy, dpr };
    ctx.save();
    ctx.clearRect(0, 0, w, h);
    const R = this.lastResults, C = this.lastCoverage;
    const mode = this.mode;

    // ---------------- world
    if (mode !== 'overlay') this.drawWorld(ctx, X, Y, w, h, scale);
    else { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h); }

    // ---------------- glasses hardware (not in naked-eye "normal" mode)
    if (C && mode !== 'normal' && mode !== 'overlay') {
      // lens outline + rim
      const lo = C.lens.angularOutline;
      ctx.lineWidth = Math.max(4, 3 * scale);
      ctx.strokeStyle = 'rgba(30,34,42,0.95)';
      ctx.beginPath();
      lo.forEach(([hd, vd], i) => (i ? ctx.lineTo(X(hd), Y(vd)) : ctx.moveTo(X(hd), Y(vd))));
      ctx.closePath(); ctx.stroke();
      // hardware silhouettes
      for (const [k, o] of Object.entries(C.occlusion)) {
        if (!o?.hull || o.hull.length < 3) continue;
        ctx.beginPath();
        o.hull.forEach(([hd, vd], i) => (i ? ctx.lineTo(X(hd), Y(vd)) : ctx.moveTo(X(hd), Y(vd))));
        ctx.closePath();
        if (k === 'prism') {
          ctx.fillStyle = 'rgba(160,215,255,0.18)'; ctx.fill();
          ctx.strokeStyle = 'rgba(190,230,255,0.85)'; ctx.lineWidth = 1.5 * (w / 600); ctx.stroke();
        } else {
          ctx.fillStyle = 'rgba(18,20,24,0.92)'; ctx.fill();
        }
      }
    }

    // ---------------- HUD
    const showHud = mode === 'hud' || mode === 'overlay';
    if (R && showHud) this.drawHud(ctx, X, Y, scale, R, C);

    // ---------------- annotations
    if (C) this.drawAnnotations(ctx, X, Y, scale, R, C, w, h);
    ctx.restore();
  }

  drawWorld(ctx, X, Y, w, h, scale) {
    const sky = ctx.createLinearGradient(0, Y(V_MAX), 0, Y(0));
    sky.addColorStop(0, '#6d9fd6'); sky.addColorStop(1, '#cfe2f3');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, w, Y(0));
    const ground = ctx.createLinearGradient(0, Y(0), 0, h);
    ground.addColorStop(0, '#8a8f83'); ground.addColorStop(1, '#4b5048');
    ctx.fillStyle = ground; ctx.fillRect(0, Y(0), w, h - Y(0));
    // buildings (deterministic)
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let hd = H_MIN; hd < H_MAX; ) {
      const bw = 4 + rnd() * 9, bh = 3 + rnd() * 14;
      if (Math.abs(hd + bw / 2) > 9) {
        const g = 120 + Math.floor(rnd() * 60);
        ctx.fillStyle = `rgb(${g - 10},${g},${g + 12})`;
        ctx.fillRect(X(hd), Y(bh), bw * scale, bh * scale);
        ctx.fillStyle = 'rgba(255,255,255,0.25)';
        for (let wy = 1.2; wy < bh - 1; wy += 2.2) for (let wx = 0.8; wx < bw - 1; wx += 1.8) ctx.fillRect(X(hd + wx), Y(wy + 0.8), 0.8 * scale, 0.8 * scale);
      }
      hd += bw + 0.5;
    }
    // road converging to the vanishing point
    ctx.fillStyle = '#3d4044';
    ctx.beginPath(); ctx.moveTo(X(-1), Y(0)); ctx.lineTo(X(1), Y(0)); ctx.lineTo(X(40), Y(V_MIN)); ctx.lineTo(X(-40), Y(V_MIN)); ctx.closePath(); ctx.fill();
    ctx.strokeStyle = '#e8e2c8'; ctx.lineWidth = Math.max(1, 0.5 * scale); ctx.setLineDash([2 * scale, 2 * scale]);
    ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(0), Y(V_MIN)); ctx.stroke(); ctx.setLineDash([]);
    // a pedestrian at the centre of vision (central area must stay clear)
    ctx.fillStyle = '#2b2f36';
    ctx.beginPath(); ctx.arc(X(2.5), Y(1.6), 0.45 * scale, 0, Math.PI * 2); ctx.fill();
    ctx.fillRect(X(2.1), Y(1.1), 0.8 * scale, 2.6 * scale);
  }

  drawHud(ctx, X, Y, scale, R, C) {
    const params = R.system.params;
    renderHud(this.hud, params.hud, params.oled, { mirrored: params.hud.driverFlip });
    const TW = this.hud.width, TH = this.hud.height;
    const nx = params.sim.pixelsX, ny = params.sim.pixelsY;
    const by = new Map(R.pixelResults.map((p) => [`${p.i},${p.j}`, p]));
    const maxPow = Math.max(1e-12, ...R.pixelResults.map((p) => p.pupilPower));
    // blur: residual defocus for this wearer's eye (prescription + focusing
    // range, from Diagnostics) plus the traced aberration spread
    let blurDeg = this.lastDiag?.focus?.blurDeg;
    if (blurDeg == null) blurDeg = R.pixelResults.some((p) => p.vergence) ? 0 : 3;
    const blurPx = Math.min(40, blurDeg * scale * 0.5);
    this.layer ??= document.createElement('canvas');
    const L = this.layer;
    if (L.width !== ctx.canvas.width || L.height !== ctx.canvas.height) { L.width = ctx.canvas.width; L.height = ctx.canvas.height; }
    const lctx = L.getContext('2d');
    lctx.clearRect(0, 0, L.width, L.height);
    const bright = params.oled.brightness / 100;
    for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
      const q = [by.get(`${i},${j}`), by.get(`${i + 1},${j}`), by.get(`${i + 1},${j + 1}`), by.get(`${i},${j + 1}`)];
      if (q.some((p) => !p || !p.availableAngles)) continue;
      const allVis = q.every((p) => p.visible);
      const anyVis = q.some((p) => p.visible);
      if (!anyVis) continue;
      const pw = q.reduce((s, p) => s + p.pupilPower, 0) / 4 / maxPow;
      lctx.globalAlpha = Math.min(1, (allVis ? 1 : 0.45) * (0.35 + 0.65 * pw) * (0.4 + 0.8 * bright));
      // texture coords of the pixel sample (u right, v up on the OLED)
      const tc = q.map((p) => [((p.u + 1) / 2) * TW, ((1 - p.v) / 2) * TH]);
      const sc = q.map((p) => { const a = p.visible ? p.angles : p.availableAngles; return [X(a.h), Y(a.v)]; });
      drawTexturedTri(lctx, this.hud, tc[0], tc[1], tc[2], sc[0], sc[1], sc[2]);
      drawTexturedTri(lctx, this.hud, tc[0], tc[2], tc[3], sc[0], sc[2], sc[3]);
    }
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    if (blurPx > 0.6) ctx.filter = `blur(${blurPx.toFixed(1)}px)`;
    ctx.drawImage(L, 0, 0);
    ctx.restore();
    this.blurDeg = blurDeg;
  }

  drawAnnotations(ctx, X, Y, scale, R, C, w) {
    const params = R?.system.params;
    const t = params?.targets;
    const fs = Math.max(10, Math.round(w / 70));
    ctx.font = `500 ${fs}px "IBM Plex Mono", ui-monospace, monospace`;
    ctx.textBaseline = 'top';
    // the wearer's HUD zone and, when computed, where the HUD can be placed
    const z = params?.targets?.zone;
    if (z) {
      ctx.fillStyle = 'rgba(60, 210, 110, 0.10)';
      ctx.fillRect(X(z.hMin), Y(z.vMax), (z.hMax - z.hMin) * scale, (z.vMax - z.vMin) * scale);
      ctx.strokeStyle = 'rgba(60, 210, 110, 0.9)'; ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5;
      ctx.strokeRect(X(z.hMin), Y(z.vMax), (z.hMax - z.hMin) * scale, (z.vMax - z.vMin) * scale);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(60, 210, 110, 0.95)';
      ctx.fillText('your HUD zone (click to aim the HUD)', X(z.hMin) + 4, Y(z.vMin) - fs - 4);
    }
    if (this.reach?.length) {
      for (const pt of this.reach) {
        const ok = pt.buildable && pt.visible >= 0.999, part = pt.visible > 0;
        ctx.beginPath(); ctx.arc(X(pt.h), Y(pt.v), Math.max(4, scale * 1.4), 0, Math.PI * 2);
        ctx.fillStyle = ok ? 'rgba(60,210,110,0.9)' : part ? 'rgba(242,201,76,0.9)' : 'rgba(255,90,79,0.9)';
        ctx.fill(); ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.lineWidth = 1; ctx.stroke();
      }
    }
    // central clear zone
    if (t) {
      ctx.strokeStyle = 'rgba(255,255,255,0.8)'; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.ellipse(X(0), Y(0), t.centralClear * scale, t.centralClear * scale, 0, 0, Math.PI * 2); ctx.stroke();
      // target HUD box
      ctx.strokeStyle = 'rgba(242,201,76,0.95)';
      ctx.strokeRect(X(t.azimuth - t.hfov / 2), Y(t.elevation + t.vfov / 2), t.hfov * scale, t.vfov * scale);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(242,201,76,0.95)';
      ctx.fillText(`target ${t.hfov}°×${t.vfov}° @ ${t.azimuth}°`, X(t.azimuth - t.hfov / 2) + 3, Y(t.elevation + t.vfov / 2) - fs - 3);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.fillText(`central ${t.centralClear}°`, X(0) - 30, Y(-t.centralClear) + 3);
    }
    // visible HUD boundary + clipped pixels
    if (C.field.hull?.length >= 3 && this.mode !== 'normal' && this.mode !== 'off') {
      ctx.strokeStyle = '#32d27a'; ctx.lineWidth = 1.5;
      ctx.beginPath();
      C.field.hull.forEach(([hd, vd], i) => (i ? ctx.lineTo(X(hd), Y(vd)) : ctx.moveTo(X(hd), Y(vd))));
      ctx.closePath(); ctx.stroke();
      ctx.fillStyle = '#32d27a';
      ctx.fillText(`HUD ${C.field.hfov.toFixed(1)}°×${C.field.vfov.toFixed(1)}°`, X(C.field.hMax) + 4, Y(C.field.vMax));
      ctx.fillText(`h ${C.field.hMin.toFixed(1)}…${C.field.hMax.toFixed(1)}°`, X(C.field.hMax) + 4, Y(C.field.vMax) + fs + 2);
      ctx.fillText(`v ${C.field.vMin.toFixed(1)}…${C.field.vMax.toFixed(1)}°`, X(C.field.hMax) + 4, Y(C.field.vMax) + 2 * (fs + 2));
      const at2m = 2 * 2000 * Math.tan(((C.field.hfov / 2) * Math.PI) / 180);
      ctx.fillText(`≈ ${(at2m / 10).toFixed(0)} cm wide at 2 m`, X(C.field.hMax) + 4, Y(C.field.vMax) + 3 * (fs + 2));
    }
    if (R && this.mode !== 'normal' && this.mode !== 'off') {
      for (const p of R.pixelResults) {
        if (p.visible || !p.availableAngles) continue;
        const x = X(p.availableAngles.h), y = Y(p.availableAngles.v);
        ctx.strokeStyle = '#ff5a4f'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x - 3, y - 3); ctx.lineTo(x + 3, y + 3); ctx.moveTo(x + 3, y - 3); ctx.lineTo(x - 3, y + 3); ctx.stroke();
      }
    }
    // axis ticks
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    for (let a = -40; a <= 70; a += 10) { ctx.fillRect(X(a), Y(V_MIN), 1, 6); ctx.fillText(`${a}°`, X(a) + 2, Y(V_MIN) - fs - 6); }
    ctx.fillText('nasal ←', X(H_MIN) + 4, Y(V_MAX) + 4);
    ctx.textAlign = 'right'; ctx.fillText('temporal →', X(H_MAX) - 4, Y(V_MAX) + 4); ctx.textAlign = 'left';
    ctx.fillText(`mode: ${{ normal: 'normal vision (no glasses)', hud: 'HUD enabled', off: 'HUD disabled', overlay: 'HUD overlay only' }[this.mode]}`, X(H_MIN) + 4, Y(V_MAX) + fs + 8);
  }
}

// Affine-map triangle (s0,s1,s2) of the source image onto (d0,d1,d2).
function drawTexturedTri(ctx, img, s0, s1, s2, d0, d1, d2) {
  const sx1 = s1[0] - s0[0], sy1 = s1[1] - s0[1], sx2 = s2[0] - s0[0], sy2 = s2[1] - s0[1];
  const du1 = d1[0] - d0[0], dv1 = d1[1] - d0[1], du2 = d2[0] - d0[0], dv2 = d2[1] - d0[1];
  const det = sx1 * sy2 - sx2 * sy1;
  if (Math.abs(det) < 1e-9) return;
  const a = (du1 * sy2 - du2 * sy1) / det, c = (du2 * sx1 - du1 * sx2) / det;
  const b = (dv1 * sy2 - dv2 * sy1) / det, d = (dv2 * sx1 - dv1 * sx2) / det;
  const e = d0[0] - a * s0[0] - c * s0[1], f = d0[1] - b * s0[0] - d * s0[1];
  // grow the clip triangle by ~0.6 px around its centroid to hide seams
  const cx = (d0[0] + d1[0] + d2[0]) / 3, cy = (d0[1] + d1[1] + d2[1]) / 3;
  const grow = (p) => { const dx = p[0] - cx, dy = p[1] - cy, l = Math.hypot(dx, dy) || 1; return [p[0] + (dx / l) * 0.6, p[1] + (dy / l) * 0.6]; };
  const g0 = grow(d0), g1 = grow(d1), g2 = grow(d2);
  ctx.save();
  ctx.beginPath(); ctx.moveTo(g0[0], g0[1]); ctx.lineTo(g1[0], g1[1]); ctx.lineTo(g2[0], g2[1]); ctx.closePath();
  ctx.clip();
  ctx.transform(a, b, c, d, e, f);
  ctx.drawImage(img, 0, 0);
  ctx.restore();
}

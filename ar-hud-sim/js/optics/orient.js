// Image orientation as the eye sees it, and the display roll that makes it
// upright. Uses the traced apparent angle of each sampled pixel and fits
//   h = a u + b v + c,   vAng = d u + e v + f     (u, v: display coords in [-1, 1])
// det < 0 means the optics mirror the image (the display driver can flip it).

import { Vector3, Quaternion } from 'three';
import { runSimulation } from './Simulation.js';
import { quatFromEulerDeg, eulerDegFromBasis } from './OpticalComponents.js';

function solve3(M, r) {
  const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const D = det(M);
  if (Math.abs(D) < 1e-12) return [NaN, NaN, NaN];
  return [0, 1, 2].map((k) => det(M.map((row, i) => row.map((x, j) => (j === k ? r[i] : x)))) / D);
}

/** Affine fit over pixel results; null if fewer than 3 samples. */
export function fitOrientation(pixelResults) {
  const pts = pixelResults.filter((p) => p.availableAngles);
  if (pts.length < 3) return null;
  const fit = (get) => {
    const M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], r = [0, 0, 0];
    for (const p of pts) {
      const x = [p.u, p.v, 1], y = get(p);
      for (let i = 0; i < 3; i++) { r[i] += x[i] * y; for (let j = 0; j < 3; j++) M[i][j] += x[i] * x[j]; }
    }
    return solve3(M, r);
  };
  const [a, b] = fit((p) => p.availableAngles.h);
  const [d, e] = fit((p) => p.availableAngles.v);
  if (![a, b, d, e].every(Number.isFinite)) return null;
  const det = a * e - b * d;
  // as shown after the driver's optional left-right flip (u -> -u)
  return { a, b, d, e, det, rollDeg: (Math.atan2(d, a) * 180) / Math.PI };
}

function measure(p) {
  const q = structuredClone(p);
  q.sim = { ...q.sim, pixelsX: 5, pixelsY: 3, raysPerPixel: Math.max(40, p.sim.raysPerPixel ?? 40), wavelengths: 'mono', ghosts: false };
  return fitOrientation(runSimulation(q).pixelResults);
}

function rollOled(p, deg) {
  const q = quatFromEulerDeg(p.oled.rot);
  const z = new Vector3(0, 0, 1).applyQuaternion(q);
  const r = new Quaternion().setFromAxisAngle(z, (deg * Math.PI) / 180).multiply(q);
  p.oled.rot = eulerDegFromBasis(new Vector3(1, 0, 0).applyQuaternion(r), new Vector3(0, 1, 0).applyQuaternion(r), z);
}

/**
 * Rolls the OLED about its own axis until the image's horizontal axis is
 * level for the eye, and sets the driver flip when the optics mirror it.
 * Returns the remaining tilt and shear (degrees). Mutates p.
 */
export function levelImage(p, { tolDeg = 0.3, maxIter = 4 } = {}) {
  let m = measure(p);
  if (!m) return { ok: false };
  p.hud.driverFlip = m.det < 0;
  const flip = (f) => (p.hud.driverFlip ? { ...f, a: -f.a, d: -f.d, b: f.b, e: f.e } : f);
  const tilt = (f) => { const g = flip(f); return (Math.atan2(g.d, g.a) * 180) / Math.PI; };
  let t = tilt(m);
  for (let i = 0; i < maxIter && Math.abs(t) > tolDeg; i++) {
    const before = { ...p.oled.rot };
    rollOled(p, -t);
    const m2 = measure(p);
    if (!m2) { p.oled.rot = before; break; }
    let t2 = tilt(m2);
    if (Math.abs(t2) > Math.abs(t)) { // wrong sense: roll the other way instead
      p.oled.rot = before; rollOled(p, t);
      const m3 = measure(p); if (!m3) { p.oled.rot = before; break; }
      m = m3; t2 = tilt(m3);
    } else m = m2;
    t = t2;
  }
  const g = flip(m);
  // shear: how far the image's vertical axis leans once the horizontal is level
  const shearDeg = (Math.atan2(g.b, g.e) * 180) / Math.PI - (Math.atan2(-g.d, g.a) * 180) / Math.PI;
  return { ok: true, tiltDeg: t, shearDeg, mirrored: p.hud.driverFlip };
}

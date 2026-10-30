// Image orientation as the eye sees it, and the display roll that makes it
// upright. Uses the traced apparent angle of each sampled pixel and fits
//   h = a u + b v + c,   vAng = d u + e v + f     (u, v: display coords in [-1, 1])
// det < 0 means the optics mirror the image (the display driver can flip it).

import { Vector3, Quaternion } from 'three';
import { runSimulation } from './Simulation.js';
import { quatFromEulerDeg, eulerDegFromBasis } from './OpticalComponents.js';

import { fitOrientation } from './orientFit.js';
export { fitOrientation };

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

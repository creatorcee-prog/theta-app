// Finds the OLED-to-collimator distance that gives a requested vergence at
// the pupil, using the real tracer (works for ideal and real lenses).

import { runSimulation } from './Simulation.js';

function centreVergence(params) {
  const p = structuredClone(params);
  p.sim = { ...p.sim, pixelsX: 3, pixelsY: 3, raysPerPixel: 90, wavelengths: 'mono', ghosts: false };
  p.parts = []; // focus does not depend on parts; skip their absorbers
  const r = runSimulation(p);
  const c = r.pixelResults.find((x) => x.i === 1 && x.j === 1);
  return c?.vergence?.mean ?? null;
}

/** Returns { ok, distance, vergence, iterations, reason }. */
export function solveFocusDistance(params, targetV, { tol = 0.03, maxIter = 8 } = {}) {
  if (!params.collimator.enabled) return { ok: false, reason: 'No collimator installed.' };
  const f = params.collimator.focalLength;
  let d0 = params.collimator.distance, v0 = centreVergence(params);
  if (v0 == null) return { ok: false, reason: 'Too few rays reach the pupil to measure vergence. Align the chain first.' };
  // thin-lens slope estimate: dV/dd ~ 1000/f^2 D per mm (moving the OLED away converges)
  let d1 = d0 + (targetV - v0) / (1000 / (f * f));
  let v1 = null;
  for (let i = 0; i < maxIter; i++) {
    d1 = Math.max(0.5, Math.min(3 * f, d1));
    v1 = centreVergence({ ...params, collimator: { ...params.collimator, distance: d1 } });
    if (v1 == null) return { ok: false, reason: 'Rays stopped reaching the pupil while refocusing.', distance: d0, vergence: v0, iterations: i + 1 };
    if (Math.abs(v1 - targetV) <= tol) return { ok: true, distance: d1, vergence: v1, iterations: i + 1 };
    const slope = (v1 - v0) / (d1 - d0 || 1e-6);
    d0 = d1; v0 = v1;
    d1 = d1 + (targetV - v1) / (Math.abs(slope) > 1e-6 ? slope : 1000 / (f * f));
  }
  return { ok: Math.abs(v1 - targetV) <= 0.15, distance: d0, vergence: v0, iterations: maxIter, reason: 'Did not fully converge.' };
}

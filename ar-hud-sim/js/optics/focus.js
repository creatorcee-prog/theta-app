// Finds the OLED-to-collimator distance that gives a requested vergence at
// the pupil, using the real tracer (works for ideal and real lenses).

import { runSimulation } from './Simulation.js';
import { assessFieldFocus } from './Vision.js';

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

function fieldResidual(params, distance) {
  const p = structuredClone(params);
  p.collimator.distance = distance;
  p.sim = { ...p.sim, pixelsX: 5, pixelsY: 3, raysPerPixel: 60, wavelengths: 'mono', ghosts: false };
  p.parts = [];
  const r = runSimulation(p);
  const v = r.pixelResults.map((x) => x.vergence).filter(Boolean);
  if (v.length < 3) return Infinity;
  return assessFieldFocus(v, p.eye).p90;
}

/** Golden-section search of the OLED distance minimising the whole-field
 *  90th-percentile defocus for the wearer's eye. */
export function solveFieldFocus(params, { span = 2.5, iters = 14 } = {}) {
  if (!params.collimator.enabled) return { ok: false, reason: 'No collimator installed.' };
  const d0 = params.collimator.distance;
  let a = Math.max(0.5, d0 - span), b = d0 + span * 0.4;
  const g = (Math.sqrt(5) - 1) / 2;
  let c = b - g * (b - a), d = a + g * (b - a);
  let fc = fieldResidual(params, c), fd = fieldResidual(params, d);
  for (let i = 0; i < iters; i++) {
    if (fc < fd) { b = d; d = c; fd = fc; c = b - g * (b - a); fc = fieldResidual(params, c); }
    else { a = c; c = d; fc = fd; d = a + g * (b - a); fd = fieldResidual(params, d); }
  }
  const distance = (a + b) / 2, residual = fieldResidual(params, distance);
  return { ok: Number.isFinite(residual), distance, residual, reason: Number.isFinite(residual) ? '' : 'Too few rays reach the pupil to measure focus.' };
}

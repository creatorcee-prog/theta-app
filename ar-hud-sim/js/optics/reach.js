// Reach map: where inside the wearer's HUD zone can this hardware put a
// fully visible, buildable HUD? For each aim point the chain is re-aligned
// (same parts, new direction), refocused paraxially and traced.

import { alignChain } from '../config/defaults.js';
import { computeCollimator, computeOled } from './OpticalComponents.js';
import { runSimulation } from './Simulation.js';
import { analyzeCoverage } from './CoverageAnalyzer.js';
import { runDiagnostics } from './Diagnostics.js';

export const REACH_CHECKS = ['prismLens', 'prismClear', 'hwCentral', 'oledFit', 'lensPod', 'armFit', 'headHousing'];

export function reachPoints(zone, nx = 5, ny = 5) {
  const pts = [];
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    pts.push({ h: zone.hMin + ((i + 0.5) / nx) * (zone.hMax - zone.hMin), v: zone.vMin + ((j + 0.5) / ny) * (zone.vMax - zone.vMin) });
  }
  return pts;
}

export function evaluateAim(params, h, v) {
  let p = structuredClone(params);
  p.intent = { ...p.intent, azimuth: h, elevation: v };
  p = alignChain(p);
  const c = computeCollimator(p.collimator, computeOled(p.oled), p.prism.n);
  if (c?.valid && p.collimator.mode !== 'thin') p.collimator.distance = c.frontFocalDistance;
  p.sim = { ...p.sim, pixelsX: 7, pixelsY: 4, raysPerPixel: 24, wavelengths: 'mono', ghosts: false };
  const r = runSimulation(p);
  const cov = analyzeCoverage(r);
  const d = runDiagnostics(r, cov);
  const failed = REACH_CHECKS.filter((id) => { const c2 = d.checks.find((x) => x.id === id); return c2 && c2.status !== 'pass'; });
  const visible = cov.field.totalPixels ? (cov.field.imagedInZone ?? cov.field.inZone) / cov.field.totalPixels : 0;
  return { h, v, visible, buildable: failed.length === 0, failed, center: cov.field.hCenter != null ? [cov.field.hCenter, cov.field.vCenter] : null };
}

// Runs in slices so the page stays responsive; onProgress(done, total).
export async function mapReach(params, { nx = 5, ny = 5, onProgress } = {}) {
  const zone = params.targets.zone;
  const pts = reachPoints(zone, nx, ny);
  const out = [];
  for (let k = 0; k < pts.length; k++) {
    out.push(evaluateAim(params, pts[k].h, pts[k].v));
    onProgress?.(k + 1, pts.length);
    if (typeof requestAnimationFrame !== 'undefined') await new Promise((res) => setTimeout(res, 0));
  }
  return out;
}

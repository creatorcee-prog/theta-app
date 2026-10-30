// Headless run of the default configuration; prints the key numbers.
// Usage: node scripts/smoke.mjs
import { defaultParams } from '../js/config/defaults.js';
import { runSimulation } from '../js/optics/Simulation.js';

const p = defaultParams();
console.log('prism', p.prism.pos, p.prism.rot, '\noled', p.oled.pos, p.oled.rot, p._alignInfo);
const r = runSimulation(p);
console.log('ms', r.elapsedMs.toFixed(0), r.counts, r.power);
console.log('hyp', r.hyp.hits, r.hyp.tir, r.hyp.minInc, r.hyp.maxInc);
console.log('chief', r.chief.outcome, r.chief.events.map((e) => [e.obj, e.face, e.incidenceDeg?.toFixed(2), e.tir]));
const vis = r.pixelResults.filter((x) => x.visible);
console.log('visible px', vis.length, '/', r.pixelResults.length);
if (vis.length) {
  const hs = vis.map((x) => x.angles.h), vs = vis.map((x) => x.angles.v);
  console.log('h', Math.min(...hs).toFixed(1), Math.max(...hs).toFixed(1), 'v', Math.min(...vs).toFixed(1), Math.max(...vs).toFixed(1));
}
const av = r.pixelResults.filter((x) => x.availableAngles);
if (av.length) console.log('avail h', Math.min(...av.map((x) => x.availableAngles.h)).toFixed(1), Math.max(...av.map((x) => x.availableAngles.h)).toFixed(1));
console.log('verg', r.pixelResults.slice(20, 25).map((x) => x.vergence && [x.vergence.mean.toFixed(2), x.vergence.residualMrad.toFixed(2)]));
console.log('cavity', r.system.glasses.cavity.min, r.system.glasses.cavity.max, 'pupil', r.system.eye.pupilCenter);

const { analyzeCoverage } = await import('../js/optics/CoverageAnalyzer.js');
const { runDiagnostics } = await import('../js/optics/Diagnostics.js');
const cov = analyzeCoverage(r);
const dg = runDiagnostics(r, cov);
for (const c of dg.checks) console.log(`[${c.status.padEnd(4)}] ${c.label}: ${c.value}${c.explain ? ' — ' + c.explain : ''}`);
console.log(dg.summary, 'lens fp', cov.lens.footprintArea.toFixed(1), 'occl', cov.occlusion.prism.minRadius.toFixed(1));

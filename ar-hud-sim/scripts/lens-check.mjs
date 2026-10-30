// Compare the real plano-convex collimators against the ideal thin lens.
// Usage: node scripts/lens-check.mjs
import { defaultParams } from '../js/config/defaults.js';
import { runSimulation } from '../js/optics/Simulation.js';
import { analyzeCoverage } from '../js/optics/CoverageAnalyzer.js';
import { runDiagnostics } from '../js/optics/Diagnostics.js';
import { computeCollimator, computeOled } from '../js/optics/OpticalComponents.js';

for (const [mode, k] of [['thin', 0], ['spherical', 0], ['aspheric', -0.43], ['aspheric', -1]]) {
  const p = defaultParams();
  p.prism.coating = 'mirror'; // isolate the lens from TIR leakage
  p.collimator.mode = mode; p.collimator.conicK = k;
  const c = computeCollimator(p.collimator, computeOled(p.oled), p.prism.n);
  p.collimator.distance = c.frontFocalDistance;
  const r = runSimulation(p);
  const cov = analyzeCoverage(r);
  const d = runDiagnostics(r, cov);
  const g = (id) => d.checks.find((x) => x.id === id);
  // per-pixel apparent angle at display edges (availableAngles)
  const mid = r.pixelResults.filter((x) => x.availableAngles && x.i === 4);
  console.log(`${mode} k=${k} t=${c.thickness?.toFixed(2)} FFD=${c.frontFocalDistance.toFixed(2)}`,
    '| FOV', cov.field.hfov?.toFixed(1), cov.field.vfov?.toFixed(1), 'avail', cov.field.availHfov?.toFixed(1), cov.field.availVfov?.toFixed(1),
    '|', g('vergence').value, '|', g('vergence').explain.slice(0, 120));
  console.log('   column i=4 v-angles:', mid.map((x) => x.availableAngles.v.toFixed(1)).join(' '));
}

// Scores a design against the four product goals. Every score is computed
// from traced results and the parts list; nothing is assumed to pass.
//
//   pupil coverage  share of sampled display pixels that reach the pupil (target 100%)
//   weight          48 g / worn weight, capped at 100% (target <= 48 g)
//   cost            $200 / parts total, capped at 100% (target < $200)
//   structure       share of build/fit checks that pass (target 100%)
// Overall = mean of the four. A make "meets the bar" at >= 80% overall.

import { bomTotals } from '../model/parts.js';

export const GOALS = { weightG: 48, costUSD: 200, overallBar: 0.8 };

// Checks that decide whether the hardware can be built and worn as modelled.
export const STRUCTURE_CHECKS = [
  ['chiefMiss', 'Display centre lands in the pupil'],
  ['prismLens', 'Prism clears the spectacle lens'],
  ['prismClear', 'Prism clears cornea and lashes'],
  ['hwCentral', 'Hardware keeps central vision clear'],
  ['oledFit', 'OLED module fits in the housing'],
  ['lensPod', 'Lens + barrel clear the head'],
  ['armFit', 'Prism held by an arm to the housing'],
  ['driverFit', 'Driver board fits in the housing'],
  ['headHousing', 'Housing clears the head'],
  ['virtualImage', 'Focusable virtual image'],
  ['left', 'No light in the left pupil'],
  ['guideTIR', 'Light stays guided in the waveguide'],
  ['seeThrough', 'World stays visible through the waveguide'],
];

export function scoreDesign(results, coverage, diag, params) {
  const checks = Object.fromEntries(diag.checks.map((c) => [c.id, c]));
  const tot = bomTotals(params.bom ?? []);

  // pixels that reach the pupil AND appear inside the wearer's HUD zone
  // (and arrive as one coherent image point, not light scrambled by extra reflections)
  const vis = coverage.field.imagedInZone ?? coverage.field.inZone ?? coverage.field.visiblePixels, all = coverage.field.totalPixels;
  const pupil = all ? vis / all : 0;
  const weight = tot.grams > 0 ? Math.min(1, GOALS.weightG / tot.grams) : 1;
  const cost = tot.total > 0 ? Math.min(1, GOALS.costUSD / tot.total) : 1;

  const structural = [];
  for (const [id, label] of STRUCTURE_CHECKS) {
    const c = checks[id];
    if (!c) continue; // e.g. no driver board on the frame
    // "left" passes with stray light on the eyelid as long as none enters the pupil
    const ok = c.status === 'pass' || (id === 'left' && results.counts.leftPupil === 0);
    structural.push({ id, label, ok, value: c.value, explain: c.explain });
  }
  // every placed part: must not block the beam or cut into the head
  for (const c of diag.checks.filter((x) => x.id.startsWith('part-'))) structural.push({ id: c.id, label: c.label, ok: false, value: c.value, explain: c.explain });
  // the prism needs something holding it
  if (params.patch?.enabled) {
    const clip = (params.bom ?? []).some((b) => b.id === 'patchMount' && b.include !== false);
    structural.push({ id: 'prismMount', label: 'Mirror patch held on the lens', ok: clip, value: clip ? 'edge-bonded' : 'no', explain: clip ? '' : 'Add the edge bond / spacer dots that hold the patch behind the lens.' });
  } else if (params.waveguide?.enabled) {
    const clip = (params.bom ?? []).some((b) => b.id === 'guideClip' && b.include !== false);
    structural.push({ id: 'prismMount', label: 'Waveguide held by the rim', ok: clip, value: clip ? 'rim clip' : 'no', explain: clip ? '' : 'Add a rim clip (parts list) that holds the plate behind the lens with an air gap.' });
  } else {
    const mount = (params.parts ?? []).some((p) => p.attach === 'prism' && p.visible !== false);
    structural.push({ id: 'prismMount', label: 'Prism has a mount', ok: mount, value: mount ? 'yes' : 'no', explain: mount ? '' : 'Add a bracket attached to the prism.' });
  }
  const structure = structural.filter((s) => s.ok).length / structural.length;

  const goals = [
    { id: 'pupil', label: 'Pupil coverage in your zone', target: '100% of display', value: `${(100 * pupil).toFixed(0)}% (${vis}/${all} px)`, score: pupil, met: pupil >= 0.999 },
    { id: 'weight', label: 'Weight', target: `≤ ${GOALS.weightG} g`, value: `${tot.grams.toFixed(1)} g`, score: weight, met: tot.grams <= GOALS.weightG + 1e-9 },
    { id: 'cost', label: 'Cost', target: `< $${GOALS.costUSD}`, value: `$${tot.total.toFixed(2)}`, score: cost, met: tot.total < GOALS.costUSD },
    { id: 'structure', label: 'Feasible structure', target: 'all checks pass', value: `${structural.filter((s) => s.ok).length}/${structural.length} checks`, score: structure, met: structure >= 0.999 },
  ];
  const overall = goals.reduce((s, g) => s + g.score, 0) / goals.length;
  return { goals, overall, meetsBar: overall >= GOALS.overallBar, structural, totals: tot };
}

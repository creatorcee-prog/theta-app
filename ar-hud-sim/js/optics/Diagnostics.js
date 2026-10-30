// Engineering diagnostics: turns traced results + coverage analysis into
// pass / adjust / fail checks with short explanations.
// status: 'pass' (green, meets the modeled requirement), 'warn' (yellow,
// needs adjustment), 'fail' (red), 'info' (reported value, no requirement).

import { Vector3, Quaternion } from 'three';
import { pointInBox } from '../model/glassesGeometry.js';
import { assessFocus, assessFieldFocus, amplitudeFor } from './Vision.js';
import { computeHead } from '../model/head.js';
import { armSurfacePoints } from './CoverageAnalyzer.js';
import { bomTotals } from '../model/parts.js';

const f1 = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toFixed(1));
const f2 = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toFixed(2));

function grade(value, passFn, warnFn) {
  if (value == null || Number.isNaN(value)) return 'fail';
  if (passFn(value)) return 'pass';
  if (warnFn && warnFn(value)) return 'warn';
  return 'fail';
}

function closestApproach(origin, dir, point) {
  const t = Math.max(0, point.clone().sub(origin).dot(dir));
  return origin.clone().addScaledVector(dir, t).distanceTo(point);
}

function minDistanceToPrism(prism, p) {
  // distance from point to the prism solid (0 if inside), via faces
  let inside = true, best = Infinity;
  for (const f of Object.values(prism.faces)) {
    const d = p.clone().sub(f.centroid).dot(f.normal);
    if (d > 0) inside = false;
  }
  if (inside) return 0;
  for (const f of Object.values(prism.faces)) {
    const vs = f.vertices;
    // project onto plane, clamp to polygon by testing edges
    const d = p.clone().sub(vs[0]).dot(f.normal);
    const proj = p.clone().addScaledVector(f.normal, -d);
    let inPoly = true;
    for (let i = 0; i < vs.length; i++) {
      const a = vs[i], b = vs[(i + 1) % vs.length];
      if (new Vector3().subVectors(b, a).cross(new Vector3().subVectors(proj, a)).dot(f.normal) < 0) { inPoly = false; break; }
    }
    if (inPoly) best = Math.min(best, Math.abs(d));
    for (let i = 0; i < vs.length; i++) {
      const a = vs[i], b = vs[(i + 1) % vs.length];
      const ab = b.clone().sub(a);
      const t = Math.max(0, Math.min(1, p.clone().sub(a).dot(ab) / ab.lengthSq()));
      best = Math.min(best, a.clone().addScaledVector(ab, t).distanceTo(p));
    }
  }
  return best;
}

function boxCorners(center, q, size) {
  const out = [];
  for (const sx of [-0.5, 0.5]) for (const sy of [-0.5, 0.5]) for (const sz of [-0.5, 0.5]) {
    out.push(new Vector3(sx * size.x, sy * size.y, sz * size.z).applyQuaternion(q).add(center));
  }
  return out;
}

function solve3(M, r) {
  const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const D = det(M);
  if (Math.abs(D) < 1e-12) return [NaN, NaN, NaN];
  return [0, 1, 2].map((k) => det(M.map((row, i) => row.map((v, j) => (j === k ? r[i] : v)))) / D);
}

function insidePolygon([x, y], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function runDiagnostics(results, coverage) {
  const { system, chief, counts, power, hyp, critical, pixelResults } = results;
  const { params, prism, oled, collimator, glasses, eye } = system;
  const t = params.targets;
  const checks = [];
  const add = (group, id, label, value, status, explain = '', unit = '') => checks.push({ group, id, label, value, status, explain, unit });

  // ---------------- prism physics
  const crit = critical.bk7Deg;
  add('Prism', 'critical', 'BK7 critical angle (glass→air)', `${f2(crit)}°`, 'info',
    `θc = asin(1/n) with n = ${params.prism.n}.`);
  const guided = prism.kind === 'waveguide', patched = prism.kind === 'patch';
  const cname = guided ? 'Waveguide' : patched ? 'Mirror patch' : 'Prism';
  const chiefHyp = guided
    ? chief.events.find((e) => e.obj === 'guide' && (e.face === 'guideFront' || e.face === 'guideBack') && !e.entering && !e.facet)
    : chief.events.find((e) => e.obj === 'prism' && e.face === 'hypotenuse' && !e.entering);
  if (patched) {
    const pt = prism, P = params.patch;
    const hit = chief.events.find((e) => e.obj === 'patch' || (e.facet && e.obj === 'specLensR'));
    const bare = P.coating === 'bare' && pt.mode !== 'embedded';
    if (pt.mode === 'embedded') {
      const ok = pt.valid && pt.fitMargin >= 0.3;
      add('Fit', 'castFit', 'Partial mirror fits inside the lens', pt.valid ? `${f1(pt.fitMargin)} mm to the nearest surface` : 'no', ok ? 'pass' : 'fail',
        !pt.valid ? 'With this fold angle the display light would have to enter the lens from the front; the buried mirror cannot be lit from the temple.'
          : ok ? `Ø${P.diameter} mm mirror cast at ${f1(pt.incidenceDeg)}° incidence inside a ${f1(params.frame.lensThicknessR ?? params.frame.lensThickness)} mm right lens.`
            : `The tilted Ø${P.diameter} mm mirror pokes ${f1(-pt.fitMargin)} mm out of the ${f1(params.frame.lensThicknessR ?? params.frame.lensThickness)} mm lens: make the lens thicker or the mirror smaller.`);
    }
    add('Prism', 'chiefInc', 'Chief-ray incidence on the mirror patch', hit ? `${f1(hit.incidenceDeg)}°` : 'not reached', hit ? 'pass' : 'fail',
      hit ? `${bare ? `Bare glass (n ${P.glassN}): Fresnel reflection from both faces, R ${f1(100 * hit.R)}% at this angle (a thin plate keeps the two reflections within a fraction of a pixel).` : `Partial mirror R ${Math.round(100 * P.reflectance)}%.`} Off-axis, a spherical mirror (R ${P.radius} mm, f ${f1(pt.f)} mm) focuses tangential and sagittal rays at f·cos i and f / cos i: ≈ ${f1(pt.astigD)} D of built-in astigmatism at ${f1(pt.incidenceDeg)}°, before any correction by the collimator tilt or a conic shape.`
        : `The display-centre ray never reaches the patch (outcome: ${chief.outcome}). Check the alignment.`);
    const Rw = bare || (pt.mode === 'lensback' && P.coating === 'bare') ? (() => { const r0 = ((P.glassN - 1) / (P.glassN + 1)) ** 2; return (2 * r0) / (1 + r0); })() : P.reflectance;
    if (system.fold) {
      const fp = hyp.hits ? (100 * hyp.tir) / hyp.hits : null;
      add('Prism', 'foldTIR', 'Fold prism: total internal reflection', fp == null ? 'no hits' : `${f1(fp)}% of ${hyp.hits} hits`, grade(fp, (v) => v >= 99, (v) => v >= 90),
        fp == null ? 'No light reaches the fold prism hypotenuse.' : `Hypotenuse incidence ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}° against θc ${f1(crit)}°. A long focal length keeps the field inside the glass small enough for a stock 45° prism.`);
      const hb = system.hingeBlock;
      const problems = [];
      if (hb.gap > 1) problems.push(`is ${f1(hb.gap)} mm from the temple housing (not joined)`);
      if (hb.max.z > hb.frontZ + 0.5) problems.push(`sticks ${f1(hb.max.z - hb.frontZ)} mm out in front of the frame`);
      add('Fit', 'foldFit', 'Fold prism held in a hinge block', problems.length ? 'no' : 'yes', problems.length ? 'fail' : 'pass',
        problems.length ? `The block around the fold prism ${problems.join(' and ')}.` : `A ${f1(hb.size.x)} × ${f1(hb.size.y)} × ${f1(hb.size.z)} mm printed block in the endpiece holds the fold prism and joins the temple housing (an L-shaped housing). The beam leaves through a window toward the patch.`);
    }
    add('Prism', 'seeThrough', 'See-through transmission (world light)', `≈ ${Math.round(100 * (1 - Rw))}%`, grade(100 * (1 - Rw), (v) => v >= 70, (v) => v >= 50),
      pt.mode === 'lensback' ? (P.coating === 'bare' ? 'The reflector is the plain lens surface: world light loses only the ~8% any uncoated lens reflects. An anti-reflection coating on your lens would remove most of the HUD reflection too.' : 'The coating on the lens back reflects part of the world light away across the whole lens.')
        : pt.mode === 'embedded' ? 'World light crosses the buried partial mirror where it sits and loses its reflectance there; elsewhere the lens is unchanged.'
          : 'World light passes the coated patch once and loses its reflectance there; elsewhere the lens is unchanged. A thin shell of even thickness adds almost no power to the see-through view.');
  } else if (guided) {
    const wg = prism;
    const inc = chiefHyp?.incidenceDeg;
    const margin = inc != null ? inc - crit : null;
    add('Prism', 'chiefInc', 'Chief-ray guided angle (TIR in the plate)', inc == null ? 'not guided' : `${f2(inc)}°`,
      inc == null ? 'fail' : margin > 3 ? 'pass' : margin > 0 ? 'warn' : 'fail',
      inc == null ? `The display-centre ray does not bounce inside the waveguide (outcome: ${chief.outcome}). Check the input alignment.`
        : `Bounces between the plate faces at ${f1(inc)}°, ${f1(margin)}° above the ${f1(crit)}° critical angle. Needs an air gap (or a low-index bond) on both faces: a normal optical adhesive (n ≈ 1.56) on the face would stop TIR.`);
    const hits = chief.events.filter((e) => e.obj === 'guide' && e.facet);
    add('Prism', 'facets', 'Out-coupling facets', `${wg.facets.length} × R ${Math.round(100 * params.waveguide.facetR)}%`, 'info',
      `Facet normal tilted ${f1(wg.incWanted)}° to the wanted rays; the other bounce phase meets them at ${f1(wg.incOther)}°. ${params.waveguide.coating === 'plain' ? `Stock partial reflector: same reflectance at every angle, so the other bounce phase also reflects and can form ghosts (the tracer follows them; the image check rejects pixels that arrive doubled).` : `Angle-selective coating assumed (custom): reflects below ${f1(wg.cutoff)}°, ~1% above, which suppresses the ghost.`} Chief ray met ${hits.length} facet surfaces.`);
    const T = 1 - params.waveguide.facetR;
    add('Prism', 'seeThrough', 'See-through transmission (world light)', `≈ ${Math.round(100 * T)}%`, grade(100 * T, (v) => v >= 70, (v) => v >= 50),
      'World light crosses one facet near normal incidence on its way to the eye and loses the facet reflectance; uncoated plate faces cost ~4% each more.');
  } else if (!chiefHyp) {
    add('Prism', 'chiefInc', 'Chief-ray incidence on hypotenuse', 'not reached', 'fail',
      `The display-centre ray never reaches the hypotenuse from inside the prism (outcome: ${chief.outcome}). Check OLED/prism alignment.`);
  } else {
    const inc = chiefHyp.incidenceDeg;
    const margin = inc - crit;
    const st = chiefHyp.mirror ? 'pass' : margin > 1 ? 'pass' : margin > 0 ? 'warn' : 'fail';
    add('Prism', 'chiefInc', 'Chief-ray incidence on hypotenuse', `${f2(inc)}°`, st,
      chiefHyp.mirror ? 'Hypotenuse is mirror-coated; reflection does not depend on TIR.'
        : margin > 1 ? `TIR with ${f1(margin)}° margin above the critical angle.`
          : margin > 0 ? `TIR, but only ${f2(margin)}° above critical; small tilts break it.`
            : `Below the critical angle by ${f2(-margin)}°: the chief ray mostly transmits through the hypotenuse (R = ${(100 * chiefHyp.R).toFixed(1)}%).`);
  }
  const tirPct = hyp.hits ? (100 * hyp.tir) / hyp.hits : null;
  const coated = params.prism.coating === 'mirror';
  if (!guided && !patched) add('Prism', 'tir', coated ? 'Hypotenuse reflection (mirror coating)' : 'Total internal reflection across beam',
    coated ? `${hyp.hits} hits, R = 90%` : tirPct == null ? 'no hits' : `${f1(tirPct)}% of ${hyp.hits} hits`,
    coated ? 'pass' : grade(tirPct, (v) => v >= 99, (v) => v >= 90),
    coated ? 'Aluminium coating assumed (R = 0.90); TIR not required. Adds absorption loss.'
      : tirPct == null ? 'No rays reached the hypotenuse.'
        : tirPct >= 99 ? `Incidence range ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}°, all above ${f1(crit)}°.`
          : `Incidence spans ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}°. Rays below ${f1(crit)}° leak through the hypotenuse (${counts.leaked} rays). The field angle inside the glass (±${f1((hyp.maxInc - hyp.minInc) / 2)}°) exceeds the TIR margin of a 45° prism (${f1(45 - crit)}°). Options: mirror-coat the hypotenuse, longer focal length, or a steeper prism angle.`);

  if (guided) {
    add('Prism', 'guideTIR', 'Total internal reflection across beam', tirPct == null ? 'no hits' : `${f1(tirPct)}% of ${hyp.hits} bounces`,
      grade(tirPct, (v) => v >= 99, (v) => v >= 90),
      tirPct == null ? 'No rays bounce inside the waveguide.' : `Bounce incidence ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}° against θc ${f1(crit)}°. The display field adds ± half its in-glass angle to the guide angle.`);
  }
  // Fresnel on the chief path
  const fevs = chief.events.filter((e) => e.R != null);
  // (a waveguide facet's partial reflectance is its design split, reported with the facets)
  const chiefT = fevs.reduce((p, e) => p * (e.tir || e.facet ? 1 : e.mirror ? e.R : e.T), 1);
  // light actually delivered: also the combiner's split (facet / patch reflectance)
  const deliveredT = fevs.reduce((p, e) => p * (e.tir ? 1 : e.mirror ? e.R : e.T), 1);
  const fresnelText = fevs.map((e) => `${e.obj}/${e.face}: ${e.tir ? 'TIR 100%' : e.mirror ? `mirror ${(100 * e.R).toFixed(1)}%` : `R ${(100 * e.R).toFixed(2)}% T ${(100 * e.T).toFixed(2)}%`}`).join('; ');
  add('Prism', 'fresnel', 'Fresnel throughput (chief path)', `${(100 * chiefT).toFixed(1)}%`,
    chiefT >= 0.85 ? 'pass' : chiefT >= 0.6 ? 'warn' : 'fail',
    `${fresnelText || 'no dielectric surfaces on chief path'}. Uncoated surfaces assumed (no AR coating).`);

  // ---------------- ray statistics
  add('Rays', 'emitted', 'Rays emitted', `${counts.emitted}`, 'info',
    `${params.sim.pixelsX}×${params.sim.pixelsY} pixel samples × ${params.sim.raysPerPixel} rays × ${results.bands.length} wavelength(s), Lambertian within ±${params.oled.emissionHalfAngle}° (${(100 * results.coneFractionOfHemisphere).toFixed(0)}% of hemispherical output).`);
  add('Rays', 'pupilRays', 'Rays reaching right pupil', `${counts.pupil} (${f1(coverage.field.pupilRayPct)}%)`,
    counts.pupil > 0 ? 'info' : 'fail',
    counts.pupil > 0 ? `Power-weighted: ${f2(coverage.field.pupilPowerPct)}% of emitted cone power. Missed eye: ${counts.eyeMiss}, absorbed: ${Object.values(counts.absorbed).reduce((a, b) => a + b, 0)}, escaped: ${counts.escaped}.`
      : 'No traced ray enters the right pupil. The HUD is not visible from this eye position.');
  const absorbedTxt = Object.entries(counts.absorbed).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(', ');
  add('Rays', 'losses', 'Where rays are lost', absorbedTxt || 'none absorbed', 'info',
    `Leaked through hypotenuse: ${counts.leaked}. Escaped scene: ${counts.escaped}.`);

  // ---------------- coverage
  const cov = coverage.lens.coveragePct;
  add('Coverage', 'lensCov', 'Right-lens coverage (apparent HUD footprint)', `${f2(cov)}%`,
    grade(cov, (v) => v >= t.coverageMin && v <= t.coverageMax, (v) => v >= t.coverageMin - 10 && v <= t.coverageMax + 10),
    cov >= t.coverageMin && cov <= t.coverageMax ? 'Within the preliminary target.'
      : `Target ${t.coverageMin}–${t.coverageMax}%. Footprint ${f1(coverage.lens.footprintArea)} mm² of ${f1(coverage.lens.area)} mm². Even the full ${t.hfov}°×${t.vfov}° target field at ${t.azimuth}° would cover only ${f1(coverage.lens.targetFovCoveragePct)}%; the whole lens spans about ${f1(coverage.lens.wholeLensHfov)}°×${f1(coverage.lens.wholeLensVfov)}° from this pupil. The coverage target and the FOV target are not mutually consistent.`);
  add('Coverage', 'outside', 'Footprint outside lens outline', `${f1(coverage.lens.outsidePct)}%`,
    grade(coverage.lens.outsidePct, (v) => v <= 1, (v) => v <= 20),
    coverage.lens.outsidePct <= 1 ? '' : 'Part of the HUD would be seen beyond the lens edge (over the frame).');
  add('Coverage', 'clip', 'Display field clipping', `${f1(coverage.field.clippedPct)}% of pixels`,
    grade(coverage.field.clippedPct, (v) => v <= 2, (v) => v <= 15),
    coverage.field.clippedPct <= 2 ? 'Whole sampled display visible from the nominal pupil.'
      : `${coverage.field.totalPixels - coverage.field.visiblePixels} of ${coverage.field.totalPixels} sampled pixels send no ray into the pupil (TIR leakage, aperture vignetting or eye-box limits).`);

  // ---------------- field of view
  const fld = coverage.field;
  const W = oled.width;
  const fEff = collimator ? collimator.f : null;
  const fovGeom = fEff ? (2 * Math.atan(W / 2 / fEff) * 180) / Math.PI : null;
  const fNeeded = W / (2 * Math.tan(((t.hfov / 2) * Math.PI) / 180));
  add('Field', 'hfov', 'Horizontal FOV (visible)', `${f1(fld.hfov)}°`, grade(fld.hfov, (v) => v >= t.hfov - 1, (v) => v >= 0.75 * t.hfov),
    fld.hfov >= t.hfov - 1 ? '' : `Target ${t.hfov}°. Display width ${f2(W)} mm at f = ${fEff ?? '—'} mm gives at most ${f1(fovGeom)}° (2·atan(W/2f)); the target needs f ≈ ${f2(fNeeded)} mm${fld.availHfov != null ? `. Unclipped field at the pupil plane: ${f1(fld.availHfov)}°` : ''}.`);
  const H = oled.height;
  const vGeom = fEff ? (2 * Math.atan(H / 2 / fEff) * 180) / Math.PI : null;
  add('Field', 'vfov', 'Vertical FOV (visible)', `${f1(fld.vfov)}°`, grade(fld.vfov, (v) => v >= t.vfov - 1, (v) => v >= 0.75 * t.vfov),
    fld.vfov >= t.vfov - 1 ? '' : `Target ${t.vfov}°. Display height ${f2(H)} mm gives at most ${f1(vGeom)}° at f = ${fEff ?? '—'} mm.`);
  add('Field', 'hoff', 'Horizontal offset (temporal +)', `${f1(fld.hCenter)}°`, grade(fld.hCenter, (v) => Math.abs(v - t.azimuth) <= 5, (v) => Math.abs(v - t.azimuth) <= 10),
    fld.hCenter == null ? 'No visible field.' : `Target ≈ ${t.azimuth}° outward. Visible span ${f1(fld.hMin)}° to ${f1(fld.hMax)}°.`);
  add('Field', 'voff', 'Vertical offset (up +)', `${f1(fld.vCenter)}°`, grade(fld.vCenter, (v) => v > 0, (v) => v > -5),
    fld.vCenter == null ? 'No visible field.' : `Upper field required. Visible span ${f1(fld.vMin)}° to ${f1(fld.vMax)}°.`);
  const z = t.zone;
  if (z) {
    const vis = fld.visiblePixels, inZ = fld.inZone ?? 0;
    if (fld.scrambled) add('Field', 'scrambled', 'Pixels arriving scrambled or as ghosts', `${fld.scrambled} px`, 'warn',
      'Their light reaches the pupil either from many directions (> 1° spread) or displaced more than 1.5° from the image (a ghost from an extra reflection, e.g. off a prism end face). They are not counted as coverage. Usually the beam is wider than the prism.');
    add('Field', 'zone', 'HUD inside your zone', `${inZ}/${vis} visible px, fills ${f1(fld.zoneCoveredPct)}% of it`,
      vis > 0 && inZ === vis ? 'pass' : inZ > 0 ? 'warn' : 'fail',
      `Zone ${z.hMin}…${z.hMax}° × ${z.vMin}…${z.vMax}° (${f1(fld.zoneArea)} deg²). The HUD can be placed anywhere inside it (click in the eye view, or map the reach), but one ${f2(oled.diagonalMm / 25.4)}″ display spans only ≈ ${f1(fld.availHfov)}° × ${f1(fld.availVfov)}° at f = ${collimator?.f ?? '—'} mm, so it cannot fill the whole zone at once.`);
  }
  add('Field', 'central', 'Central zone clear of HUD', fld.minRadius == null ? '—' : `${f1(fld.minRadius)}° from axis`,
    grade(fld.minRadius, (v) => v >= t.centralClear, (v) => v >= t.centralClear * 0.6),
    fld.minRadius >= t.centralClear ? `Nearest HUD edge is outside the ${t.centralClear}° central zone.` : `HUD intrudes into the ${t.centralClear}° central zone.`);
  const occ = coverage.occlusion;
  add('Field', 'hwCentral', 'Central zone clear of hardware', `${f1(occ.minRadius)}° from axis`,
    grade(occ.minRadius, (v) => v >= t.centralClear, (v) => v >= t.centralClear * 0.6),
    patched ? 'The mirror patch is see-through (its transmission is a separate check); the display and lens stay in the temple.' : guided ? 'The waveguide plate is see-through (its transmission is a separate check); the input optics stay at the temple.' : occ.minRadius >= t.centralClear ? `Prism blocks ${f1(occ.prismLensPct)}% of the lens's angular area.`
      : `The prism silhouette reaches ${f1(occ.prism.minRadius)}° from the line of sight (inside the ${t.centralClear}° zone) and blocks ${f1(occ.prismLensPct)}% of the lens's angular area. A 10 mm prism this close to the eye subtends a large angle; move it outward/up or increase eye relief.`);

  // ---------------- eye geometry
  const cornea = eye.corneaVertex;
  const prismClear = patched && prism.mode ? glasses.lenses.R.backCenter.distanceTo(cornea) : patched ? Math.min(...Object.values(prism.vertices).map((v) => v.distanceTo(cornea))) : minDistanceToPrism(prism, cornea); // to corneal apex
  add('Eye', 'relief', 'Eye relief (lens back → cornea)', `${f1(params.eye.eyeRelief)} mm`,
    grade(params.eye.eyeRelief, (v) => v >= 10 && v <= 20, (v) => v >= 8 && v <= 25), 'Typical spectacle vertex distance is 12–14 mm.');
  const lash = params.eye.lashLength ?? 6;
  add('Eye', 'prismClear', `${cname} clearance to cornea`, `${f1(prismClear)} mm (lashes ${f1(lash)} mm)`,
    grade(prismClear, (v) => v >= lash, (v) => v >= 2),
    prismClear >= lash ? '' : prismClear >= 2 ? `Closer than your ${f1(lash)} mm lash length: lashes will likely brush or smear the prism.` : 'Prism touches or nearly touches the cornea.');
  const lfR = glasses.lenses.R;
  const lensGap = patched && prism.mode ? 0 : Math.min(...Object.values(prism.vertices).map((v) => -v.clone().sub(lfR.backCenter).dot(lfR.normal)));
  if (patched && prism.mode) add('Eye', 'prismLens', 'Reflector and lens', prism.mode === 'embedded' ? 'cast inside the lens' : 'the lens back surface itself', 'pass', 'No separate part behind the lens.');
  else add('Eye', 'prismLens', `${cname} clearance to lens back surface`, `${f1(lensGap)} mm`,
    grade(lensGap, (v) => v >= 0.3, (v) => v >= 0), lensGap < 0 ? `${cname} intersects the (tilted/wrapped) spectacle lens plane.` : 'Measured to the lens back plane, including tilt and wrap.');
  const eb = coverage.eyebox;
  add('Eye', 'eyebox', 'Eye-box (full field visible)', `${f1(eb.full.width)} × ${f1(eb.full.height)} mm`,
    grade(eb.full.width, (v) => v >= 4 && eb.full.height >= 4, (v) => v > 0),
    eb.full.area > 0 ? `Area ${f1(eb.full.area)} mm²; ≥50% field: ${f1(eb.half.width)} × ${f1(eb.half.height)} mm. Pupil ${params.eye.pupilDiameter} mm.`
      : `No pupil position sees the whole sampled display (best ${(100 * eb.best.frac).toFixed(0)}% at offset ${f1(eb.best.ox)}, ${f1(eb.best.oy)} mm). ≥50% field: ${f1(eb.half.width)} × ${f1(eb.half.height)} mm.`);
  if (coverage.gaze) {
    const g = coverage.gaze;
    add('Eye', 'gaze', 'Field visible when looking at the HUD', `${f1(100 * g.visibleFrac)}%`,
      grade(100 * g.visibleFrac, (v) => v >= 98, (v) => v >= 60),
      `Rotating the eye ${f1(g.yaw)}° / ${f1(g.pitch)}° to look at the HUD moves the entrance pupil ${f1(g.pupilShift)} mm.`);
  }
  const leftOk = counts.leftPupil === 0;
  add('Eye', 'left', 'Left eye unaffected', leftOk ? `0 rays in pupil` : `${counts.leftPupil} rays in pupil`,
    leftOk ? (counts.leftEye ? 'warn' : 'pass') : 'fail',
    leftOk ? (counts.leftEye ? `${counts.leftEye} stray rays strike the left eye/eyelid area outside the pupil (mostly hypotenuse leakage).` : 'No traced light reaches the left eye.')
      : 'Stray light enters the left pupil.');

  // ---------------- collimation / focus
  if (!collimator) {
    add('Collimation', 'focal', 'OLED focal-plane alignment', 'no collimator', 'fail',
      'Without a collimating lens the eye sees the bare OLED a few centimetres away; it cannot focus that close.');
  } else if (!collimator.valid) {
    add('Collimation', 'focal', 'Collimator geometry', 'invalid', 'fail', collimator.invalidReason);
  } else {
    const so = collimator.center.clone().sub(oled.center).dot(collimator.axis);
    const delta = so - collimator.frontFocalDistance;
    const ffdLabel = collimator.mode === 'thin' ? 'f' : 'front focal distance';
    let image = '';
    const fT = collimator.frontFocalDistance;
    if (Math.abs(delta) < 1e-6) image = 'image at infinity';
    else {
      const si = 1 / (1 / fT - 1 / so);
      image = si < 0 ? `virtual image ${f1(-si)} mm before the lens (thin-lens estimate)` : `real image ${f1(si)} mm after the lens: beam converges`;
    }
    add('Collimation', 'focal', 'OLED focal-plane alignment', `Δ = ${f2(delta)} mm`,
      grade(Math.abs(delta), (v) => v <= 0.1, (v) => v <= 0.5),
      `Object distance ${f2(so)} mm vs ${ffdLabel} ${f2(fT)} mm → ${image}.${collimator.mode === 'thin' ? '' : ' Paraxial value: spherical aberration moves the best focus of a real singlet away from it; check the measured vergence below.'}`);
  }
  const verg = pixelResults.map((p) => p.vergence).filter(Boolean);
  const pixelArcmin = ((oled.pixelPitch / (collimator?.f ?? 12)) * 180 * 60) / Math.PI;
  let focus = null;
  if (verg.length) {
    const meanV = verg.reduce((s, v) => s + v.mean, 0) / verg.length;
    const Vx = verg.reduce((s, v) => s + v.Vx, 0) / verg.length, Vy = verg.reduce((s, v) => s + v.Vy, 0) / verg.length;
    const maxAst = Math.max(...verg.map((v) => v.astig));
    const blurMrad = verg.reduce((s, v) => s + v.residualMrad, 0) / verg.length;
    const blurArcmin = (blurMrad * 180 * 60) / Math.PI / 1000;
    const imgDist = meanV < -0.05 ? `virtual image ≈ ${f1(1000 / -meanV)} mm away` : meanV > 0.05 ? 'converging bundle (focus "beyond infinity")' : 'image at optical infinity';
    add('Collimation', 'vergence', 'Measured bundle vergence at pupil', `${f2(meanV)} D`, 'info',
      `From traced rays: ${imgDist}. Horizontal ${f2(Vx)} D, vertical ${f2(Vy)} D, astigmatism up to ${f2(maxAst)} D. Residual aberration spread ${f2(blurArcmin)}′ vs pixel size ${f2(pixelArcmin)}′.`);
    // ---- focus for this wearer's eye (prescription + accommodation), whole field
    focus = assessFocus({ Vx, Vy }, params.eye);
    const field = assessFieldFocus(verg, params.eye);
    Object.assign(focus, { field, residual: field.p90, accommodation: field.accommodation, blurRad: field.blurRad });
    focus.aberrationArcmin = blurArcmin;
    const defocusArcmin = (focus.blurRad * 180 * 60) / Math.PI;
    focus.blurDeg = (focus.blurRad + blurMrad / 1000) * (180 / Math.PI);
    const rx = params.eye.rx;
    const rxText = `Rx ${rx.sphere >= 0 ? '+' : ''}${f2(rx.sphere)} / ${f2(rx.cyl)} × ${Math.round(rx.axis)}° → at cornea ${f2(focus.Fh)} D (horizontal), ${f2(focus.Fv)} D (vertical); accommodation range ${f1(focus.amp)} D`;
    // blur limit: 2 pixels, but never finer than 2′ (≈ 20/40; the eye resolves ~1′
    // at best, so sharper-than-2′ blur is invisible even on a very fine display)
    const blurLimit = Math.max(2 * pixelArcmin, 2);
    const st = field.p90 <= 0.25 && blurArcmin <= blurLimit ? 'pass' : field.p90 <= 0.75 ? 'warn' : 'fail';
    const why = maxAst > 1 ? `Field astigmatism up to ${f1(maxAst)} D (typical of a single lens at wide field angles) cannot be focused away; a smaller field (longer focal length) or a two-element eyepiece reduces it.`
      : focus.tooConverging ? 'The HUD focuses farther than your eye can relax to (typical when short-sighted, because the HUD light bypasses your spectacle lens).'
        : focus.tooDiverging ? 'The HUD image is closer than your near point.' : '';
    add('Vision', 'eyeFocus', 'HUD in focus for your eye', `90% of field within ${f2(field.p90)} D (worst ${f1(field.worst)} D)`, st,
      `${rxText}. One accommodation (${f2(field.accommodation)} D) has to serve the whole image. ${why} ${st !== 'pass' && !why.includes('astigmatism') ? 'Use "Focus HUD for my eye" to move the OLED to the best distance.' : ''}`.trim());
    const supports = field.p90 <= 0.5 && blurArcmin <= blurLimit;
    add('Collimation', 'virtualImage', 'Focused virtual image', supports ? 'supported' : 'not supported', supports ? (st === 'pass' ? 'pass' : 'warn') : 'fail',
      supports ? `At least 90% of the field focuses within 0.5 D of one accommodation, with aberration under ${f1(blurLimit)}′ (2 pixels, at least 2′).`
        : `Not enough of the field focuses at once (90th percentile ${f2(field.p90)} D; needs ≤ 0.5 D) or the aberration spread (${f1(blurArcmin)}′) exceeds ${f1(blurLimit)}′ (2 pixels of ${f1(pixelArcmin)}′, at least 2′ since the eye resolves ~1′ at best).`);
  } else {
    add('Collimation', 'vergence', 'Measured bundle vergence at pupil', 'insufficient rays', 'fail', 'Fewer than 4 rays per pixel reach the pupil region; vergence cannot be measured.');
  }

  // ---------------- alignment
  const chiefFinal = chief.finalRay;
  if (chiefFinal) {
    const miss = closestApproach(chiefFinal.origin, chiefFinal.dir, eye.pupilCenter);
    add('Alignment', 'chiefMiss', 'Chief ray miss distance at pupil', `${f2(miss)} mm`,
      grade(miss, (v) => v <= eye.pupilRadius * 0.5, (v) => v <= eye.pupilRadius),
      `Chief ray outcome: ${chief.outcome}. Pupil radius ${f1(eye.pupilRadius)} mm.`);
  } else {
    add('Alignment', 'chiefMiss', 'Chief ray miss distance at pupil', 'absorbed', 'fail', `Chief ray outcome: ${chief.outcome}.`);
  }
  const entryHit = chief.events.find((e) => e.obj === (guided ? 'guide' : 'prism') && e.entering);
  if (entryHit) {
    add('Alignment', 'entryDecenter', `Chief ray decentre on ${cname.toLowerCase()} entry`, `${f2(entryHit.point.distanceTo(prism.entryCenter))} mm`,
      grade(entryHit.point.distanceTo(prism.entryCenter), (v) => v <= 0.5, (v) => v <= 2), `Entered through face: ${entryHit.face}.`);
  }
  if (collimator) {
    const dec = Math.hypot(params.collimator.offsetX, params.collimator.offsetY);
    const tilt = Math.hypot(params.collimator.tiltX, params.collimator.tiltY);
    add('Alignment', 'collAlign', 'Collimator decentre / tilt', `${f2(dec)} mm / ${f2(tilt)}°`,
      grade(dec + tilt / 5, (v) => v <= 0.05, (v) => v <= 0.5), dec || tilt ? 'Decentre steers the field; tilt adds astigmatism.' : '');
  }
  const housingOk = [-0.5, 0.5].every((sx) => [-0.5, 0.5].every((sy) => [-0.5, 0.5].every((sz) => pointInBox(
    new Vector3(sx * oled.housing.size.x, sy * oled.housing.size.y, sz * oled.housing.size.z).applyQuaternion(oled.quaternion).add(oled.housing.center), glasses.cavity, 0.01))));
  add('Alignment', 'oledFit', 'OLED module inside temple cavity', housingOk ? 'yes' : 'no', housingOk ? 'pass' : 'fail',
    housingOk ? '' : 'The OLED housing extends outside the temple cavity; enlarge the housing or move the OLED.');
  const dEnv = system.driver;
  const driverOk = boxCorners(dEnv.envCenter, dEnv.quaternion, dEnv.envelope).every((c) => pointInBox(c, glasses.cavity, 0.01));
  add('Alignment', 'driverFit', 'Driver board inside temple cavity', driverOk ? 'yes' : 'no', driverOk ? 'pass' : 'fail',
    driverOk ? `Board ${dEnv.size.z}×${dEnv.size.y} mm (assumed compact driver; common HDMI boards are larger).` : 'The driver board does not fit in the cavity.');
  // conformal shell: the lens sits in the printed barrel section of the housing
  const collInside = collimator ? (system.housingShell ? system.housingShell.parts.some((q) => q.id === 'barrel') : pointInBox(collimator.center, glasses.cavity, 0.01)) : null;
  if (system.housingShell) {
    const loose = system.housingShell.loose;
    add('Fit', 'shellJoined', 'Housing joined to the temple', loose.length ? `${loose.join(', ')} not joined` : 'yes', loose.length ? 'fail' : 'pass',
      loose.length ? `These shell sections do not touch the rest of the housing or the temple arm: ${loose.join(', ')}. They would float.` : `Every section (${system.housingShell.parts.map((q) => q.label).join(', ')}) connects through the others to the right temple arm.`);
  }
  if (collimator) add('Alignment', 'collFit', 'Collimator inside temple cavity', collInside ? 'yes' : 'no', collInside ? 'pass' : 'warn',
    collInside ? '' : 'The collimator sits outside the temple housing and needs its own enclosure.');

  // ---------------- image
  // Fit apparent angles as an affine function of display coordinates over
  // every pixel sample that reached the pupil plane: h = a u + b v + c,
  // vAng = d u + e v + f. det < 0 means the image is mirrored.
  const pts = pixelResults.filter((p) => p.availableAngles);
  if (pts.length >= 3) {
    const fit = (get) => {
      // normal equations for [u v 1]
      const M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], r = [0, 0, 0];
      for (const p of pts) {
        const x = [p.u, p.v, 1], y = get(p);
        for (let i = 0; i < 3; i++) { r[i] += x[i] * y; for (let j = 0; j < 3; j++) M[i][j] += x[i] * x[j]; }
      }
      return solve3(M, r);
    };
    let [a, b] = fit((p) => p.availableAngles.h);
    let [d, e] = fit((p) => p.availableAngles.v);
    // what the eye sees after the display driver's optional left-right flip
    const flipped = !!params.hud.driverFlip;
    if (flipped) { a = -a; d = -d; }
    if ([a, b, d, e].every(Number.isFinite)) {
      const det = a * e - b * d;
      const rot = (Math.atan2(d, a) * 180) / Math.PI;
      // tilt of the image's horizontal axis from horizontal, folded to ±90°
      const tilt = rot > 90 ? rot - 180 : rot < -90 ? rot + 180 : rot;
      const how = det < 0 ? (a < 0 ? 'mirrored left–right' : 'mirrored top–bottom') : Math.abs(rot) > 90 ? 'upside down' : 'upright';
      const shear = (Math.atan2(b, e) * 180) / Math.PI + rot;
      add('Image', 'orientation', 'Image orientation', `${how}, tilted ${f1(tilt)}°`,
        det < 0 || Math.abs(rot) > 3 ? 'fail' : Math.abs(shear) > 5 ? 'warn' : 'pass',
        `${det < 0 ? 'The optics mirror the image: turn on "Driver mirrors image". ' : flipped ? 'The display driver flips the image left–right to undo the optics\' mirror. ' : ''}${Math.abs(rot) > 3 ? 'Text will not read level: use "Level the image" (Align section), which rolls the OLED about its axis. ' : ''}Vertical axis leans ${f1(shear)}° relative to the horizontal (keystone from the off-axis fold${Math.abs(shear) > 5 ? '; noticeable' : ''}).`);
    }
  } else {
    add('Image', 'orientation', 'Image orientation', 'not determinable', 'fail', 'Fewer than 3 pixel samples reach the pupil plane.');
  }
  const ppd = fld.availHfov ? params.oled.resX / fld.availHfov : null;
  add('Image', 'res', 'Angular resolution', `${f1(pixelArcmin)}′/px, ${f1(ppd)} px/°`, 'info', '20/20 acuity resolves ~1′ at the fovea; the HUD sits in the periphery where acuity is far lower.');
  const L = params.oled.peakLuminance * (params.oled.brightness / 100) * deliveredT;
  add('Image', 'lum', 'Estimated HUD luminance', `${Math.round(L)} cd/m²`, grade(L, (v) => v >= 1000, (v) => v >= 150),
    `Peak OLED luminance ${params.oled.peakLuminance} cd/m² × ${params.oled.brightness}% × chief-path transmission including the combiner's reflectance (${(100 * deliveredT).toFixed(1)}%). Luminance is conserved through lossless imaging when the pupil is filled. Thresholds are rules of thumb (assumed): ≥ 1000 cd/m² for outdoor daylight, ≥ 150 cd/m² for indoors.`);

  // ---------------- head and face fit (right side)
  const fr = params.frame, hd = params.head;
  const head = computeHead(params, glasses, eye);
  const innerTempleX = head.innerTempleX;
  const hs = glasses.housing;
  const shell = system.housingShell;
  const housingInto = shell ? Math.max(...shell.points.map(head.intrusion)) : Math.max(...boxCorners(hs.center, new Quaternion(), hs.size).map(head.intrusion),
    ...(system.hingeBlock ? boxCorners(system.hingeBlock.center, new Quaternion(), system.hingeBlock.size).map(head.intrusion) : []));
  const hClear = Number.isFinite(housingInto) ? -housingInto : 99;
  add('Fit', 'headHousing', 'Temple housing clears your head', hClear >= 99 ? 'fully in front of the head' : `${f1(hClear)} mm`, grade(hClear, (v) => v >= 1, (v) => v >= 0),
    hClear >= 1 ? `Head model: lateral orbital rim ${f1(hd.hertelDepth)} mm behind the cornea, ${f1(hd.hertelBase)} mm rim-to-rim; temple gaps ${f1(hd.gap20)} / ${f1(hd.gap40)} mm at 20 / 40 mm behind the hinge.`
      : `The housing reaches ${f1(-hClear)} mm into your head. Reduce its depth or length, or bulge it outward.`);
  const canthusX = eye.pupilCenter.x - hd.canthusOffset;
  // ---- form factor: how far the housing bulges out beyond the temple
  // conformal shell: measured from the temple's outer face at each point along it
  const tR = glasses.temples.find((t) => t.side === 1);
  const bulge = shell && tR ? Math.max(0, ...shell.points.map((q) => {
    const t2 = q.clone().sub(tR.start).dot(tR.dir);
    const outer = tR.start.x + tR.dir.x * t2 - fr.templeThickness / 2;
    return outer - q.x;
  })) : fr.housingOutward ?? 0;
  add('Fit', 'formFactor', 'Housing bulge beyond the temple', `${f1(bulge)} mm`, grade(bulge, (v) => v <= 8, (v) => v <= 14),
    bulge <= 8 ? 'Keeps a normal-glasses look (a bulge of up to ~8 mm, like a thick temple; assumed limit).' : 'The display housing sticks out from the side of the frame like a camera pod; shorten the optical path or fold it along the temple.');
  // ---- standoff pins: is the combiner carried by the lens/frame?
  const lm = system.lensMount;
  if (lm) {
    const stopped = Object.entries(counts.absorbed).filter(([k]) => k.startsWith('mount-')).reduce((s2, [, v]) => s2 + v, 0);
    const blocked = counts.mountEyeward ?? 0;
    const ok = lm.pins.length >= 2 && lm.longest <= 12;
    add('Fit', 'lensMount', `${cname} bonded to the lens`, `${lm.pins.length} pins, longest ${f1(lm.longest)} mm`,
      !ok ? 'fail' : blocked > 0.01 * counts.emitted ? 'warn' : 'pass',
      `Ø${f1(2 * lm.radius)} mm standoff pins glued between the ${cname.toLowerCase()} and the back of the lens (the frame carries it).${lm.longest > 12 ? ' Longer than 12 mm: too flexible; move the part closer to the lens.' : ''} They stop ${blocked} rays heading for the eye${blocked > 0.01 * counts.emitted ? ': move them off the beam' : ''} (and ${stopped - blocked} stray rays going elsewhere).`);
  }
  // ---- optics arm: does a rigid part connect the prism to the housing?
  const arm = system.arm;
  if (arm) {
    const pts = armSurfacePoints(arm);
    const into = Math.max(...pts.map(head.intrusion));
    const lf = glasses.lenses.R;
    // only points over the lens itself can hit it (outline in lens coordinates)
    const overLens = pts.filter((p) => { const l = lf.toLocal(p); return insidePolygon([l.x, l.y], glasses.outline); });
    const lensGapArm = overLens.length ? Math.min(...overLens.map((p) => -p.clone().sub(lf.backCenter).dot(lf.normal))) : Infinity;
    const corneaGap = Math.min(...pts.map((p) => p.distanceTo(eye.corneaVertex)));
    const problems = [];
    if (!arm.reachesPrism) problems.push(`does not meet the ${cname.toLowerCase()} entry face`);
    if (into > 0) problems.push(`cuts ${f1(into)} mm into your head`);
    if (lensGapArm < 0.3) problems.push(`hits the spectacle lens (${f1(lensGapArm)} mm)`);
    if (corneaGap < lash) problems.push(`passes ${f1(corneaGap)} mm from the cornea`);
    add('Fit', 'armFit', guided ? 'Input optics tube to the waveguide' : 'Prism held by an arm to the housing', problems.length ? 'no' : `yes, ${f1(arm.length)} mm arm`, problems.length ? 'fail' : 'pass',
      problems.length ? `The optics arm ${problems.join('; ')}.` : `Ø${f1(2 * (arm.radius + arm.wall))} mm printed tube from the lens to the ${cname.toLowerCase()} ${guided ? 'aligns the input and shields the beam' : 'carries it and shields the beam'}.`);
  }
  // Lens + barrel ("optics pod"): the full glass diameter and the barrel must
  // stay clear of the head beside the temple and must start at the housing.
  if (collimator) {
    const gd = params.collimator.glassDiameter ?? collimator.aperture;
    const ref = Math.abs(collimator.axis.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
    const e1 = new Vector3().crossVectors(collimator.axis, ref).normalize(), e2 = new Vector3().crossVectors(collimator.axis, e1).normalize();
    const pts = [];
    const rings = [[collimator.center, gd / 2 + 0.8], [collimator.center.clone().addScaledVector(collimator.axis, collimator.thickness || 1), gd / 2 + 0.8], [oled.center, collimator.apertureRadius + 1.05]];
    for (const [c0, r] of rings) for (let i = 0; i < 24; i++) { const a = (i / 24) * Math.PI * 2; pts.push(c0.clone().addScaledVector(e1, r * Math.cos(a)).addScaledVector(e2, r * Math.sin(a))); }
    const into = Math.max(...pts.map(head.intrusion));
    const corneaHit = Math.min(...pts.map((c) => c.distanceTo(eye.corneaVertex)));
    const ok = into <= 0 && corneaHit >= lash;
    add('Fit', 'lensPod', 'Lens + barrel clear your head', ok ? 'yes' : into > 0 ? `${f1(into)} mm into head` : `${f1(corneaHit)} mm from cornea`, ok ? 'pass' : 'fail',
      ok ? `Ø${f1(gd)} mm lens in a barrel from the OLED housing (an optics pod, as in Google Glass-style designs).` : into > 0 ? 'The lens or its barrel cuts into the side of your head.' : 'The lens or barrel comes closer to the eye than your lashes allow.');
  }
  const modelCanthus = canthusX - innerTempleX;
  if (hd.canthusToTemple > 0) {
    const diff = modelCanthus - hd.canthusToTemple;
    add('Fit', 'canthus', 'Eye corner to temple: model vs your measurement', `${f1(modelCanthus)} vs ${f1(hd.canthusToTemple)} mm`,
      Math.abs(diff) <= 3 ? 'pass' : 'warn',
      Math.abs(diff) <= 3 ? 'The frame width and monocular PD agree with your measurement.' : `Off by ${f1(diff)} mm: recheck monocular PD, lens width, bridge, endpiece, or the assumed ${f1(hd.canthusOffset)} mm pupil-to-eye-corner offset.`);
  } else {
    add('Fit', 'canthus', 'Eye corner to temple (model)', `${f1(modelCanthus)} mm`, 'info', 'Enter your own measurement to cross-check the frame and PD.');
  }
  for (const pf of system.parts ?? []) {
    const blocked = counts.absorbed[`part:${pf.part.id}`] ?? 0;
    const corners = boxCorners(pf.position, pf.quaternion, pf.size);
    // the temple-side skin surface applies outboard of the eye corner and
    // behind the cornea; parts in front of the eye are checked elsewhere
    const intoHead = Math.max(...corners.map(head.intrusion));
    const notes = [];
    if (blocked) notes.push(`blocks ${blocked} rays`);
    if (intoHead > 0) notes.push(`cuts ${f1(intoHead)} mm into your head`);
    if (notes.length) add('Fit', `part-${pf.part.id}`, pf.part.name, notes.join(', '), intoHead > 0 ? 'fail' : 'warn',
      blocked ? 'It sits in the light path. Move it (drag it, or edit it under Parts & cost).' : 'Move it outward or behind the ear.');
  }
  if (glasses.outlineNote) add('Fit', 'outline', 'Lens outline', 'adjusted', 'warn', glasses.outlineNote);

  // ---------------- vision notes
  const amp = amplitudeFor(params.eye);
  add('Vision', 'amp', 'Accommodation range', `${f1(amp)} D`, 'info',
    params.eye.ampMode === 'age' ? `Average for age ${params.eye.age} (Hofstetter: 18.5 − 0.3 × age). Individuals vary by ±2 D or more.` : 'Entered manually.');
  if (params.eye.rx.add > 0) add('Vision', 'add', 'Reading add', `+${f2(params.eye.rx.add)} D`, 'info', 'Presbyopic: keep the HUD focused near your distance prescription; you have little range to accommodate.');
  const dom = params.eye.dominant;
  add('Vision', 'dominance', 'Dominant eye', dom, dom === 'left' ? 'warn' : 'info',
    dom === 'left' ? 'The HUD is on your non-dominant eye: expect more binocular rivalry (the HUD fading in and out).' : dom === 'right' ? 'The HUD is on your dominant eye.' : 'Unknown. Test: frame a distant object between your hands with both eyes open, then close each eye.');
  const cond = params.eye.condition;
  if (cond !== 'none') add('Vision', 'condition', 'Right-eye condition', cond, 'warn',
    { amblyopia: 'With a lazy right eye the HUD may look dim or blurred even when the optics are right; consider a left-eye build.', strabismus: 'A turned eye shifts where the HUD lands relative to your gaze; check the eye-box with your real fixation.', other: 'Check with your eye-care professional whether a right-eye HUD suits you.' }[cond]);

  // ---------------- cost
  const tot = bomTotals(params.bom ?? []);
  add('Cost', 'bom', 'Parts total', `$${tot.total.toFixed(2)}`, 'info', `$${tot.sourced.toFixed(2)} from sourced prices + $${tot.estimated.toFixed(2)} estimated. Details under Parts & cost.`);
  const wt = results.weights;
  if (wt) {
    add('Weight', 'weight', 'Total worn weight', `${tot.grams.toFixed(1)} g`, 'info',
      `${tot.gramsEstimated.toFixed(1)} g of it is estimated. Ray-Ban Meta smart glasses weigh about 48.6 g; the Meta Ray-Ban Display about 69 g.`);
    const share = wt.grams ? Math.max(wt.right, wt.left) / wt.grams : 0.5;
    add('Weight', 'balance', 'Left / right balance', `${wt.right.toFixed(1)} g right / ${wt.left.toFixed(1)} g left`,
      share <= 0.6 ? 'pass' : share <= 0.7 ? 'warn' : 'fail',
      `${(100 * share).toFixed(0)}% on the ${wt.right >= wt.left ? 'right' : 'left'} side${wt.com ? `; centre of mass ${Math.abs(wt.com.x).toFixed(0)} mm ${wt.com.x < 0 ? 'right' : 'left'} of centre, ${Math.abs(wt.com.z).toFixed(0)} mm behind the lenses` : ''}. The 60% / 70% comfort thresholds are modelling assumptions. To balance, move parts to the left temple (the battery and charger are already there).`);
  }

  const summary = { pass: 0, warn: 0, fail: 0, info: 0 };
  for (const c of checks) summary[c.status]++;
  return { checks, summary, focus };
}

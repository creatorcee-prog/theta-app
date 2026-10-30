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
  const chiefHyp = chief.events.find((e) => e.obj === 'prism' && e.face === 'hypotenuse' && !e.entering);
  if (!chiefHyp) {
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
  add('Prism', 'tir', coated ? 'Hypotenuse reflection (mirror coating)' : 'Total internal reflection across beam',
    coated ? `${hyp.hits} hits, R = 90%` : tirPct == null ? 'no hits' : `${f1(tirPct)}% of ${hyp.hits} hits`,
    coated ? 'pass' : grade(tirPct, (v) => v >= 99, (v) => v >= 90),
    coated ? 'Aluminium coating assumed (R = 0.90); TIR not required. Adds absorption loss.'
      : tirPct == null ? 'No rays reached the hypotenuse.'
        : tirPct >= 99 ? `Incidence range ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}°, all above ${f1(crit)}°.`
          : `Incidence spans ${f1(hyp.minInc)}°–${f1(hyp.maxInc)}°. Rays below ${f1(crit)}° leak through the hypotenuse (${counts.leaked} rays). The field angle inside the glass (±${f1((hyp.maxInc - hyp.minInc) / 2)}°) exceeds the TIR margin of a 45° prism (${f1(45 - crit)}°). Options: mirror-coat the hypotenuse, longer focal length, or a steeper prism angle.`);

  // Fresnel on the chief path
  const fevs = chief.events.filter((e) => e.R != null);
  const chiefT = fevs.reduce((p, e) => p * (e.tir ? 1 : e.mirror ? e.R : e.T), 1);
  const fresnelText = fevs.map((e) => `${e.obj}/${e.face}: ${e.tir ? 'TIR 100%' : e.mirror ? 'mirror 90%' : `R ${(100 * e.R).toFixed(2)}% T ${(100 * e.T).toFixed(2)}%`}`).join('; ');
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
    occ.minRadius >= t.centralClear ? `Prism blocks ${f1(occ.prismLensPct)}% of the lens's angular area.`
      : `The prism silhouette reaches ${f1(occ.prism.minRadius)}° from the line of sight (inside the ${t.centralClear}° zone) and blocks ${f1(occ.prismLensPct)}% of the lens's angular area. A 10 mm prism this close to the eye subtends a large angle; move it outward/up or increase eye relief.`);

  // ---------------- eye geometry
  const cornea = eye.corneaVertex;
  const prismClear = minDistanceToPrism(prism, cornea) - 0; // to corneal apex
  add('Eye', 'relief', 'Eye relief (lens back → cornea)', `${f1(params.eye.eyeRelief)} mm`,
    grade(params.eye.eyeRelief, (v) => v >= 10 && v <= 20, (v) => v >= 8 && v <= 25), 'Typical spectacle vertex distance is 12–14 mm.');
  const lash = params.eye.lashLength ?? 6;
  add('Eye', 'prismClear', 'Prism clearance to cornea', `${f1(prismClear)} mm (lashes ${f1(lash)} mm)`,
    grade(prismClear, (v) => v >= lash, (v) => v >= 2),
    prismClear >= lash ? '' : prismClear >= 2 ? `Closer than your ${f1(lash)} mm lash length: lashes will likely brush or smear the prism.` : 'Prism touches or nearly touches the cornea.');
  const lfR = glasses.lenses.R;
  const lensGap = Math.min(...Object.values(prism.vertices).map((v) => -v.clone().sub(lfR.backCenter).dot(lfR.normal)));
  add('Eye', 'prismLens', 'Prism clearance to lens back surface', `${f1(lensGap)} mm`,
    grade(lensGap, (v) => v >= 0.3, (v) => v >= 0), lensGap < 0 ? 'Prism intersects the (tilted/wrapped) spectacle lens plane.' : 'Measured to the lens back plane, including tilt and wrap.');
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
    const st = field.p90 <= 0.25 && blurArcmin <= 2 * pixelArcmin ? 'pass' : field.p90 <= 0.75 ? 'warn' : 'fail';
    const why = maxAst > 1 ? `Field astigmatism up to ${f1(maxAst)} D (typical of a single lens at wide field angles) cannot be focused away; a smaller field (longer focal length) or a two-element eyepiece reduces it.`
      : focus.tooConverging ? 'The HUD focuses farther than your eye can relax to (typical when short-sighted, because the HUD light bypasses your spectacle lens).'
        : focus.tooDiverging ? 'The HUD image is closer than your near point.' : '';
    add('Vision', 'eyeFocus', 'HUD in focus for your eye', `90% of field within ${f2(field.p90)} D (worst ${f1(field.worst)} D)`, st,
      `${rxText}. One accommodation (${f2(field.accommodation)} D) has to serve the whole image. ${why} ${st !== 'pass' && !why.includes('astigmatism') ? 'Use "Focus HUD for my eye" to move the OLED to the best distance.' : ''}`.trim());
    const supports = field.p90 <= 0.5 && blurArcmin <= 2 * pixelArcmin;
    add('Collimation', 'virtualImage', 'Focused virtual image', supports ? 'supported' : 'not supported', supports ? (st === 'pass' ? 'pass' : 'warn') : 'fail',
      supports ? 'At least 90% of the field focuses within 0.5 D of one accommodation, with sub-2-pixel aberration.'
        : `Not enough of the field focuses at once (90th percentile ${f2(field.p90)} D; needs ≤ 0.5 D) or the aberration spread (${f1(blurArcmin)}′) exceeds 2 pixels (${f1(2 * pixelArcmin)}′).`);
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
  const entryHit = chief.events.find((e) => e.obj === 'prism' && e.entering);
  if (entryHit) {
    add('Alignment', 'entryDecenter', 'Chief ray decentre on prism entry', `${f2(entryHit.point.distanceTo(prism.entryCenter))} mm`,
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
  const collInside = collimator ? pointInBox(collimator.center, glasses.cavity, 0.01) : null;
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
    const [a, b] = fit((p) => p.availableAngles.h);
    const [d, e] = fit((p) => p.availableAngles.v);
    if ([a, b, d, e].every(Number.isFinite)) {
      const det = a * e - b * d;
      const rot = (Math.atan2(d, a) * 180) / Math.PI;
      // tilt of the image's horizontal axis from horizontal, folded to ±90°
      const tilt = rot > 90 ? rot - 180 : rot < -90 ? rot + 180 : rot;
      const how = det < 0 ? (a < 0 ? 'mirrored left–right' : 'mirrored top–bottom') : Math.abs(rot) > 90 ? 'rotated 180°' : 'upright';
      add('Image', 'orientation', 'Image orientation', `${how}, tilted ${f1(tilt)}°`,
        det < 0 || Math.abs(tilt) > 3 || Math.abs(rot) > 90 ? 'warn' : 'pass',
        det < 0 ? 'A single reflection mirrors the image; flip it in the display driver.' : Math.abs(rot) > 3 ? 'Rotate the frame buffer or roll the OLED.' : '');
    }
  } else {
    add('Image', 'orientation', 'Image orientation', 'not determinable', 'fail', 'Fewer than 3 pixel samples reach the pupil plane.');
  }
  const ppd = fld.availHfov ? params.oled.resX / fld.availHfov : null;
  add('Image', 'res', 'Angular resolution', `${f1(pixelArcmin)}′/px, ${f1(ppd)} px/°`, 'info', '20/20 acuity resolves ~1′ at the fovea; the HUD sits in the periphery where acuity is far lower.');
  const L = params.oled.peakLuminance * (params.oled.brightness / 100) * chiefT;
  add('Image', 'lum', 'Estimated HUD luminance', `${Math.round(L)} cd/m²`, 'info',
    `Peak OLED luminance ${params.oled.peakLuminance} cd/m² (assumed) × ${params.oled.brightness}% × chief-path transmission. Luminance is conserved through lossless imaging when the pupil is filled.`);

  // ---------------- head and face fit (right side)
  const fr = params.frame, hd = params.head;
  const head = computeHead(params, glasses, eye);
  const innerTempleX = head.innerTempleX;
  const hs = glasses.housing;
  const housingInto = Math.max(...boxCorners(hs.center, new Quaternion(), hs.size).map(head.intrusion));
  const hClear = Number.isFinite(housingInto) ? -housingInto : 99;
  add('Fit', 'headHousing', 'Temple housing clears your head', hClear >= 99 ? 'fully in front of the head' : `${f1(hClear)} mm`, grade(hClear, (v) => v >= 1, (v) => v >= 0),
    hClear >= 1 ? `Head model: lateral orbital rim ${f1(hd.hertelDepth)} mm behind the cornea, ${f1(hd.hertelBase)} mm rim-to-rim; temple gaps ${f1(hd.gap20)} / ${f1(hd.gap40)} mm at 20 / 40 mm behind the hinge.`
      : `The housing reaches ${f1(-hClear)} mm into your head. Reduce its depth or length, or bulge it outward.`);
  const canthusX = eye.pupilCenter.x - hd.canthusOffset;
  // ---- optics arm: does a rigid part connect the prism to the housing?
  const arm = system.arm;
  if (arm) {
    const pts = armSurfacePoints(arm);
    const into = Math.max(...pts.map(head.intrusion));
    const lf = glasses.lenses.R;
    const lensGapArm = Math.min(...pts.map((p) => -p.clone().sub(lf.backCenter).dot(lf.normal)));
    const corneaGap = Math.min(...pts.map((p) => p.distanceTo(eye.corneaVertex)));
    const problems = [];
    if (!arm.reachesPrism) problems.push('does not meet the prism entry face');
    if (into > 0) problems.push(`cuts ${f1(into)} mm into your head`);
    if (lensGapArm < 0.3) problems.push(`hits the spectacle lens (${f1(lensGapArm)} mm)`);
    if (corneaGap < lash) problems.push(`passes ${f1(corneaGap)} mm from the cornea`);
    add('Fit', 'armFit', 'Prism held by an arm to the housing', problems.length ? 'no' : `yes, ${f1(arm.length)} mm arm`, problems.length ? 'fail' : 'pass',
      problems.length ? `The optics arm ${problems.join('; ')}.` : `Ø${f1(2 * (arm.radius + arm.wall))} mm printed tube from the lens to the prism carries it and shields the beam.`);
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

// Engineering diagnostics: turns traced results + coverage analysis into
// pass / adjust / fail checks with short explanations.
// status: 'pass' (green, meets the modeled requirement), 'warn' (yellow,
// needs adjustment), 'fail' (red), 'info' (reported value, no requirement).

import { Vector3 } from 'three';
import { pointInBox } from '../model/glassesGeometry.js';

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
  add('Eye', 'prismClear', 'Prism clearance to cornea', `${f1(prismClear)} mm`,
    grade(prismClear, (v) => v >= 6, (v) => v >= 2),
    prismClear >= 6 ? '' : prismClear >= 2 ? 'Likely eyelash contact (lashes ~8–12 mm long, assumed threshold 6 mm).' : 'Prism touches or nearly touches the cornea.');
  const pz = Math.max(...Object.values(prism.vertices).map((v) => v.z));
  add('Eye', 'prismLens', 'Prism clearance to lens back surface', `${f1(glasses.lensBackZ - pz)} mm`,
    grade(glasses.lensBackZ - pz, (v) => v >= 0.3, (v) => v >= 0), glasses.lensBackZ - pz < 0 ? 'Prism intersects the spectacle lens.' : '');
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
  if (verg.length) {
    const meanV = verg.reduce((s, v) => s + v.mean, 0) / verg.length;
    const maxAst = Math.max(...verg.map((v) => v.astig));
    const blurMrad = verg.reduce((s, v) => s + v.residualMrad, 0) / verg.length;
    const blurArcmin = (blurMrad * 180 * 60) / Math.PI / 1000;
    const defocusBlur = (params.eye.pupilDiameter * Math.abs(meanV)) / 1000; // rad, eye focused at the image
    const supports = meanV <= 0.25 && meanV >= -3 && blurArcmin <= 2 * pixelArcmin;
    const st = meanV <= 0.1 && meanV >= -0.5 && blurArcmin <= pixelArcmin ? 'pass' : supports ? 'warn' : 'fail';
    const imgDist = meanV < -0.05 ? `virtual image ≈ ${f1(1000 / -meanV)} mm away` : meanV > 0.05 ? 'converging bundle: no virtual image the eye can focus' : 'image at optical infinity';
    add('Collimation', 'vergence', 'Measured bundle vergence at pupil', `${f2(meanV)} D`, st,
      `From traced rays: ${imgDist}. Astigmatism up to ${f2(maxAst)} D. Residual aberration spread ${f2(blurArcmin)}′ vs pixel size ${f2(pixelArcmin)}′. Eye focused at infinity would see ≈ ${f1((defocusBlur * 180 * 60) / Math.PI)}′ defocus blur.`);
    add('Collimation', 'virtualImage', 'Focused virtual image', supports ? 'supported' : 'not supported', supports ? (st === 'pass' ? 'pass' : 'warn') : 'fail',
      supports ? 'Ray bundles are near-collimated with sub-2-pixel aberration; a focusable virtual image is consistent with this configuration.'
        : 'The traced bundles do not form a virtual image the eye can focus on (too divergent/convergent or too aberrated).');
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
  const dMin = dEnv.center.clone().sub(new Vector3(dEnv.size.x / 2, dEnv.size.y / 2, dEnv.size.z / 2));
  const dMax = dEnv.center.clone().add(new Vector3(dEnv.envelope.x - dEnv.size.x / 2, dEnv.size.y / 2, dEnv.size.z / 2));
  const driverOk = pointInBox(dMin, glasses.cavity, 0.01) && pointInBox(dMax, glasses.cavity, 0.01);
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

  const summary = { pass: 0, warn: 0, fail: 0, info: 0 };
  for (const c of checks) summary[c.status]++;
  return { checks, summary };
}

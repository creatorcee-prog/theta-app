// Builds the optical scene from parameters, generates OLED emission, runs
// the tracer and reduces the paths into per-pixel and global results.
// No rendering code here.

import { Vector3 } from 'three';
import { computeGlasses, autoFitHousing } from '../model/glassesGeometry.js';
import { computeEye, directionToAngles } from '../model/eye.js';
import { computeOled, computePrism, computeCollimator, computeDriver, computeArm, buildOpticalObjects } from './OpticalComponents.js';
import { trace, coneDirections, eyeDetector } from './RayTracer.js';
import { makeGlass, WAVELENGTHS, criticalAngle, AIR } from './materials.js';
import { partFrame, computeWeights } from '../model/parts.js';
import { boxAbsorber } from './RayTracer.js';
import { computeWaveguide, waveguideObjects } from './Waveguide.js';
import { computePatch, patchObjects } from './Combiner.js';
import { computeLensMount, lensMountObjects } from './LensMount.js';

function boxCornersOf(center, q, size) {
  const out = [];
  for (const sx of [-0.5, 0.5]) for (const sy of [-0.5, 0.5]) for (const sz of [-0.5, 0.5]) out.push(new Vector3(sx * size.x, sy * size.y, sz * size.z).applyQuaternion(q).add(center));
  return out;
}

export function buildSystem(params) {
  if (params.frame.housingAuto) {
    // printed housing shaped around the OLED module and the driver board
    const o = computeOled(params.oled), d = computeDriver(params.driver);
    Object.assign(params.frame, autoFitHousing(params.frame, [...boxCornersOf(o.housing.center, o.quaternion, o.housing.size), ...boxCornersOf(d.envCenter, d.quaternion, d.envelope)]));
  }
  const glasses = computeGlasses(params.frame);
  const eye = computeEye({ ...params.eye, monoPD: params.eye.monoPDRight, side: 1 }, glasses);
  const leftEye = computeEye({ monoPD: params.eye.monoPDLeft, pupilHeight: params.eye.pupilHeightLeft, eyeRelief: params.eye.eyeRelief, pupilDiameter: params.eye.pupilDiameter, constants: params.eye.constants, side: -1 }, glasses);
  const oled = computeOled(params.oled);
  const patched = !!params.patch?.enabled;
  const guided = !patched && !!params.waveguide?.enabled;
  const prism = patched ? computePatch(params, glasses, eye) : guided ? computeWaveguide(params, glasses, eye) : computePrism(params.prism);
  const dispersive = params.sim.wavelengths === 'rgb';
  const prismMaterial = makeGlass('BK7', params.prism.n, { dispersive });
  const lensMaterial = makeGlass('BK7', params.prism.n, { dispersive });
  const specMaterial = makeGlass('CR-39', params.frame.specLensN, { dispersive: false });
  const collimator = computeCollimator(params.collimator, oled, params.prism.n);
  const driver = computeDriver(params.driver);
  const arm = params.frame.optArm === false || patched ? null : computeArm(oled, collimator?.valid ? collimator : null, prism);
  const objects = buildOpticalObjects({
    oled, prism, collimator, driver, arm, glasses, frame: params.frame, prismMaterial, lensMaterial, specMaterial,
    coating: params.prism.coating, guideObjects: patched ? patchObjects(prism, params) : guided ? waveguideObjects(prism, prismMaterial) : null,
  });
  // standoff pins bonding the combiner to the lens back
  const lensMount = params.frame.lensMount === false ? null : computeLensMount(prism, glasses, eye, params.targets.centralClear);
  objects.push(...lensMountObjects(lensMount));
  // placeable hardware parts block light where they are put
  const parts = (params.parts ?? []).map((part) => ({ part, ...partFrame(part, { prism, oled }) }));
  for (const pf of parts) if (pf.part.blocksLight && pf.part.visible !== false) objects.push(boxAbsorber(`part:${pf.part.id}`, pf.part.name, pf.matrix, pf.size));
  objects.push(eyeDetector('eyeR', 'Right eye', eye));
  objects.push(eyeDetector('eyeL', 'Left eye', leftEye));
  return { params, glasses, eye, leftEye, oled, prism, collimator, driver, arm, parts, objects, prismMaterial, lensMount };
}

// Sample pixel positions in [-1,1]^2 (edges included).
export function pixelGrid(nx, ny) {
  const out = [];
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      out.push({ i, j, u: nx === 1 ? 0 : -1 + (2 * i) / (nx - 1), v: ny === 1 ? 0 : -1 + (2 * j) / (ny - 1) });
    }
  }
  return out;
}

export function makeSources(system) {
  const { params, oled } = system;
  const { pixelsX, pixelsY, raysPerPixel, wavelengths } = params.sim;
  const alpha = (params.oled.emissionHalfAngle * Math.PI) / 180;
  const dirsLocal = coneDirections(raysPerPixel, alpha);
  const pixels = pixelGrid(pixelsX, pixelsY);
  const bands = WAVELENGTHS[wavelengths] ?? WAVELENGTHS.mono;
  const brightness = params.oled.brightness / 100;
  const sources = [];
  // Lambertian emitter: equal-solid-angle samples weighted by cos(theta),
  // normalised so the power inside the simulated cone sums to 1 per pixel
  // per band (before brightness).
  const cosSum = dirsLocal.reduce((s, d) => s + d.z, 0);
  for (const band of bands) {
    for (const px of pixels) {
      const origin = oled.pointAt(px.u, px.v);
      for (const dl of dirsLocal) {
        const dir = new Vector3()
          .addScaledVector(oled.xAxis, dl.x).addScaledVector(oled.yAxis, dl.y).addScaledVector(oled.normal, dl.z).normalize();
        sources.push({ origin, dir, weight: (brightness * dl.z) / cosSum, lambda: band.nm, color: band.color, pixel: px, chief: false });
      }
    }
  }
  return { sources, pixels, bands, coneFractionOfHemisphere: Math.sin(alpha) ** 2 };
}

// The display-centre ray along the OLED normal. It is the design axis; it
// is reported separately and not counted in the statistics.
export function chiefSource(system) {
  const { oled, params } = system;
  return {
    origin: oled.pointAt(0, 0), dir: oled.normal.clone(),
    weight: params.oled.brightness / 100, lambda: 550, color: 0xffffff, pixel: { i: -1, j: -1, u: 0, v: 0 }, chief: true,
  };
}

function planeHit(ray, center, normal) {
  const denom = ray.dir.dot(normal);
  if (Math.abs(denom) < 1e-9) return null;
  const t = center.clone().sub(ray.origin).dot(normal) / denom;
  if (t <= 0) return null;
  return ray.origin.clone().addScaledVector(ray.dir, t);
}

export function runSimulation(params) {
  const t0 = typeof performance !== 'undefined' ? performance.now() : Date.now();
  const system = buildSystem(params);
  const { sources, pixels, bands, coneFractionOfHemisphere } = makeSources(system);
  const opts = { ghosts: params.sim.ghosts, ghostMin: params.sim.ghostMin };
  const paths = trace({ objects: system.objects, escapeLength: 45 }, sources, opts);
  const chiefPaths = trace({ objects: system.objects, escapeLength: 45 }, [chiefSource(system)], { ghosts: false });
  // a waveguide splits the chief ray into one copy per facet: the copy that
  // lands nearest the pupil centre is the one the eye uses
  let chief = chiefPaths[0];
  if (system.prism.kind === 'waveguide') {
    const missOf = (pth) => {
      const f = pth.finalRay; if (!f || !pth.outcome.endsWith(':eyeR')) return Infinity;
      const w = system.eye.pupilCenter.clone().sub(f.origin); const t = Math.max(0, w.dot(f.dir));
      return f.origin.clone().addScaledVector(f.dir, t).distanceTo(system.eye.pupilCenter);
    };
    const best = chiefPaths.reduce((b, pth) => (missOf(pth) < missOf(b) ? pth : b), chief);
    chief = best;
  }

  const eye = system.eye;
  const counts = { emitted: sources.length, pupil: 0, eyeMiss: 0, leftPupil: 0, leftEye: 0, escaped: 0, absorbed: {}, leaked: 0, trapped: 0 };
  const power = { emitted: 0, pupil: 0, leftPupil: 0, ghostPupil: 0, leaked: 0, absorbed: 0, lensStray: 0 };
  const hyp = { hits: 0, tir: 0, minInc: Infinity, maxInc: -Infinity, incidences: [] };
  const perPixel = new Map();
  const keyOf = (px) => `${px.i},${px.j}`;
  for (const px of pixels) perPixel.set(keyOf(px), { px, pupilPower: 0, pupilRays: 0, dirSum: new Vector3(), finals: [], arrivals: [] });
  const lensCrossings = [];
  for (const s of sources) power.emitted += s.weight;

  const pupilSources = new Set();
  for (const path of paths) {
    const out = path.outcome;
    if (!path.primary) {
      if (out === 'pupil:eyeR') power.ghostPupil += path.finalWeight;
      continue;
    }
    const pp = perPixel.get(keyOf(path.pixel));
    if (out === 'pupil:eyeR') {
      // count sources, not branches (facets split one source into several paths)
      if (!pupilSources.has(path.source)) { pupilSources.add(path.source); counts.pupil++; }
      power.pupil += path.finalWeight;
      pp.pupilPower += path.finalWeight; pp.pupilRays++;
      pp.dirSum.addScaledVector(path.finalRay.dir, path.finalWeight);
      pp.arrivals.push({ dir: path.finalRay.dir, w: path.finalWeight, lambda: path.lambda });
    } else if (out === 'eyeMiss:eyeR') counts.eyeMiss++;
    else if (out === 'pupil:eyeL') { counts.leftPupil++; power.leftPupil += path.finalWeight; }
    else if (out === 'eyeMiss:eyeL') counts.leftEye++;
    else if (out === 'escaped') counts.escaped++;
    else if (out === 'trapped' || out === 'maxDepth') counts.trapped++;
    else if (out.startsWith('absorbed:')) {
      const k = out.slice(9);
      counts.absorbed[k] = (counts.absorbed[k] ?? 0) + 1;
      // mount pins: only light already heading back toward the eye is image light lost
      if (k.startsWith('mount-')) {
        const sg = path.segments[path.segments.length - 1];
        if (sg && sg.b.clone().sub(sg.a).dot(eye.gaze) < 0) counts.mountEyeward = (counts.mountEyeward ?? 0) + 1;
      }
      power.absorbed += path.finalWeight;
    }
    if (path.segments.some((s) => s.type === 'leak')) { counts.leaked++; power.leaked += path.finalWeight; }
    let afterFacet = false;
    for (const ev of path.events) {
      if (ev.facet) afterFacet = true;
      // TIR surface statistics: the prism hypotenuse, or the waveguide's guiding faces
      if ((ev.obj === 'prism' && ev.face === 'hypotenuse' && !ev.entering) || (ev.obj === 'guide' && !afterFacet && (ev.face === 'guideBack' || ev.face === 'guideFront') && !ev.entering)) {
        hyp.hits++; if (ev.tir) hyp.tir++;
        hyp.minInc = Math.min(hyp.minInc, ev.incidenceDeg); hyp.maxInc = Math.max(hyp.maxInc, ev.incidenceDeg);
        if (hyp.incidences.length < 4000) hyp.incidences.push(ev.incidenceDeg);
      }
      if ((ev.obj === 'specLensR' || ev.obj === 'specLensL') && ev.entering) {
        lensCrossings.push({ point: ev.point, toPupil: out === 'pupil:eyeR', w: path.finalWeight, lens: ev.obj });
        if (out !== 'pupil:eyeR') power.lensStray += path.finalWeight;
      }
    }
    // Free final rays that left all optics (for eye-box sweeps / vergence)
    if (path.finalRay && (out.startsWith('pupil') || out.startsWith('eyeMiss') || out === 'escaped')) {
      const ph = planeHit(path.finalRay, eye.pupilCenter, eye.gaze);
      if (ph && path.finalRay.dir.dot(eye.gaze) < 0) pp.finals.push({ point: ph, origin: path.finalRay.origin, dir: path.finalRay.dir, w: path.finalWeight });
    }
  }

  // Per-pixel reductions
  const pixelResults = [];
  for (const pp of perPixel.values()) {
    const visible = pp.pupilRays > 0;
    const arrival = visible ? pp.dirSum.clone().normalize() : null;
    const apparent = arrival ? arrival.clone().negate() : null;
    const ang = apparent ? directionToAngles(apparent, 1) : null;
    // Available (unclipped) direction: mean of rays crossing the pupil plane
    // within 12 mm of the pupil centre, even if they miss the pupil.
    const near = pp.finals.filter((f) => f.point.distanceTo(eye.pupilCenter) < 12);
    let availAng = null;
    if (near.length) {
      const d = near.reduce((s, f) => s.addScaledVector(f.dir, f.w), new Vector3()).normalize().negate();
      availAng = directionToAngles(d, 1);
    }
    // Vergence as the eye samples it: rays within 1.5 pupil radii of the
    // pupil centre (falls back to the wider set if too few rays land there).
    const inPupil = near.filter((f) => f.point.distanceTo(eye.pupilCenter) <= 1.5 * eye.pupilRadius);
    const verg = bundleVergence(inPupil.length >= 8 ? inPupil : near, eye);
    // angular spread of the light entering the pupil: a coherent image point
    // arrives within a fraction of a degree; light scrambled by extra
    // reflections (prism end faces, edges) arrives from many directions
    let spreadDeg = null;
    if (arrival && pp.arrivals.length >= 2) {
      let s2 = 0, w = 0;
      for (const a of pp.arrivals) { s2 += a.w * a.dir.angleTo(arrival) ** 2; w += a.w; }
      spreadDeg = (Math.sqrt(s2 / w) * 180) / Math.PI;
    }
    pixelResults.push({ ...pp.px, visible, spreadDeg, imaged: visible && (spreadDeg == null || spreadDeg <= 1), pupilRays: pp.pupilRays, pupilPower: pp.pupilPower, apparent, angles: ang, availableAngles: availAng, vergence: verg, finals: pp.finals });
  }

  // Weights: calculated lines follow the current geometry (written back so
  // the parts list shows them); typed values are kept.
  let weights = null;
  if (params.bom) {
    weights = computeWeights(params, system);
    for (const l of weights.lines) {
      const b = params.bom.find((x) => x.id === l.id);
      if (b && b.weightBasis === 'calc' && b.autoWeight !== false) b.weight = l.grams;
    }
  }
  const elapsed = (typeof performance !== 'undefined' ? performance.now() : Date.now()) - t0;
  return {
    system, paths, chief, sources, pixels, bands, pixelResults, counts, power, hyp, lensCrossings, weights,
    coneFractionOfHemisphere, elapsedMs: elapsed,
    critical: { bk7Deg: (criticalAngle(params.prism.n, AIR.n550) * 180) / Math.PI },
  };
}

/**
 * Vergence of a ray bundle at the pupil plane, from a least-squares fit of
 * transverse slope against transverse position along the eye's right and up
 * axes. Diopters; negative = diverging (virtual image in front of the eye),
 * 0 = collimated (image at infinity), positive = converging (no virtual image).
 * Also returns the residual angular spread after removing the fit (mrad).
 */
export function bundleVergence(rays, eye) {
  if (rays.length < 8) return null;
  const fit = (axis) => {
    let sw = 0, sx = 0, ss = 0, sxx = 0, sxs = 0;
    const pts = rays.map((r) => {
      const x = r.point.clone().sub(eye.pupilCenter).dot(axis);
      const dz = -r.dir.dot(eye.gaze);
      const s = r.dir.dot(axis) / dz;
      return { x, s, w: r.w };
    });
    for (const p of pts) { sw += p.w; sx += p.w * p.x; ss += p.w * p.s; sxx += p.w * p.x * p.x; sxs += p.w * p.x * p.s; }
    const varX = sxx / sw - (sx / sw) ** 2;
    if (varX < 0.09) return null; // rays must span >= ~0.3 mm rms for a stable slope
    const slope = (sxs / sw - (sx / sw) * (ss / sw)) / varX; // 1/mm
    const icpt = ss / sw - slope * (sx / sw);
    let res = 0;
    for (const p of pts) res += p.w * (p.s - (icpt + slope * p.x)) ** 2;
    return { slope, rms: Math.sqrt(res / sw) };
  };
  const fx = fit(eye.right), fy = fit(eye.up);
  if (!fx || !fy) return null;
  // Rays travel toward -gaze; for a diverging bundle slope relative to the
  // travel direction is positive. Convert to vergence (D): -1000*slope.
  const Vx = -1000 * fx.slope, Vy = -1000 * fy.slope;
  return { Vx, Vy, mean: (Vx + Vy) / 2, astig: Math.abs(Vx - Vy), residualMrad: 1000 * Math.hypot(fx.rms, fy.rms) / Math.SQRT2 };
}

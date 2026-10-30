// Builds the optical scene from parameters, generates OLED emission, runs
// the tracer and reduces the paths into per-pixel and global results.
// No rendering code here.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { computeGlasses, autoFitHousing } from '../model/glassesGeometry.js';
import { computeEye, directionToAngles } from '../model/eye.js';
import { computeOled, computePrism, computeCollimator, computeDriver, computeArm, buildOpticalObjects } from './OpticalComponents.js';
import { trace, coneDirections, eyeDetector } from './RayTracer.js';
import { makeGlass, WAVELENGTHS, criticalAngle, AIR } from './materials.js';
import { partFrame, computeWeights } from '../model/parts.js';
import { computeHead } from '../model/head.js';
import { boxAbsorber } from './RayTracer.js';
import { computeWaveguide, waveguideObjects } from './Waveguide.js';
import { computePatch, patchObjects, computeFoldPrism, computeFoldMirror } from './Combiner.js';
import { partialMirror } from './RayTracer.js';
import { dielectricSolid } from './RayTracer.js';
import { computeLensMount, lensMountObjects } from './LensMount.js';

function boxCornersOf(center, q, size) {
  const out = [];
  for (const sx of [-0.5, 0.5]) for (const sy of [-0.5, 0.5]) for (const sz of [-0.5, 0.5]) out.push(new Vector3(sx * size.x, sy * size.y, sz * size.z).applyQuaternion(q).add(center));
  return out;
}

// Conformal printed housing (folded designs): a wall around each part instead
// of one box, so the shell follows the splayed temple and the side of the head.
function conformalShell(params, oled, driver, hingeBlock, collimator, glasses, foldMirror) {
  if (params.frame.housingShape !== 'conformal') return null;
  const w = params.frame.housingWall;
  const grow = (s) => new Vector3(s.x + 2 * w, s.y + 2 * w, s.z + 2 * w);
  const parts = [
    { id: 'oled', label: 'display module', center: oled.housing.center, quaternion: oled.quaternion, size: grow(oled.housing.size) },
    { id: 'driver', label: 'driver board', center: driver.envCenter, quaternion: driver.quaternion, size: grow(driver.envelope) },
  ];
  if (collimator) {
    // printed barrel around the whole lens, from the display module to the lens
    const br = Math.max(collimator.apertureRadius + 0.25, (collimator.glassDiameter ?? 0) / 2 + 0.1) + 0.8;
    const len = Math.max(0.5, collimator.center.clone().sub(oled.center).dot(oled.normal) + (collimator.thickness || 0) + 0.5);
    parts.push({ id: 'barrel', label: 'lens barrel', center: oled.center.clone().addScaledVector(oled.normal, len / 2), quaternion: oled.quaternion, size: new Vector3(2 * br, 2 * br, len) });
  }
  if (hingeBlock) parts.push({ id: 'hinge', label: 'hinge block', center: hingeBlock.center, quaternion: new Quaternion(), size: hingeBlock.size });
  if (foldMirror) {
    // holder around the mirror tile at the front of the temple
    const n = foldMirror.normal, ref = Math.abs(n.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
    const ex = new Vector3().crossVectors(ref, n).normalize(), ey = new Vector3().crossVectors(n, ex);
    const q = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(ex, ey, n));
    parts.push({ id: 'mirror', label: 'fold-mirror holder', center: foldMirror.center.clone().addScaledVector(n, -1), quaternion: q, size: new Vector3(2 * foldMirror.radius + 2 * w, 2 * foldMirror.radius + 2 * w, 2 + 2 * w) });
  }
  const points = parts.flatMap((p) => boxCornersOf(p.center, p.quaternion, p.size));
  // is every part joined (≤ 1 mm, bounding boxes) through the others to the right temple?
  const aabb = (corners) => ({ min: new Vector3(Math.min(...corners.map((c) => c.x)), Math.min(...corners.map((c) => c.y)), Math.min(...corners.map((c) => c.z))), max: new Vector3(Math.max(...corners.map((c) => c.x)), Math.max(...corners.map((c) => c.y)), Math.max(...corners.map((c) => c.z))) });
  const gap = (a, b) => Math.max(0, a.min.x - b.max.x, b.min.x - a.max.x, a.min.y - b.max.y, b.min.y - a.max.y, a.min.z - b.max.z, b.min.z - a.max.z);
  const t = glasses.temples.find((q) => q.side === 1);
  const nodes = [{ id: 'temple', box: aabb(boxCornersOf(t.center, t.quaternion, t.size)) }, ...parts.map((p) => ({ id: p.id, label: p.label, box: aabb(boxCornersOf(p.center, p.quaternion, p.size)) }))];
  const reached = new Set(['temple']);
  for (let changed = true; changed;) {
    changed = false;
    for (const n of nodes) if (!reached.has(n.id) && nodes.some((m) => reached.has(m.id) && gap(n.box, m.box) <= 1)) { reached.add(n.id); changed = true; }
  }
  const loose = nodes.filter((n) => !reached.has(n.id)).map((n) => n.label);
  return { parts, points, wall: w, loose };
}

export function buildSystem(params) {
  if (params.frame.housingAuto) {
    // printed housing shaped around the OLED module and the driver board, and,
    // when the optics are folded along the temple, the lens barrel and fold prism
    const o = computeOled(params.oled), d = computeDriver(params.driver);
    const pts = [...boxCornersOf(o.housing.center, o.quaternion, o.housing.size), ...boxCornersOf(d.envCenter, d.quaternion, d.envelope)];
    if (params.patch?.enabled) {
      const g0 = computeGlasses(params.frame);
      const e0 = computeEye({ ...params.eye, monoPD: params.eye.monoPDRight, side: 1 }, g0);
      // (the fold prism gets its own hinge block, see below)
      const c0 = computeCollimator(params.collimator, o, params.collimator.n ?? params.prism.n);
      if (c0) {
        const r0 = Math.max(c0.apertureRadius + 0.25, (c0.glassDiameter ?? 0) / 2 + 0.1) + 0.8;
        const e1 = new Vector3().crossVectors(c0.axis, Math.abs(c0.axis.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0)).normalize();
        const e2 = new Vector3().crossVectors(c0.axis, e1);
        for (const t of [0, (c0.center.clone().sub(o.center).dot(o.normal)) + (c0.thickness || 0)]) for (let k = 0; k < 8; k++) {
          const a = (k / 8) * Math.PI * 2;
          pts.push(o.center.clone().addScaledVector(o.normal, t).addScaledVector(e1, r0 * Math.cos(a)).addScaledVector(e2, r0 * Math.sin(a)));
        }
      }
    }
    Object.assign(params.frame, autoFitHousing(params.frame, pts));
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
  const lensMaterial = makeGlass('BK7', params.collimator.n ?? params.prism.n, { dispersive: dispersive && params.collimator.n == null });
  const specMaterial = makeGlass('CR-39', params.frame.specLensN, { dispersive: false });
  const collimator = computeCollimator(params.collimator, oled, params.collimator.n ?? params.prism.n);
  const driver = computeDriver(params.driver);
  const fold = patched ? computeFoldPrism(params, prism) : null;
  const foldMirror = patched ? computeFoldMirror(params, prism, glasses) : null;
  // hinge block: printed block around the fold prism, in the endpiece, joined to
  // the temple housing (an L-shaped housing overall)
  let hingeBlock = null;
  if (fold) {
    const wall = params.frame.housingWall + 0.6;
    const vs = Object.values(fold.vertices);
    const min = new Vector3(Math.min(...vs.map((q) => q.x)) - wall, Math.min(...vs.map((q) => q.y)) - wall, Math.min(...vs.map((q) => q.z)) - wall);
    const max = new Vector3(Math.max(...vs.map((q) => q.x)) + wall, Math.max(...vs.map((q) => q.y)) + wall, Math.max(...vs.map((q) => q.z)) + wall);
    const h = glasses.housing;
    const hMin = h.center.clone().sub(h.size.clone().multiplyScalar(0.5)), hMax = h.center.clone().add(h.size.clone().multiplyScalar(0.5));
    // gap between the block and the temple housing along each axis (0 = touching/overlapping)
    const gap = Math.max(0, min.x - hMax.x, hMin.x - max.x, min.y - hMax.y, hMin.y - max.y, min.z - hMax.z, hMin.z - max.z);
    hingeBlock = { min, max, center: min.clone().add(max).multiplyScalar(0.5), size: max.clone().sub(min), gap, frontZ: params.frame.rimDepth / 2 };
  }
  const arm = params.frame.optArm === false || patched ? null : computeArm(oled, collimator?.valid ? collimator : null, prism);
  const objects = buildOpticalObjects({
    oled, prism, collimator, driver, arm, glasses, frame: params.frame, prismMaterial, lensMaterial, specMaterial,
    coating: params.prism.coating, embeddedFacet: patched ? prism.embeddedFace ?? null : null, guideObjects: patched ? [...patchObjects(prism, params), ...(fold ? [dielectricSolid('fold', 'Fold prism', prismMaterial, Object.values(fold.faces))] : []),
      // back-silvered glass tile: silver behind thin glass, R ≈ 0.85 overall (assumed)
      ...(foldMirror ? [partialMirror('foldMirror', 'Fold mirror', foldMirror.face, params.patch.inline.mirrorR ?? 0.85, 0)] : [])] : guided ? waveguideObjects(prism, prismMaterial) : null,
  });
  // standoff pins bonding the combiner to the lens back
  const lensMount = params.frame.lensMount === false ? null : computeLensMount(prism, glasses, eye, params.targets.centralClear);
  objects.push(...lensMountObjects(lensMount));
  // placeable hardware parts block light where they are put
  const parts = (params.parts ?? []).map((part) => ({ part, ...partFrame(part, { prism, oled }) }));
  for (const pf of parts) if (pf.part.blocksLight && pf.part.visible !== false) objects.push(boxAbsorber(`part:${pf.part.id}`, pf.part.name, pf.matrix, pf.size));
  objects.push(eyeDetector('eyeR', 'Right eye', eye));
  objects.push(eyeDetector('eyeL', 'Left eye', leftEye));
  return { params, glasses, eye, leftEye, oled, prism, collimator, driver, arm, parts, objects, prismMaterial, lensMount, fold, foldMirror, hingeBlock, housingShell: conformalShell(params, oled, driver, hingeBlock, collimator?.valid ? collimator : null, glasses, foldMirror) };
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
  // The head is not a traced surface, so any path that runs through it (e.g. a
  // beam skimming past the outer corner of the eye) is stopped here.
  const head = computeHead(params, system.glasses, eye);
  const throughHead = (path) => {
    for (const sg of path.segments) {
      const L = sg.a.distanceTo(sg.b), n = Math.max(2, Math.ceil(L / 1.5));
      for (let i = 1; i < n; i++) { const q = sg.a.clone().lerp(sg.b, i / n); if (head.intrusion(q) > 0.3) return q; }
    }
    return null;
  };
  let headBlocked = 0;
  for (const path of [...paths, ...chiefPaths]) {
    if (!path.outcome.includes('eyeR') && !path.outcome.includes('eyeL')) continue;
    if (throughHead(path)) { path.outcome = 'absorbed:head'; path.finalRay = null; headBlocked++; }
  }
  const counts = { emitted: sources.length, pupil: 0, eyeMiss: 0, leftPupil: 0, leftEye: 0, escaped: 0, absorbed: {}, leaked: 0, trapped: 0, headBlocked };
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
      if ((ev.obj === 'prism' && ev.face === 'hypotenuse' && !ev.entering) || (ev.obj === 'fold' && ev.face === 'hypotenuse' && !ev.entering) || (ev.obj === 'guide' && !afterFacet && (ev.face === 'guideBack' || ev.face === 'guideFront') && !ev.entering)) {
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
    let near = pp.finals.filter((f) => f.point.distanceTo(eye.pupilCenter) < 12);
    // keep the rays of the main image path: stray rays (an extra reflection,
    // light skirting a part) reach the pupil plane from a different direction
    // and would corrupt the focus fit. Image rays of one pixel differ by well
    // under 3° even 10 D out of focus over the 12 mm region.
    if (near.length >= 3) {
      const med = (k) => { const v = near.map((f) => f.dir[k]).sort((a, b) => a - b); return v[v.length >> 1]; };
      const m = new Vector3(med('x'), med('y'), med('z')).normalize();
      const cos3 = Math.cos((3 * Math.PI) / 180);
      const main = near.filter((f) => f.dir.dot(m) >= cos3);
      if (main.length >= 3) near = main;
    }
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

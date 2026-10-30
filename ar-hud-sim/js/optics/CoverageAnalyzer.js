// Lens coverage, visual-field coverage, hardware occlusion and eye-box
// analysis. Operates only on traced results; nothing here creates rays that
// the tracer did not produce.

import { Vector3, Quaternion } from 'three';
import { computeEye, directionToAngles, anglesToDirection } from '../model/eye.js';

// ---------------------------------------------------------------- 2D helpers

export function convexHull(points) {
  const pts = points.map((p) => [p[0], p[1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  upper.pop(); lower.pop();
  return lower.concat(upper); // CCW
}

export function polygonArea(poly) {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

// Sutherland-Hodgman: clip `subject` by convex CCW `clip`.
export function clipPolygon(subject, clip) {
  let out = subject;
  for (let i = 0; i < clip.length && out.length; i++) {
    const a = clip[i], b = clip[(i + 1) % clip.length];
    const inside = (p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0;
    const inter = (p, q) => {
      const x1 = p[0], y1 = p[1], x2 = q[0], y2 = q[1];
      const x3 = a[0], y3 = a[1], x4 = b[0], y4 = b[1];
      const den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
      const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den;
      return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)];
    };
    const input = out;
    out = [];
    for (let j = 0; j < input.length; j++) {
      const p = input[j], q = input[(j + 1) % input.length];
      const pi = inside(p), qi = inside(q);
      if (pi) out.push(p);
      if (pi !== qi) out.push(inter(p, q));
    }
  }
  return out;
}

function pointInConvex(poly, p) {
  if (poly.length < 3) return false;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    if ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < 0) return false;
  }
  return true;
}

function distToSegment(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

// Minimum angular radius (deg) of a hull from the straight-ahead axis.
export function minRadius(hull) {
  if (!hull.length) return Infinity;
  if (hull.length >= 3 && pointInConvex(hull, [0, 0])) return 0;
  let m = Infinity;
  for (let i = 0; i < hull.length; i++) m = Math.min(m, distToSegment([0, 0], hull[i], hull[(i + 1) % hull.length]));
  return m;
}

// ---------------------------------------------------------------- analysis

function projectToLens(origin, dir, z) {
  if (Math.abs(dir.z) < 1e-9) return null;
  const t = (z - origin.z) / dir.z;
  if (t <= 0) return null;
  return origin.clone().addScaledVector(dir, t);
}

function hardwarePoints(system) {
  const { prism, oled, collimator, glasses } = system;
  const groups = {};
  groups.prism = Object.values(prism.vertices);
  // subdivide prism edges so silhouettes near 90 deg stay sensible
  const pv = prism.vertices, edges = [['A+', 'B+'], ['B+', 'C+'], ['C+', 'A+'], ['A-', 'B-'], ['B-', 'C-'], ['C-', 'A-'], ['A+', 'A-'], ['B+', 'B-'], ['C+', 'C-']];
  for (const [a, b] of edges) for (let k = 1; k < 4; k++) groups.prism.push(pv[a].clone().lerp(pv[b], k / 4));
  const boxCorners = (center, q, size) => {
    const out = [];
    for (const sx of [-0.5, 0.5]) for (const sy of [-0.5, 0.5]) for (const sz of [-0.5, 0.5]) {
      out.push(new Vector3(sx * size.x, sy * size.y, sz * size.z).applyQuaternion(q).add(center));
    }
    return out;
  };
  groups.oled = boxCorners(oled.housing.center, oled.quaternion, oled.housing.size);
  if (collimator) {
    const pts = [];
    const ref = Math.abs(collimator.axis.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
    const e1 = new Vector3().crossVectors(collimator.axis, ref).normalize();
    const e2 = new Vector3().crossVectors(collimator.axis, e1).normalize();
    const r = collimator.apertureRadius + 1.5;
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      for (const h of [0, collimator.thickness || 0.5]) {
        pts.push(collimator.center.clone().addScaledVector(e1, r * Math.cos(a)).addScaledVector(e2, r * Math.sin(a)).addScaledVector(collimator.axis, h));
      }
    }
    groups.collimator = pts;
  }
  const h = glasses.housing;
  groups.housing = boxCorners(h.center, new Quaternion(), h.size);
  return groups;
}

function angularHull(points, eye) {
  const pts = [];
  for (const p of points) {
    const d = p.clone().sub(eye.pupilCenter);
    if (d.z <= 0.5) continue; // behind or beside the eye: outside the forward field
    const a = directionToAngles(d.normalize(), 1);
    pts.push([a.h, a.v]);
  }
  return pts.length >= 3 ? convexHull(pts) : pts;
}

// Eye-box: visible field fraction for pupil centres offset on the pupil
// plane. Re-uses the traced final rays (occlusion changes by the moved eye
// itself are ignored).
function eyeboxSweep(pixelResults, eye, range = 6, step = 0.5) {
  const n = Math.round((2 * range) / step) + 1;
  const grid = [];
  const r2 = eye.pupilRadius ** 2;
  const total = pixelResults.length;
  for (let iy = 0; iy < n; iy++) {
    for (let ix = 0; ix < n; ix++) {
      const ox = -range + ix * step, oy = -range + iy * step;
      const c = eye.pupilCenter.clone().addScaledVector(eye.right, ox).addScaledVector(eye.up, oy);
      let vis = 0;
      for (const px of pixelResults) {
        if (px.finals.some((f) => f.point.distanceToSquared(c) <= r2)) vis++;
      }
      grid.push({ ox, oy, frac: total ? vis / total : 0 });
    }
  }
  const area = (thr) => grid.filter((g) => g.frac >= thr - 1e-9).length * step * step;
  const extent = (thr, axis) => {
    const along = grid.filter((g) => (axis === 'x' ? Math.abs(g.oy) < 1e-9 : Math.abs(g.ox) < 1e-9) && g.frac >= thr - 1e-9);
    if (!along.length) return 0;
    const vals = along.map((g) => (axis === 'x' ? g.ox : g.oy));
    return Math.max(...vals) - Math.min(...vals) + step;
  };
  const best = grid.reduce((b, g) => (g.frac > b.frac ? g : b), { frac: -1 });
  return {
    grid, n, step, range,
    full: { area: area(1), width: extent(1, 'x'), height: extent(1, 'y') },
    half: { area: area(0.5), width: extent(0.5, 'x'), height: extent(0.5, 'y') },
    best,
  };
}

function visibleWithEye(pixelResults, eye) {
  let vis = 0;
  const r2 = eye.pupilRadius ** 2;
  for (const px of pixelResults) {
    const ok = px.finals.some((f) => {
      const denom = f.dir.dot(eye.gaze);
      if (denom >= 0) return false;
      const t = eye.pupilCenter.clone().sub(f.origin).dot(eye.gaze) / denom;
      if (t <= 0) return false;
      return f.origin.clone().addScaledVector(f.dir, t).distanceToSquared(eye.pupilCenter) <= r2;
    });
    if (ok) vis++;
  }
  return pixelResults.length ? vis / pixelResults.length : 0;
}

export function analyzeCoverage(results) {
  const { system, pixelResults, counts, power } = results;
  const { glasses, eye, params } = system;
  const lc = glasses.rightLensCenter;
  const lensPoly = glasses.outline.map(([x, y]) => [x, y]);
  const lensArea = glasses.lensArea;
  const lensZ = 0;

  // ---- visual field from visible pixels
  const visible = pixelResults.filter((p) => p.visible);
  const field = { visiblePixels: visible.length, totalPixels: pixelResults.length };
  if (visible.length) {
    const hs = visible.map((p) => p.angles.h), vs = visible.map((p) => p.angles.v);
    field.hMin = Math.min(...hs); field.hMax = Math.max(...hs);
    field.vMin = Math.min(...vs); field.vMax = Math.max(...vs);
    field.hfov = field.hMax - field.hMin; field.vfov = field.vMax - field.vMin;
    field.hCenter = (field.hMin + field.hMax) / 2; field.vCenter = (field.vMin + field.vMax) / 2;
    field.hull = convexHull(visible.map((p) => [p.angles.h, p.angles.v]));
    field.minRadius = minRadius(field.hull);
    field.radialOffset = Math.hypot(field.hCenter, field.vCenter);
  }
  const avail = pixelResults.filter((p) => p.availableAngles);
  if (avail.length) {
    const hs = avail.map((p) => p.availableAngles.h), vs = avail.map((p) => p.availableAngles.v);
    field.availHfov = Math.max(...hs) - Math.min(...hs);
    field.availVfov = Math.max(...vs) - Math.min(...vs);
    field.availHull = convexHull(avail.map((p) => [p.availableAngles.h, p.availableAngles.v]));
  }
  field.clippedPct = 100 * (1 - visible.length / Math.max(1, pixelResults.length));
  field.pupilRayPct = (100 * counts.pupil) / Math.max(1, counts.emitted);
  field.pupilPowerPct = (100 * power.pupil) / Math.max(1e-12, power.emitted);

  // ---- apparent lens footprint (HUD back-projected from the pupil centre)
  const lens = { area: lensArea };
  const fp = [];
  for (const p of visible) {
    const hit = projectToLens(eye.pupilCenter, p.apparent, lensZ);
    if (hit) fp.push([hit.x - lc.x, hit.y - lc.y]);
  }
  lens.footprint = fp.length >= 3 ? convexHull(fp) : [];
  lens.footprintArea = lens.footprint.length >= 3 ? polygonArea(lens.footprint) : 0;
  lens.inside = lens.footprint.length >= 3 ? clipPolygon(lens.footprint, lensPoly) : [];
  lens.insideArea = lens.inside.length >= 3 ? polygonArea(lens.inside) : 0;
  lens.outsideArea = Math.max(0, lens.footprintArea - lens.insideArea);
  lens.coveragePct = (100 * lens.insideArea) / lensArea;
  lens.outsidePct = lens.footprintArea ? (100 * lens.outsideArea) / lens.footprintArea : 0;

  // What the brief's FOV target would cover if met exactly at the target
  // position (upper bound reference, same projection).
  const t = params.targets;
  const tgtPts = [];
  const N = 12;
  for (let i = 0; i <= N; i++) for (const sv of [-1, 1]) {
    tgtPts.push([t.azimuth - t.hfov / 2 + (t.hfov * i) / N, t.elevation + (sv * t.vfov) / 2]);
    tgtPts.push([t.azimuth + (sv * t.hfov) / 2, t.elevation - t.vfov / 2 + (t.vfov * i) / N]);
  }
  const tgtFp = tgtPts.map(([h, v]) => projectToLens(eye.pupilCenter, anglesToDirection(h, v, 1), lensZ)).filter(Boolean).map((p) => [p.x - lc.x, p.y - lc.y]);
  const tgtHull = convexHull(tgtFp);
  const tgtInside = clipPolygon(tgtHull, lensPoly);
  lens.targetFovCoveragePct = (100 * (tgtInside.length >= 3 ? polygonArea(tgtInside) : 0)) / lensArea;
  lens.targetHull = tgtHull;

  // Field that 40-50% of the lens corresponds to: whole-lens angular size
  const lensAng = lensPoly.map(([x, y]) => {
    const d = new Vector3(lc.x + x, lc.y + y, lensZ).sub(eye.pupilCenter).normalize();
    const a = directionToAngles(d, 1);
    return [a.h, a.v];
  });
  const lh = lensAng.map((a) => a[0]), lv = lensAng.map((a) => a[1]);
  lens.wholeLensHfov = Math.max(...lh) - Math.min(...lh);
  lens.wholeLensVfov = Math.max(...lv) - Math.min(...lv);
  lens.angularOutline = lensAng;

  // ---- physical beam footprint on the lens (rays that actually cross it)
  const phys = results.lensCrossings.filter((c) => c.lens === 'specLensR');
  const physPupil = phys.filter((c) => c.toPupil).map((c) => [c.point.x - lc.x, c.point.y - lc.y]);
  lens.physicalFootprint = physPupil.length >= 3 ? convexHull(physPupil) : [];
  lens.physicalArea = lens.physicalFootprint.length >= 3 ? polygonArea(clipPolygon(lens.physicalFootprint, lensPoly)) : 0;
  lens.strayHits = phys.filter((c) => !c.toPupil).map((c) => [c.point.x - lc.x, c.point.y - lc.y]);
  lens.strayPowerPct = (100 * power.lensStray) / Math.max(1e-12, power.emitted);

  // ---- hardware occlusion in the angular field
  const hw = hardwarePoints(system);
  const occlusion = {};
  for (const [k, pts] of Object.entries(hw)) {
    const hull = angularHull(pts, eye);
    occlusion[k] = { hull, minRadius: hull.length >= 3 ? minRadius(hull) : Infinity };
  }
  occlusion.minRadius = Math.min(...Object.values(occlusion).map((o) => o.minRadius ?? Infinity));
  // Prism solid-angle footprint as fraction of the lens's angular area
  const lensHull = convexHull(lensAng);
  const prismInLens = occlusion.prism.hull.length >= 3 ? clipPolygon(occlusion.prism.hull, lensHull) : [];
  occlusion.prismLensPct = lensHull.length >= 3 ? (100 * (prismInLens.length >= 3 ? polygonArea(prismInLens) : 0)) / polygonArea(lensHull) : 0;

  // ---- eye-box and gaze
  const eyebox = eyeboxSweep(pixelResults, eye);
  let gaze = null;
  if (field.hCenter != null) {
    const gEye = computeEye({ ...params.eye, side: 1, gazeYaw: field.hCenter, gazePitch: field.vCenter }, glasses);
    gaze = { yaw: field.hCenter, pitch: field.vCenter, visibleFrac: visibleWithEye(pixelResults, gEye), pupilShift: gEye.pupilCenter.distanceTo(eye.pupilCenter) };
  }

  return { field, lens, occlusion, eyebox, gaze };
}

// Pure geometry of the glasses frame (no rendering). Millimetres.
// World frame (right-handed): +z = forward (viewing direction), +y = up,
// -x = wearer's RIGHT. The right eye, right lens and display temple sit at x < 0.
// Origin: centre of the nose bridge, in the mid-plane of the lenses.

import { Vector3, Matrix4, Quaternion } from 'three';

export function roundedRectOutline(w, h, r, segmentsPerCorner = 10) {
  const rr = Math.min(r, w / 2, h / 2);
  const pts = [];
  const corners = [
    [w / 2 - rr, h / 2 - rr, 0],
    [-w / 2 + rr, h / 2 - rr, Math.PI / 2],
    [-w / 2 + rr, -h / 2 + rr, Math.PI],
    [w / 2 - rr, -h / 2 + rr, (3 * Math.PI) / 2],
  ];
  for (const [cx, cy, a0] of corners) {
    for (let i = 0; i <= segmentsPerCorner; i++) {
      const a = a0 + (i / segmentsPerCorner) * (Math.PI / 2);
      pts.push([cx + rr * Math.cos(a), cy + rr * Math.sin(a)]);
    }
  }
  return pts; // counter-clockwise seen from +z
}

// Superellipse |x/a|^n + |y/b|^n = 1 (n = 2: ellipse; larger n: squarer).
export function superellipseOutline(w, h, n, count = 72) {
  const pts = [];
  for (let i = 0; i < count; i++) {
    const t = (i / count) * Math.PI * 2;
    const c = Math.cos(t), s = Math.sin(t);
    pts.push([(w / 2) * Math.sign(c) * Math.abs(c) ** (2 / n), (h / 2) * Math.sign(s) * Math.abs(s) ** (2 / n)]);
  }
  return pts;
}

// "x,y; x,y; ..." in mm about the lens centre, as seen in a front photo of
// the right lens (x to the photo's right = toward the nose, y up). Returns
// null when fewer than 3 points parse.
export function parseOutline(text) {
  const nums = String(text ?? '').split(/[;\n]+/).map((pair) => pair.split(/[ ,\t]+/).filter(Boolean).map(Number))
    .filter((v) => v.length >= 2 && v.every(Number.isFinite)).map((v) => [v[0], v[1]]);
  return nums.length >= 3 ? nums : null;
}

function polyArea(poly) {
  let a = 0;
  for (let i = 0; i < poly.length; i++) { const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length]; a += x1 * y2 - x2 * y1; }
  return a / 2;
}

function hull(points) {
  const pts = points.map((p) => [p[0], p[1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const p of pts) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  lo.pop(); up.pop();
  return lo.concat(up);
}

export function lensOutline(frame) {
  const { lensWidth: w, lensHeight: h, lensCorner: r, lensShape = 'roundrect', lensExponent = 4, customOutline = '' } = frame;
  if (lensShape === 'superellipse') return { outline: superellipseOutline(w, h, lensExponent), note: '' };
  if (lensShape === 'custom') {
    const pts = parseOutline(customOutline);
    if (!pts) return { outline: roundedRectOutline(w, h, r), note: 'Custom outline needs at least 3 "x,y" points; using the rounded rectangle.' };
    let poly = polyArea(pts) < 0 ? pts.slice().reverse() : pts;
    const hl = hull(poly);
    const convex = Math.abs(Math.abs(polyArea(hl)) - Math.abs(polyArea(poly))) < 1e-6 * Math.abs(polyArea(poly)) + 1e-9;
    return { outline: convex ? poly : hl, note: convex ? '' : 'Custom outline is not convex; its convex hull is used (the tracer and the coverage clip need a convex lens).' };
  }
  return { outline: roundedRectOutline(w, h, r), note: '' };
}

export function roundedRectArea(w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  return w * h - (4 - Math.PI) * rr * rr;
}

export function computeGlasses(frame) {
  const {
    lensWidth, lensHeight, lensCorner, lensThickness, bridge, endpiece,
    rimDepth, templeLength, templeThickness, templeHeight, templeSplayDeg,
    housingLength, housingDepth, housingHeight, housingWall, hingeY = 0, housingOffsetY = 0, housingOffsetZ = 0, housingOutward = 0,
  } = frame;
  const rightLensCenter = new Vector3(-(bridge / 2 + lensWidth / 2), 0, 0);
  const leftLensCenter = new Vector3(-rightLensCenter.x, 0, 0);
  const hingeX = bridge / 2 + lensWidth + endpiece;
  const hingeZ = -rimDepth / 2 - 1;
  const { outline, note: outlineNote } = lensOutline(frame);
  const lensArea = Math.abs(polyArea(outline));
  const outlineMinY = Math.min(...outline.map((p) => p[1]));
  // Each lens has its own frame: wrap (temporal edge toward the face) about
  // y, then pantoscopic tilt (bottom edge toward the face) about the lens's
  // own x axis. Local z = lens normal pointing forward.
  const lensFrame = (center, side) => {
    // rotation about +y by theta moves the point (x, 0, 0) to z = -x sin(theta):
    // theta = -side * wrap sends each lens's temporal edge backward.
    const qWrap = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), (-side * (frame.wrapDeg ?? 0) * Math.PI) / 180);
    const qTilt = new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), ((frame.pantoTiltDeg ?? 0) * Math.PI) / 180);
    const q = qWrap.multiply(qTilt);
    const qi = q.clone().invert();
    const normal = new Vector3(0, 0, 1).applyQuaternion(q);
    const toWorld = (x, y, z = 0) => new Vector3(x, y, z).applyQuaternion(q).add(center);
    const toLocal = (p) => p.clone().sub(center).applyQuaternion(qi);
    const backCenter = toWorld(0, 0, -lensThickness / 2);
    return { center, side, quaternion: q, normal, toWorld, toLocal, backCenter, frontCenter: toWorld(0, 0, lensThickness / 2) };
  };
  const lenses = { R: lensFrame(rightLensCenter, 1), L: lensFrame(leftLensCenter, -1) };
  // lensBackZ: z of the right lens back surface at its centre (eye relief datum)
  const lensBackZ = lenses.R.backCenter.z;
  const lensFrontZ = lenses.R.frontCenter.z;

  // Temples: boxes from the hinge backwards, splayed outward by templeSplayDeg.
  const temples = [1, -1].map((side) => {
    // side: +1 right temple (x < 0), -1 left temple; both splay outward
    const splay = (side * templeSplayDeg * Math.PI) / 180;
    const q = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), splay);
    const dir = new Vector3(0, 0, -1).applyQuaternion(q);
    const start = new Vector3(-side * hingeX, hingeY, hingeZ);
    const center = start.clone().addScaledVector(dir, templeLength / 2);
    const m = new Matrix4().compose(center, q, new Vector3(1, 1, 1));
    return { side, start, dir, center, quaternion: q, matrix: m, size: new Vector3(templeThickness, templeHeight, templeLength) };
  });

  // Right-temple display housing near the hinge. It bulges inward (toward
  // the face, +x) by housingDepth from the temple's outer surface and,
  // optionally, outward (away from the head) by housingOutward.
  const outerX = -(hingeX + templeThickness / 2);
  const housing = {
    min: new Vector3(outerX - housingOutward, hingeY + housingOffsetY - housingHeight / 2, hingeZ - housingOffsetZ - housingLength),
    max: new Vector3(outerX + housingDepth, hingeY + housingOffsetY + housingHeight / 2, hingeZ - housingOffsetZ),
  };
  housing.center = housing.min.clone().add(housing.max).multiplyScalar(0.5);
  housing.size = housing.max.clone().sub(housing.min);
  const cavity = {
    min: housing.min.clone().addScalar(housingWall),
    max: housing.max.clone().subScalar(housingWall),
  };
  cavity.center = cavity.min.clone().add(cavity.max).multiplyScalar(0.5);
  cavity.size = cavity.max.clone().sub(cavity.min);

  return {
    rightLensCenter, leftLensCenter, hingeX, hingeZ, outline, outlineNote, lensArea, lenses, outlineMinY,
    lensBackZ, lensFrontZ, temples, housing, cavity,
    hingeY, hinges: [new Vector3(-hingeX, hingeY, hingeZ), new Vector3(hingeX, hingeY, hingeZ)],
  };
}

// Outward offset of a CCW convex polygon by d (miter at each vertex).
export function offsetPolygon(poly, d) {
  const n = poly.length;
  return poly.map((p, i) => {
    const a = poly[(i - 1 + n) % n], b = poly[(i + 1) % n];
    const e1 = [p[0] - a[0], p[1] - a[1]], e2 = [b[0] - p[0], b[1] - p[1]];
    const n1 = norm2([e1[1], -e1[0]]), n2 = norm2([e2[1], -e2[0]]);
    const m = norm2([n1[0] + n2[0], n1[1] + n2[1]]);
    const k = d / Math.max(0.3, m[0] * n1[0] + m[1] * n1[1]);
    return [p[0] + m[0] * k, p[1] + m[1] * k];
  });
}
const norm2 = (v) => { const l = Math.hypot(v[0], v[1]) || 1; return [v[0] / l, v[1] / l]; };

export function pointInBox(p, box, margin = 0) {
  return p.x >= box.min.x - margin && p.x <= box.max.x + margin &&
    p.y >= box.min.y - margin && p.y <= box.max.y + margin &&
    p.z >= box.min.z - margin && p.z <= box.max.z + margin;
}

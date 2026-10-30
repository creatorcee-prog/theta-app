// Curved partial-mirror combiner ("patch"): a thin shell behind the right
// spectacle lens, partially mirrored on its concave (eye-side) face. Light from
// a display in the temple reflects off it into the pupil, as in Focals-style
// glasses. The shell's power (2/R) and the collimator together set focus;
// hitting a curved mirror off-axis adds astigmatism, which the tracer measures.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { conicFace, partialMirror, polygonFace, refract, discFace } from './RayTracer.js';
import { computePrism, eulerDegFromBasis } from './OpticalComponents.js';
import { anglesToDirection } from '../model/eye.js';

// Right temple axes: S hinge point on the temple centre line, d backward along
// the temple, i inward (toward the head), up.
export function templeAxes(glasses) {
  const t = glasses.temples.find((q) => q.side === 1);
  const d = t.dir.clone().normalize();
  const i = new Vector3(1, 0, 0).addScaledVector(d, -d.x).normalize();
  const up = new Vector3().crossVectors(d, i).normalize();
  if (up.y < 0) up.negate();
  return { S: t.start.clone(), d, i, up };
}

// In-line route: the display and lens lie along the temple and a small fold
// mirror at the front of the temple turns the beam toward the reflector, so
// everything folds with the temple. Its position on the temple:
export function inlineFoldPoint(p, glasses) {
  const I = p.patch.inline, { S, d, i, up } = templeAxes(glasses);
  return S.addScaledVector(d, I.dist).addScaledVector(i, I.inset).addScaledVector(up, I.dy);
}

// The patch is tilted, so its rim reaches further toward the lens than its
// vertex: slide it along the HUD line until every rim point keeps `gap`.
export function computePatch(p, glasses, eye) {
  if (p.patch.mode === 'lensback') return lensBackReflector(p, glasses, eye);
  if (p.patch.mode === 'embedded') return embeddedReflector(p, glasses, eye);
  const lf = glasses.lenses.R;
  let shift = 0;
  for (let i = 0; i < 3; i++) {
    const g = patchAt(p, glasses, eye, shift);
    const minDepth = Math.min(...Object.values(g.vertices).map((q) => -q.clone().sub(lf.backCenter).dot(lf.normal)));
    const err = p.patch.gap - minDepth;
    if (Math.abs(err) < 1e-3) return g;
    shift += err;
  }
  return patchAt(p, glasses, eye, shift);
}

function patchAt(p, glasses, eye, shift) {
  const P = p.patch;
  const lf = glasses.lenses.R;
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1);
  // vertex on the HUD line, `gap` behind the lens back surface
  const plane = lf.backCenter.clone().addScaledVector(lf.normal, -P.gap - shift);
  const t = plane.clone().sub(eye.pupilCenter).dot(lf.normal) / A.dot(lf.normal);
  const M = eye.pupilCenter.clone().addScaledVector(A, t);
  const toEye = eye.pupilCenter.clone().sub(M).normalize();
  // source direction: toEye turned toward the temple by the fold angle, then tilted up/down
  const temporal = new Vector3(-1, 0, 0);
  const e2 = temporal.clone().addScaledVector(toEye, -temporal.dot(toEye)).normalize();
  const fold = (P.foldDeg * Math.PI) / 180, tilt = (P.sourceTiltDeg * Math.PI) / 180;
  let toSource;
  const temple = glasses.temples.find((t) => t.side === 1);
  const foldPoint = P.route === 'inline' ? inlineFoldPoint(p, glasses) : null;
  if (foldPoint) {
    toSource = foldPoint.clone().sub(M).normalize();
  } else if (P.fold?.enabled && temple) {
    // folded optics: the beam reaches the patch square to the temple, so the
    // display and lens behind the fold prism lie along the temple
    const back = temple.dir.clone().normalize();
    const out = temporal.clone().addScaledVector(back, -temporal.dot(back)).normalize();
    const up = new Vector3().crossVectors(back, out).normalize();
    toSource = out.multiplyScalar(Math.cos(tilt)).addScaledVector(up.y >= 0 ? up : up.negate(), Math.sin(tilt)).normalize();
  } else {
    toSource = toEye.clone().multiplyScalar(Math.cos(fold)).addScaledVector(e2, Math.sin(fold));
    const e3 = new Vector3().crossVectors(toEye, e2).normalize();
    toSource = toSource.multiplyScalar(Math.cos(tilt)).addScaledVector(e3, Math.sin(tilt)).normalize();
  }
  const nM = toEye.clone().add(toSource).normalize(); // mirror normal at the vertex (eye side)
  const axis = nM.clone().negate(); // conic sag runs toward -axis: concave side faces the eye
  const a = P.diameter / 2;
  const c = 1 / P.radius;
  const face = conicFace(M, axis, c, P.conicK, a, { role: 'patch' });
  // sample points (rim + vertex) for clearances and rendering
  const ref = Math.abs(axis.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
  const u = new Vector3().crossVectors(ref, axis).normalize(), v = new Vector3().crossVectors(axis, u);
  const at = (r, ang) => M.clone().addScaledVector(u, r * Math.cos(ang)).addScaledVector(v, r * Math.sin(ang)).addScaledVector(axis, -face.sag(r));
  const vertices = { vertex: M.clone() };
  for (let k = 0; k < 16; k++) vertices[`rim${k}`] = at(a, (k / 16) * Math.PI * 2);
  const incidenceDeg = (Math.acos(Math.min(1, toEye.dot(nM))) * 180) / Math.PI;
  // off-axis spherical mirror: tangential / sagittal focal lengths f cos(i), f / cos(i)
  const f = P.radius / 2, ci = Math.cos((incidenceDeg * Math.PI) / 180);
  return {
    kind: 'patch', route: P.route, foldPoint, templeBack: glasses.temples.find((t) => t.side === 1)?.dir.clone().normalize(), face, vertex: M, center: M.clone(), entryCenter: M.clone(), exitCenter: M.clone(), toEye, toSource, normal: nM, axis,
    vertices, at, u, v, a, incidenceDeg, f, astigD: 1000 / (f * ci) - 1000 * ci / f,
    quaternion: new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(u, v, axis)),
    w: v.clone(), Lac: P.diameter, H: P.diameter, faces: {},
    volumeMm3: Math.PI * a * a * P.thickness,
  };
}

export function patchObjects(patch, params) {
  if (patch.mode === 'embedded') return []; // its mirror is a face of the lens solid
  // 'bare': uncoated glass (e.g. a cover slip); reflectance follows Fresnel per ray
  const bare = params.patch.coating === 'bare';
  return [partialMirror('patch', bare ? 'Glass reflector' : 'Mirror patch', patch.face, params.patch.reflectance, undefined, bare ? params.patch.glassN ?? 1.523 : undefined)];
}

/**
 * Optional fold prism at the hinge (stock 45-45-90, TIR on the hypotenuse):
 * the display and lens lie along the temple, and the prism turns the beam
 * toward the patch, so a long focal length still fits a normal frame.
 * Placed `dist` mm from the patch along the source direction.
 */
export function computeFoldPrism(p, patch) {
  const F = p.patch.fold;
  if (!F?.enabled) return null;
  const L = F.size;
  const out = patch.toSource.clone().negate(); // prism exit -> patch
  // the beam runs forward along the temple into the prism
  const fwd = patch.templeBack ? patch.templeBack.clone().negate() : new Vector3(0, 0, 1);
  const u = fwd.addScaledVector(out, -fwd.dot(out)).normalize();
  const v = patch.toSource.clone(); // prism local -v is its output direction
  const w = new Vector3().crossVectors(u, v);
  const exitW = patch.vertex.clone().addScaledVector(patch.toSource, F.dist);
  const center = exitW.clone().addScaledVector(v, L / 2);
  return computePrism({ size: L, height: L, angle: 45, pos: { x: center.x, y: center.y, z: center.z }, rot: eulerDegFromBasis(u, v, w) });
}

// ---------------------------------------------------------------- the lens as the reflector
const AIR_N = 1.000293;
const tangentBasis = (n) => {
  const ref = Math.abs(n.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
  const u = new Vector3().crossVectors(ref, n).normalize();
  return { u, v: new Vector3().crossVectors(n, u) };
};

/**
 * Option 3: the back surface of the right spectacle lens is the reflector
 * (bare glass, or a partial mirror coating on it). Its tilt is the lens's
 * own tilt, so the display has to sit at the mirror image of the eye's
 * line of sight, reflected about the lens normal.
 */
function lensBackReflector(p, glasses, eye) {
  const lf = glasses.lenses.R;
  const nEye = lf.normal.clone().negate(); // back surface faces the eye
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1);
  const plane = lf.backCenter.clone().addScaledVector(lf.normal, -0.02);
  const t = plane.clone().sub(eye.pupilCenter).dot(lf.normal) / A.dot(lf.normal);
  const M = eye.pupilCenter.clone().addScaledVector(A, t);
  const toEye = eye.pupilCenter.clone().sub(M).normalize();
  const toSource = nEye.clone().multiplyScalar(2 * toEye.dot(nEye)).sub(toEye).normalize();
  // in-line route: the fold mirror must sit where this fixed line reaches the temple
  let foldPoint = null, inlineValid = true;
  if (p.patch.route === 'inline') {
    const { S, d, i } = templeAxes(glasses);
    const t = (p.patch.inline.inset - M.clone().sub(S).dot(i)) / toSource.dot(i);
    foldPoint = M.clone().addScaledVector(toSource, t);
    inlineValid = t > 0 && foldPoint.clone().sub(S).dot(d) > 0;
  }
  const outline = glasses.outline.map(([x, y]) => lf.toWorld(x, y, -lf.thickness / 2 - 0.02));
  const face = polygonFace(outline, { role: 'lensback' });
  const vertices = Object.fromEntries(outline.map((q, i) => [`o${i}`, q]));
  const { u, v } = tangentBasis(nEye);
  const incidenceDeg = (Math.acos(Math.min(1, toEye.dot(nEye))) * 180) / Math.PI;
  return {
    kind: 'patch', mode: 'lensback', route: p.patch.route, foldPoint, inlineValid, face, vertex: M, center: M.clone(), entryCenter: M.clone(), exitCenter: M.clone(), toEye, toSource, normal: nEye, axis: lf.normal.clone(),
    vertices, outline, u, v, a: 0, incidenceDeg, f: Infinity, astigD: 0, templeBack: glasses.temples.find((q) => q.side === 1)?.dir.clone().normalize(),
    quaternion: lf.quaternion.clone(), w: v.clone(), Lac: 0, H: 0, faces: {}, volumeMm3: 0,
  };
}

/**
 * Option 2: a flat partial mirror cast inside a thicker right lens. Light
 * from the temple enters through the lens back, reflects off the buried
 * mirror and leaves through the lens back toward the eye; every surface is
 * refracted by the tracer. The mirror (diameter `diameter`) must fit inside
 * the lens thickness.
 */
function embeddedReflector(p, glasses, eye) {
  const P = p.patch, lf = glasses.lenses.R, nL = p.frame.specLensN;
  const back = lf.normal.clone().negate(); // outward normal of the back face
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1);
  // eye -> lens back -> into the glass, to the lens mid-plane
  const tB = lf.backCenter.clone().sub(eye.pupilCenter).dot(lf.normal) / A.dot(lf.normal);
  const B = eye.pupilCenter.clone().addScaledVector(A, tB);
  const Ag = refract(A.clone(), back, AIR_N, nL) ?? A.clone();
  const E = B.clone().addScaledVector(Ag, (lf.thickness / 2) / Ag.dot(lf.normal));
  const toEyeG = Ag.clone().negate(); // in glass, from the mirror toward the eye
  // source direction in air: the eye direction turned toward the temple by the fold angle
  const toEye = eye.pupilCenter.clone().sub(B).normalize();
  const temporal = new Vector3(-1, 0, 0);
  const e2 = temporal.clone().addScaledVector(toEye, -temporal.dot(toEye)).normalize();
  const fold = (P.foldDeg * Math.PI) / 180, tilt = (P.sourceTiltDeg * Math.PI) / 180;
  const e3 = new Vector3().crossVectors(toEye, e2).normalize();
  let toSource = toEye.clone().multiplyScalar(Math.cos(fold)).addScaledVector(e2, Math.sin(fold)).multiplyScalar(Math.cos(tilt)).addScaledVector(e3, Math.sin(tilt)).normalize();
  const foldPoint = P.route === 'inline' ? inlineFoldPoint(p, glasses) : null;
  if (foldPoint) {
    // aim from the fold mirror at the point where the refracted beam enters the lens back
    let entry0 = B.clone();
    for (let k = 0; k < 6; k++) {
      toSource = foldPoint.clone().sub(entry0).normalize();
      const dg = refract(toSource.clone().negate(), back, AIR_N, nL);
      if (!dg || dg.dot(lf.normal) <= 0) break;
      // the entry point is where the in-glass ray from the mirror centre meets the back face
      const sE = (lf.thickness / 2) / dg.dot(lf.normal);
      entry0 = E.clone().addScaledVector(dg, -sE);
    }
  }
  // light from the source enters the back face (must travel forward into the lens)
  const dInAir = toSource.clone().negate();
  const valid = dInAir.dot(lf.normal) > 0.05;
  const dInG = valid ? refract(dInAir.clone(), back, AIR_N, nL) : null;
  const nf = dInG ? dInG.clone().sub(toEyeG).normalize() : lf.normal.clone();
  const { u, v } = tangentBasis(nf);
  const a = P.diameter / 2;
  // flat, or a spherical cap concave toward the light (power 2n/R inside the
  // glass): focusing next to the eye gives a bigger image for the same mirror
  const curved = P.radius && P.radius < 1e5;
  const sag = (r) => (curved ? P.radius - Math.sqrt(Math.max(0, P.radius * P.radius - r * r)) : 0);
  const ring = [];
  for (let k = 0; k < 24; k++) { const ang = (k / 24) * Math.PI * 2; ring.push(E.clone().addScaledVector(u, a * Math.cos(ang)).addScaledVector(v, a * Math.sin(ang)).addScaledVector(nf, -sag(a))); }
  // nf points along the incoming light, away from the reflecting side: a
  // concave (focusing) mirror has its centre of curvature at E - nf R and its
  // rim bent toward -nf. conicFace sags toward -axis, so axis = nf.
  const face = curved ? conicFace(E.clone(), nf.clone(), 1 / P.radius, 0, a, { role: 'facet' }) : polygonFace(ring, { role: 'facet' });
  face.facetR = P.reflectance; face.facetT = 1 - P.reflectance;
  // the entry point on the back face, where the beam from the display arrives
  const sEntry = dInG ? -(lf.thickness / 2) / dInG.dot(lf.normal) : 0;
  const entry = dInG ? E.clone().addScaledVector(dInG, sEntry) : B.clone();
  // how far the mirror's rim comes to either lens surface
  const depths = ring.map((q) => q.clone().sub(lf.center).dot(lf.normal));
  const margin = lf.thickness / 2 - Math.max(...depths.map(Math.abs));
  const vertices = Object.fromEntries(ring.map((q, i) => [`r${i}`, q]));
  const incidenceDeg = dInG ? (Math.acos(Math.min(1, Math.abs(dInG.dot(nf)))) * 180) / Math.PI : 90;
  return {
    kind: 'patch', mode: 'embedded', route: P.route, foldPoint, face: null, embeddedFace: valid ? face : null, valid, fitMargin: margin, vertex: entry, center: E.clone(), entryCenter: entry, exitCenter: B, toEye, toSource, normal: nf, axis: nf.clone().negate(),
    vertices, u, v, a, incidenceDeg, f: Infinity, astigD: 0, templeBack: glasses.temples.find((q) => q.side === 1)?.dir.clone().normalize(),
    at: (r, ang) => E.clone().addScaledVector(u, r * Math.cos(ang)).addScaledVector(v, r * Math.sin(ang)).addScaledVector(nf, -sag(r)),
    mirrorPowerD: curved ? (2000 * nL) / P.radius : 0,
    quaternion: new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(u, v, nf)), w: v.clone(), Lac: 0, H: 0, faces: {}, volumeMm3: 0,
  };
}

/** Fold mirror of the in-line route (back-silvered craft mirror tile). */
export function computeFoldMirror(p, patch, glasses) {
  if (p.patch.route !== 'inline' || !patch.foldPoint) return null;
  const { d } = templeAxes(glasses);
  const dIn = d.clone().negate(); // the beam runs forward along the temple
  const dOut = patch.toSource.clone().negate(); // mirror -> reflector
  const normal = dIn.clone().sub(dOut).normalize();
  const radius = p.patch.inline.mirrorD / 2;
  return { center: patch.foldPoint.clone(), normal, radius, dIn, dOut, face: discFace(patch.foldPoint.clone(), normal, radius), deviationDeg: (Math.acos(Math.max(-1, Math.min(1, dIn.dot(dOut)))) * 180) / Math.PI };
}

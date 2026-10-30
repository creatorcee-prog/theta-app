// Curved partial-mirror combiner ("patch"): a thin shell behind the right
// spectacle lens, partially mirrored on its concave (eye-side) face. Light from
// a display in the temple reflects off it into the pupil, as in Focals-style
// glasses. The shell's power (2/R) and the collimator together set focus;
// hitting a curved mirror off-axis adds astigmatism, which the tracer measures.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { conicFace, partialMirror } from './RayTracer.js';
import { computePrism, eulerDegFromBasis } from './OpticalComponents.js';
import { anglesToDirection } from '../model/eye.js';

// The patch is tilted, so its rim reaches further toward the lens than its
// vertex: slide it along the HUD line until every rim point keeps `gap`.
export function computePatch(p, glasses, eye) {
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
  if (P.fold?.enabled && temple) {
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
    kind: 'patch', templeBack: glasses.temples.find((t) => t.side === 1)?.dir.clone().normalize(), face, vertex: M, center: M.clone(), entryCenter: M.clone(), exitCenter: M.clone(), toEye, toSource, normal: nM, axis,
    vertices, at, u, v, a, incidenceDeg, f, astigD: 1000 / (f * ci) - 1000 * ci / f,
    quaternion: new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(u, v, axis)),
    w: v.clone(), Lac: P.diameter, H: P.diameter, faces: {},
    volumeMm3: Math.PI * a * a * P.thickness,
  };
}

export function patchObjects(patch, params) {
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

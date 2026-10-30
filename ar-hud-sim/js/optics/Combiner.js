// Curved partial-mirror combiner ("patch"): a thin shell behind the right
// spectacle lens, partially mirrored on its concave (eye-side) face. Light from
// a display in the temple reflects off it into the pupil, as in Focals-style
// glasses. The shell's power (2/R) and the collimator together set focus;
// hitting a curved mirror off-axis adds astigmatism, which the tracer measures.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { conicFace, partialMirror } from './RayTracer.js';
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
  let toSource = toEye.clone().multiplyScalar(Math.cos(fold)).addScaledVector(e2, Math.sin(fold));
  const e3 = new Vector3().crossVectors(toEye, e2).normalize();
  toSource = toSource.multiplyScalar(Math.cos(tilt)).addScaledVector(e3, Math.sin(tilt)).normalize();
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
    kind: 'patch', face, vertex: M, center: M.clone(), entryCenter: M.clone(), exitCenter: M.clone(), toEye, toSource, normal: nM, axis,
    vertices, at, u, v, a, incidenceDeg, f, astigD: 1000 / (f * ci) - 1000 * ci / f,
    quaternion: new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(u, v, axis)),
    w: v.clone(), Lac: P.diameter, H: P.diameter, faces: {},
    volumeMm3: Math.PI * a * a * P.thickness,
  };
}

export function patchObjects(patch, params) {
  return [partialMirror('patch', 'Mirror patch', patch.face, params.patch.reflectance)];
}

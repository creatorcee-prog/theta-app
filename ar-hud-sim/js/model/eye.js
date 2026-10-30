// Right/left eye geometry (pure data). Millimetres, world frame of
// glassesGeometry.js. Constants are textbook schematic-eye values and are
// exposed as assumptions in the UI and README.

import { Vector3, Euler, Quaternion } from 'three';

export const EYE_CONSTANTS = {
  vertexToRotationCenter: 13.5, // corneal vertex to centre of rotation
  entrancePupilDepth: 3.05,     // entrance pupil behind corneal vertex
  eyeballRadius: 12.0,
  corneaRadius: 7.8,            // anterior corneal radius of curvature
};

/**
 * eye params: { side: +1 right / -1 left, ipd, dx, dy, eyeRelief,
 *               pupilDiameter, gazeYaw, gazePitch }
 * Eye relief is measured from the lens back surface to the corneal vertex
 * with the eye looking straight ahead (the spectacle vertex distance).
 */
export function computeEye(p, glasses) {
  const C = { ...EYE_CONSTANTS, ...(p.constants ?? {}) };
  const side = p.side ?? 1;
  const vertexZ = glasses.lensBackZ - p.eyeRelief;
  const rotationCenter = new Vector3(-side * (p.ipd / 2) + (p.dx ?? 0), p.dy ?? 0, vertexZ - C.vertexToRotationCenter);
  // Gaze: yaw positive = temporal (wearer's right for the right eye, -x),
  // pitch positive = up.
  const q = new Quaternion().setFromEuler(new Euler((-(p.gazePitch ?? 0) * Math.PI) / 180, (-side * (p.gazeYaw ?? 0) * Math.PI) / 180, 0, 'YXZ'));
  const gaze = new Vector3(0, 0, 1).applyQuaternion(q).normalize();
  const up = new Vector3(0, 1, 0).applyQuaternion(q).normalize();
  const right = new Vector3().crossVectors(gaze, up).normalize(); // wearer's right: -x when gaze=+z
  const corneaVertex = rotationCenter.clone().addScaledVector(gaze, C.vertexToRotationCenter);
  const pupilCenter = corneaVertex.clone().addScaledVector(gaze, -C.entrancePupilDepth);
  const corneaCenter = corneaVertex.clone().addScaledVector(gaze, -C.corneaRadius);
  return {
    side, rotationCenter, gaze, up, right, quaternion: q, corneaVertex, pupilCenter, corneaCenter,
    pupilRadius: p.pupilDiameter / 2, eyeballRadius: C.eyeballRadius, corneaRadius: C.corneaRadius,
  };
}

// Head-fixed angular coordinates of a direction seen from the eye, relative
// to the straight-ahead axis (+z). Returns degrees: h positive = temporal
// (outer) side of that eye, v positive = up.
export function directionToAngles(dir, side = 1) {
  const h = (Math.atan2(-dir.x * side, dir.z) * 180) / Math.PI;
  const v = (Math.atan2(dir.y, Math.hypot(dir.x, dir.z)) * 180) / Math.PI;
  return { h, v };
}

export function anglesToDirection(hDeg, vDeg, side = 1) {
  const h = (hDeg * Math.PI) / 180, v = (vDeg * Math.PI) / 180;
  return new Vector3(-side * Math.sin(h) * Math.cos(v), Math.sin(v), Math.cos(h) * Math.cos(v));
}

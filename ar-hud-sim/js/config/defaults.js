// Default configuration and the alignment helper that derives the default
// component placement from a stated design intent.
//
// Every value carries a provenance tag used in the UI:
//   spec    - given in the project brief
//   assumed - not known for the real hardware; adjustable assumption
//   derived - computed from other values (e.g. the alignment helper)
// There are no measured values: no physical glasses were measured.

import { Vector3 } from 'three';
import { computeGlasses } from '../model/glassesGeometry.js';
import { computeEye, anglesToDirection } from '../model/eye.js';
import { eulerDegFromBasis } from '../optics/OpticalComponents.js';

export const PROVENANCE = {
  'oled.diagonalIn': 'spec', 'oled.resX': 'spec', 'oled.resY': 'spec',
  'prism.size': 'spec', 'prism.angle': 'spec', 'prism.n': 'spec',
  'targets.hfov': 'spec', 'targets.vfov': 'spec', 'oled.brightness': 'spec',
  'collimator.focalLength': 'spec', 'targets.azimuth': 'spec', 'targets.coverageMin': 'spec', 'targets.coverageMax': 'spec',
};

export function baseParams() {
  return {
    frame: {
      lensWidth: 50, lensHeight: 38, lensCorner: 12, lensThickness: 2, bridge: 18, endpiece: 7,
      rimDepth: 4, rimWidth: 3, templeLength: 145, templeThickness: 4.5, templeHeight: 6, templeSplayDeg: 2,
      housingLength: 40, housingDepth: 13, housingHeight: 16, housingWall: 1, hingeY: 6, housingOffsetY: -3,
      lensesPresent: true, specLensN: 1.498,
    },
    eye: { ipd: 63, dx: 0, dy: 0, eyeRelief: 14, pupilDiameter: 4, gazeYaw: 0, gazePitch: 0 },
    oled: {
      diagonalIn: 0.23, resX: 640, resY: 400, brightness: 75, peakLuminance: 1000,
      emissionHalfAngle: 20, housingMarginX: 3, housingMarginY: 3, housingDepth: 2.5,
      pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 },
    },
    collimator: {
      enabled: true, mode: 'thin', focalLength: 12, aperture: 8, conicK: -0.8, edgeThickness: 0.8,
      distance: 12, offsetX: 0, offsetY: 0, tiltX: 0, tiltY: 0, flip: false,
    },
    prism: { size: 10, angle: 45, n: 1.517, coating: 'none', pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } },
    driver: { length: 22, height: 10, thickness: 1.6, pos: { x: 0, y: 0, z: 0 } },
    sim: { pixelsX: 9, pixelsY: 5, raysPerPixel: 40, wavelengths: 'mono', ghosts: false, ghostMin: 0.005, drawRays: 900 },
    targets: { hfov: 35, vfov: 20, azimuth: 25, elevation: 10, coverageMin: 40, coverageMax: 50, centralClear: 10 },
    // design intent used only by the alignment helper
    intent: { azimuth: 25, elevation: 10, prismClearance: 1.0, oledInset: 0.5 },
  };
}

/**
 * Alignment helper. Places the prism on the line from the right entrance
 * pupil toward the intended HUD direction, as far forward as the lens back
 * surface allows, orients it so a ray entering its entry face at normal
 * incidence leaves the exit face heading at the pupil centre, and puts the
 * OLED + collimator on the input axis inside the temple housing.
 *
 * This only sets INPUT positions/orientations. The tracer then computes
 * what actually happens; nothing here guarantees the light reaches the eye.
 */
export function alignChain(params) {
  const p = structuredClone(params);
  const glasses = computeGlasses(p.frame);
  const eye = computeEye({ ...p.eye, side: 1, gazeYaw: 0, gazePitch: 0 }, glasses);
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1); // apparent HUD direction
  // prism basis: v = A (output travels -v toward the eye),
  // u = input travel direction, as close to world +x (from the right temple
  // inward toward the nose) as possible
  const v = A.clone();
  const u = new Vector3(1, 0, 0).addScaledVector(v, -v.x).normalize();
  const w = new Vector3().crossVectors(u, v).normalize();
  const L = p.prism.size;
  const Lab = L * Math.tan((p.prism.angle * Math.PI) / 180);
  // Largest forward distance D with every prism vertex behind the lens back
  // surface minus clearance.
  const zLimit = glasses.lensBackZ - p.intent.prismClearance;
  const corners = [];
  for (const [cu, cv] of [[-Lab / 2, -L / 2], [Lab / 2, -L / 2], [-Lab / 2, L / 2]]) {
    for (const cw of [-L / 2, L / 2]) corners.push(u.clone().multiplyScalar(cu).addScaledVector(v, cv).addScaledVector(w, cw));
  }
  const maxCornerZ = Math.max(...corners.map((c) => c.z));
  // Output axis passes through local (0, *, 0): line pupil + A*D through prism center
  const D = (zLimit - maxCornerZ - eye.pupilCenter.z) / A.z;
  const prismCenter = eye.pupilCenter.clone().addScaledVector(A, D);
  p.prism.pos = round3(prismCenter);
  p.prism.rot = eulerDegFromBasis(u, v, w);

  // OLED on the input axis (line through prism centre along u), emitting +u.
  const entryDist = Lab / 2;
  const lensToOled = p.collimator.mode === 'thin' || !p.collimator.enabled ? p.collimator.focalLength : null;
  p.collimator.distance = lensToOled ?? p.collimator.distance;
  // Choose the OLED position so it sits inside the housing cavity, as close
  // to its inner (face-side, +x) wall as allowed: solve x(s) = target along -u.
  const targetX = glasses.cavity.max.x - p.frame.housingWall - p.intent.oledInset - 1.5;
  const s = Math.max(entryDist + 1 + p.collimator.distance, (prismCenter.x - targetX) / u.x);
  const oledCenter = prismCenter.clone().addScaledVector(u, -s);
  p.oled.pos = round3(oledCenter);
  // Display width along the fold plane (maps to the horizontal field), display
  // "up" as close to world up as the fold allows (w points down here, so use -w).
  p.oled.rot = eulerDegFromBasis(v.clone().negate(), w.clone().negate(), u);
  p.collimator.offsetX = 0; p.collimator.offsetY = 0; p.collimator.tiltX = 0; p.collimator.tiltY = 0;
  // driver board flat against the temple's outer wall at the rear of the cavity
  const cav = glasses.cavity;
  p.driver.pos = round3(new Vector3(cav.min.x + p.driver.thickness / 2 + 0.3, cav.center.y, cav.min.z + p.driver.length / 2 + 0.5));
  p._alignInfo = { distanceAlongHudDir: D, oledToPrismCenter: s };
  return p;
}

function round3(v) {
  const r = (x) => Math.round(x * 1000) / 1000;
  return { x: r(v.x), y: r(v.y), z: r(v.z) };
}

export function defaultParams() {
  return alignChain(baseParams());
}

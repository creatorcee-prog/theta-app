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
import { eulerDegFromBasis, computePrism, computeCollimator, computeOled } from '../optics/OpticalComponents.js';
import { computeWaveguide } from '../optics/Waveguide.js';
import { defaultParts, defaultBom } from '../model/parts.js';
import { trace, dielectricSolid } from '../optics/RayTracer.js';
import { makeGlass } from '../optics/materials.js';

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
      housingLength: 40, housingDepth: 13, housingHeight: 16, housingWall: 1, hingeY: 6, housingOffsetY: -3, housingOffsetZ: 0, housingOutward: 0, housingAuto: false,
      lensesPresent: true, specLensN: 1.498,
      sizeCode: '50□18-145', lensShape: 'roundrect', lensExponent: 4, customOutline: '',
      pantoTiltDeg: 0, wrapDeg: 0,
    },
    eye: {
      // your measurements (defaults are typical adult values)
      monoPDRight: 31.5, monoPDLeft: 31.5, pupilHeight: 19, pupilHeightLeft: 19,
      eyeRelief: 14, pupilDiameter: 4, gazeYaw: 0, gazePitch: 0, lashLength: 6,
      // vision (right-eye spectacle prescription unless noted)
      rx: { sphere: 0, cyl: 0, axis: 0, add: 0 }, age: 35, ampMode: 'age', amplitude: 8,
      dominant: 'unknown', condition: 'none',
      constants: { vertexToRotationCenter: 13.5, entrancePupilDepth: 3.05, eyeballRadius: 12, corneaRadius: 7.8 },
    },
    oled: {
      diagonalIn: 0.23, resX: 640, resY: 400, brightness: 75, peakLuminance: 1000,
      emissionHalfAngle: 20, housingMarginX: 3, housingMarginY: 3, housingDepth: 2.5,
      pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 },
    },
    collimator: {
      enabled: true, mode: 'thin', focalLength: 12, aperture: 8, conicK: -0.8, edgeThickness: 0.8,
      distance: 12, offsetX: 0, offsetY: 0, tiltX: 0, tiltY: 0, flip: false,
    },
    prism: { size: 10, height: 10, angle: 45, n: 1.517, coating: 'none', pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } },
    driver: { length: 22, height: 10, thickness: 1.6, ribbonWidth: 3.2, pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } },
    // What the OLED shows (visual only; the optics trace pixel positions)
    hud: {
      mode: 'text', line1: '12:45', line2: 'NEXT 200 m', line3: '64 BPM', textSize: 120,
      color: '#39ff88', background: '#000000', border: true, arrow: true,
      image: null, imageName: '', imageFit: 'contain', driverFlip: false,
    },
    sim: { pixelsX: 9, pixelsY: 5, raysPerPixel: 40, wavelengths: 'mono', ghosts: false, ghostMin: 0.005, drawRays: 900, raySpeed: 22 },
    // zone: where the HUD may appear (degrees from the line of sight, temporal + / up +);
    // default traced from the wearer's sketch: the temporal half of the right lens
    targets: { hfov: 35, vfov: 20, azimuth: 25, elevation: 10, coverageMin: 40, coverageMax: 50, centralClear: 10, zone: { hMin: 0, hMax: 48, vMin: -33, vMax: 38 } },
    // head clearance beside the right temple (your measurements)
    head: { gap20: 10, gap40: 7, hertelDepth: 15.5, hertelBase: 114, canthusToTemple: 0, canthusOffset: 14 },
    parts: defaultParts(),
    bom: defaultBom(),
    // design intent used only by the alignment helper
    intent: { azimuth: 25, elevation: 10, prismClearance: 1.0, oledInset: 0.5, entryTiltDeg: 0 },
    // geometric (reflective) waveguide that replaces the prism when enabled
    waveguide: { enabled: false, thickness: 2.5, height: 9, gapToLens: 0.4, guideAngle: 55, facets: 3, facetSpacing: 3.5, facetR: 0.25, coating: 'selective', templeMargin: 2, mount: 'rim' },
  };
}

/**
 * Alignment helper. Traces the axial ray through the prism as currently
 * shaped (any prism angle, index and size), then rotates and places the
 * prism so that ray leaves heading at the right entrance pupil from the
 * target direction, as far forward as the lens back surface allows. The
 * OLED + collimator go on the input axis inside the temple housing.
 *
 * This only sets INPUT positions/orientations. The full trace then computes
 * what actually happens; nothing here guarantees the light reaches the eye.
 */
export function alignChain(params) {
  if (params.waveguide?.enabled) return alignGuideChain(params);
  const p = structuredClone(params);
  const glasses = computeGlasses(p.frame);
  const eye = computeEye({ ...p.eye, monoPD: p.eye.monoPDRight, side: 1, gazeYaw: 0, gazePitch: 0 }, glasses);
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1); // apparent HUD direction
  const outWorld = A.clone().negate(); // light travels from the prism to the eye

  // 1. Trace the axial ray through the prism in its own frame.
  const local = computePrism({ ...p.prism, pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } });
  const glass = makeGlass('BK7', p.prism.n, { dispersive: false });
  // Align on the reflected path even where TIR fails (the full trace then
  // reports the leak); geometry of the reflection is the same either way.
  local.faces.hypotenuse.mirrorR = 1;
  // entryTiltDeg tilts the input ray inside the fold plane so it meets the
  // entry face off-normal; positive values raise the hypotenuse incidence
  // (more TIR margin on a stock 45° prism).
  const tilt = ((p.intent.entryTiltDeg ?? 0) * Math.PI) / 180;
  const dIn = new Vector3(Math.cos(tilt), -Math.sin(tilt), 0);
  const entry = local.entryCenter.clone();
  const [path] = trace({ objects: [dielectricSolid('prism', 'prism', glass, Object.values(local.faces))] },
    [{ origin: entry.clone().addScaledVector(dIn, -5), dir: dIn, weight: 1 }]);
  let dOut = new Vector3(0, -1, 0), exitPt = local.exitCenter.clone(), traced = false;
  const lastSeg = path.segments[path.segments.length - 1];
  if (path.outcome === 'escaped' && lastSeg && lastSeg.type !== 'glass' && path.segments.length >= 3) {
    dOut = path.finalRay.dir.clone(); exitPt = path.finalRay.origin.clone(); traced = true;
  }

  // 2. Rotation mapping local (dOut, dIn) onto world (outWorld, input from the temple).
  const cos = dIn.dot(dOut);
  const sin = Math.sqrt(Math.max(1e-12, 1 - cos * cos));
  const l1 = dOut.clone(), l2 = dIn.clone().addScaledVector(dOut, -cos).normalize(), l3 = new Vector3().crossVectors(l1, l2);
  const f1 = outWorld.clone();
  const f2 = new Vector3(1, 0, 0).addScaledVector(f1, -f1.x).normalize(); // input travels inward (+x) from the right temple
  const f3 = new Vector3().crossVectors(f1, f2);
  const toWorld = (v) => f1.clone().multiplyScalar(v.dot(l1)).addScaledVector(f2, v.dot(l2)).addScaledVector(f3, v.dot(l3));
  const u = toWorld(new Vector3(1, 0, 0)), v = toWorld(new Vector3(0, 1, 0)), w = toWorld(new Vector3(0, 0, 1));
  const inWorld = f1.clone().multiplyScalar(cos).addScaledVector(f2, sin);

  // 3. Place it: exit point on the line pupil + A t, every vertex behind the lens.
  // Largest t with every vertex at least `prismClearance` behind the right
  // lens's back plane (which includes pantoscopic tilt and wrap):
  //   -(C + R c_i - B) . n >= clearance,  C = P + A t - R e
  const lf = glasses.lenses.R;
  const e = toWorld(exitPt);
  const nA = A.dot(lf.normal);
  const t = Math.min(...Object.values(local.vertices).map((c) => {
    const k = eye.pupilCenter.clone().sub(e).add(toWorld(c)).sub(lf.backCenter).dot(lf.normal);
    return (-p.intent.prismClearance - k) / nA;
  }));
  const prismCenter = eye.pupilCenter.clone().addScaledVector(A, t).sub(e);
  p.prism.pos = round3(prismCenter);
  p.prism.rot = eulerDegFromBasis(u, v, w);

  // 4. OLED on the input axis, emitting along it, width in the fold plane,
  //    display "up" on the side of world up.
  const entryWorld = prismCenter.clone().add(toWorld(entry));
  const lensToOled = p.collimator.mode === 'thin' || !p.collimator.enabled ? p.collimator.focalLength : null;
  p.collimator.distance = lensToOled ?? p.collimator.distance;
  // fixed housing: OLED near the cavity's inner wall; auto-sized housing:
  // OLED `oledInset` mm inward of the temple's outer face (negative = outward)
  const outerX = -(glasses.hingeX + p.frame.templeThickness / 2);
  const targetX = p.frame.housingAuto ? outerX + p.intent.oledInset : glasses.cavity.max.x - p.frame.housingWall - p.intent.oledInset - 1.5;
  // distance from the entry face, kept between "just fits the lens" and 60 mm
  const s = Math.min(60, Math.max(1 + p.collimator.distance, (entryWorld.x - targetX) / Math.max(0.05, inWorld.x)));
  const oledCenter = entryWorld.clone().addScaledVector(inWorld, -s);
  const z = inWorld.clone();
  let y = f3.clone(); // normal of the fold plane
  if (y.y < 0) y.negate();
  const x = new Vector3().crossVectors(y, z);
  p.oled.pos = round3(oledCenter);
  p.oled.rot = eulerDegFromBasis(x, y, z);
  p.collimator.offsetX = 0; p.collimator.offsetY = 0; p.collimator.tiltX = 0; p.collimator.tiltY = 0;

  // driver board flat against the temple's outer wall at the rear of the cavity
  const cav = glasses.cavity;
  if (p.frame.housingAuto) {
    // board flat against the temple, just behind the OLED module
    const oz = oledCenter.z - 6;
    p.driver.pos = round3(new Vector3(outerX + p.driver.thickness / 2 + 0.3, oledCenter.y, Math.min(oz, glasses.hingeZ - 1) - p.driver.length / 2));
    p.driver.rot = { yaw: 0, pitch: 0, roll: 0 };
  } else {
    p.driver.pos = round3(new Vector3(cav.min.x + p.driver.thickness / 2 + 0.3, cav.center.y, cav.min.z + p.driver.length / 2 + 0.5));
  }
  p._alignInfo = { traced, deviationDeg: (Math.acos(Math.min(1, Math.max(-1, cos))) * 180) / Math.PI, distanceAlongHudDir: t, entryToOled: s };
  return p;
}

/** Waveguide version: the plate's position follows the lens (it sits just
 *  behind it) and the HUD direction (facets in line with it); the OLED and
 *  collimator go on the plate's input axis behind its temple end. */
export function alignGuideChain(params) {
  const p = structuredClone(params);
  const glasses = computeGlasses(p.frame);
  const eye = computeEye({ ...p.eye, monoPD: p.eye.monoPDRight, side: 1, gazeYaw: 0, gazePitch: 0 }, glasses);
  const wg = computeWaveguide(p, glasses, eye);
  const lensToOled = p.collimator.mode === 'thin' || !p.collimator.enabled ? p.collimator.focalLength : null;
  p.collimator.distance = lensToOled ?? p.collimator.distance;
  const c = computeCollimator({ ...p.collimator, enabled: true }, computeOled(p.oled), p.prism.n);
  const s = (c?.valid ? c.frontFocalDistance + (c.thickness || 0) : p.collimator.distance) + (p.intent.guideStandoff ?? 2);
  const oledCenter = wg.entryPoint.clone().addScaledVector(wg.I, -s);
  const z = wg.I.clone();
  const y = wg.v.clone().addScaledVector(z, -wg.v.dot(z)).normalize();
  const x = new Vector3().crossVectors(y, z);
  // roll 180° when asked (image orientation is a display-driver setting too)
  const flip = p.intent.guideRoll ? -1 : 1;
  p.oled.pos = round3(oledCenter);
  p.oled.rot = eulerDegFromBasis(x.multiplyScalar(flip), y.multiplyScalar(flip), z);
  p.collimator.offsetX = 0; p.collimator.offsetY = 0; p.collimator.tiltX = 0; p.collimator.tiltY = 0;
  // driver board flat against the temple's outer wall, behind the OLED module
  const outerX = -(glasses.hingeX + p.frame.templeThickness / 2);
  p.driver.pos = round3(new Vector3(outerX + p.driver.thickness / 2 + 0.3, oledCenter.y, Math.min(oledCenter.z - 6, glasses.hingeZ - 1) - p.driver.length / 2));
  p.driver.rot = { yaw: 0, pitch: 0, roll: 0 };
  p._alignInfo = { traced: true, guideAngle: p.waveguide.guideAngle, entryToOled: s };
  return p;
}

function round3(v) {
  const r = (x) => Math.round(x * 1000) / 1000;
  return { x: r(v.x), y: r(v.y), z: r(v.z) };
}

export function defaultParams() {
  return alignChain(baseParams());
}

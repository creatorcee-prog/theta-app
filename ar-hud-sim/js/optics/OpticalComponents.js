// Geometry of the optical components (Micro-OLED, BK7 prism, collimator,
// spectacle lens) and their conversion into ray-tracer objects.
// Pure data + math; the renderer reads the same geometry so what you see is
// exactly what is traced.

import { Vector3, Quaternion, Euler, Matrix4 } from 'three';
import {
  polygonFace, discFace, conicFace, cylinderFace, dielectricSolid, thinLens,
  boxAbsorber, orthonormalBasis,
} from './RayTracer.js';

export const MM_PER_INCH = 25.4;

export function quatFromEulerDeg(rot) {
  return new Quaternion().setFromEuler(new Euler(
    (rot.pitch * Math.PI) / 180, (rot.yaw * Math.PI) / 180, (rot.roll * Math.PI) / 180, 'YXZ'));
}

export function eulerDegFromBasis(x, y, z) {
  const m = new Matrix4().makeBasis(x, y, z);
  const e = new Euler().setFromRotationMatrix(m, 'YXZ');
  const r = (a) => Math.round(((a * 180) / Math.PI) * 1000) / 1000;
  return { pitch: r(e.x), yaw: r(e.y), roll: r(e.z) };
}

function axes(q) {
  return {
    x: new Vector3(1, 0, 0).applyQuaternion(q),
    y: new Vector3(0, 1, 0).applyQuaternion(q),
    z: new Vector3(0, 0, 1).applyQuaternion(q),
  };
}

// ------------------------------------------------------------ Micro-OLED
// Local frame: +z = emission normal, +x = display width (640 px),
// +y = display height (400 px).
export function computeOled(p) {
  const diag = p.diagonalIn * MM_PER_INCH;
  const hyp = Math.hypot(p.resX, p.resY); // square pixels assumed
  const width = (diag * p.resX) / hyp;
  const height = (diag * p.resY) / hyp;
  const q = quatFromEulerDeg(p.rot);
  const a = axes(q);
  const center = new Vector3(p.pos.x, p.pos.y, p.pos.z);
  const housing = {
    size: new Vector3(width + p.housingMarginX, height + p.housingMarginY, p.housingDepth),
  };
  housing.center = center.clone().addScaledVector(a.z, -p.housingDepth / 2 - 0.02);
  housing.matrix = new Matrix4().compose(housing.center, q, new Vector3(1, 1, 1));
  return {
    diagonalMm: diag, width, height, pixelPitch: width / p.resX,
    resX: p.resX, resY: p.resY, center, quaternion: q, normal: a.z, xAxis: a.x, yAxis: a.y, housing,
    // u,v in [-1,1] across the active area (pixel-centre to pixel-centre)
    pointAt(u, v) {
      const hx = (width / 2) * (1 - 1 / p.resX), hy = (height / 2) * (1 - 1 / p.resY);
      return center.clone().addScaledVector(a.x, u * hx).addScaledVector(a.y, v * hy);
    },
  };
}

// ------------------------------------------------------------ Driver board
export function computeDriver(p) {
  const center = new Vector3(p.pos.x, p.pos.y, p.pos.z);
  const q = quatFromEulerDeg(p.rot ?? { yaw: 0, pitch: 0, roll: 0 });
  const size = new Vector3(p.thickness + 3.5, p.height, p.length); // PCB + parts + connector
  const pcbSize = new Vector3(p.thickness, p.height, p.length);
  // parts sit on the board's local +x side (the face side by default)
  const envCenter = new Vector3(1.75, 0, 0).applyQuaternion(q).add(center);
  return { center, quaternion: q, size: pcbSize, envelope: size, envCenter, matrix: new Matrix4().compose(envCenter, q, new Vector3(1, 1, 1)) };
}

// ------------------------------------------------------------ Prism
// Right-angle prism. Local frame: +x (u) = intended input travel direction,
// -y (v) = intended output direction, +z (w) = extrusion. Faces:
//   entry  : x = -Lab/2 (leg, size L x L)
//   exit   : y = -L/2   (leg, size Lab x L)
//   hypotenuse: BC; its incidence for a ray entering the entry face at
//   normal incidence equals the prism angle.
// prismAngle (deg) is the angle at vertex C between entry face and
// hypotenuse. 45 deg gives the standard 45-45-90 prism.
export function computePrism(p) {
  const L = p.size;
  const Lac = L;
  const Lab = L * Math.tan((p.angle * Math.PI) / 180);
  const H = p.height ?? L;
  const q = quatFromEulerDeg(p.rot);
  const a = axes(q);
  const center = new Vector3(p.pos.x, p.pos.y, p.pos.z);
  const toWorld = (u, v, w) => center.clone().addScaledVector(a.x, u).addScaledVector(a.y, v).addScaledVector(a.z, w);
  const A2 = [-Lab / 2, -Lac / 2], B2 = [Lab / 2, -Lac / 2], C2 = [-Lab / 2, Lac / 2];
  const V = {};
  for (const [name, [u, v]] of Object.entries({ A: A2, B: B2, C: C2 })) {
    V[name + '+'] = toWorld(u, v, H / 2);
    V[name + '-'] = toWorld(u, v, -H / 2);
  }
  const centroid = toWorld((A2[0] + B2[0] + C2[0]) / 3, (A2[1] + B2[1] + C2[1]) / 3, 0);
  const faceDefs = {
    entry: ['A-', 'C-', 'C+', 'A+'],
    exit: ['A-', 'A+', 'B+', 'B-'],
    hypotenuse: ['B-', 'B+', 'C+', 'C-'],
    capTop: ['A+', 'C+', 'B+'],
    capBottom: ['A-', 'B-', 'C-'],
  };
  const faces = {};
  for (const [role, names] of Object.entries(faceDefs)) {
    let verts = names.map((n) => V[n]);
    let f = polygonFace(verts, { role });
    if (f.normal.dot(f.centroid.clone().sub(centroid)) < 0) f = polygonFace(verts.slice().reverse(), { role });
    faces[role] = f;
  }
  const hypLength = Math.hypot(Lab, Lac);
  return {
    L, Lab, Lac, H, center, quaternion: q, u: a.x, v: a.y, w: a.z, vertices: V, faces, centroid,
    entryCenter: toWorld(-Lab / 2, 0, 0), exitCenter: toWorld(0, -Lac / 2, 0),
    faceAreas: { entry: Lac * H, exit: Lab * H, hypotenuse: hypLength * H },
    volumeMm3: 0.5 * Lab * Lac * H,
  };
}

// ------------------------------------------------------------ Collimator
// Mounted in a barrel on the OLED axis. distance = OLED surface to the
// lens (thin lens plane, or first vertex of a real lens).
export function computeCollimator(p, oled, nGlass) {
  if (!p.enabled) return null;
  const tilt = new Quaternion().setFromEuler(new Euler((p.tiltX * Math.PI) / 180, (p.tiltY * Math.PI) / 180, 0, 'XYZ'));
  const q = oled.quaternion.clone().multiply(tilt);
  const axis = new Vector3(0, 0, 1).applyQuaternion(q);
  const center = oled.center.clone()
    .addScaledVector(oled.normal, p.distance)
    .addScaledVector(oled.xAxis, p.offsetX)
    .addScaledVector(oled.yAxis, p.offsetY);
  const a = p.aperture / 2;
  const base = { mode: p.mode, f: p.focalLength, aperture: p.aperture, apertureRadius: a, axis, center, quaternion: q, flip: p.flip };
  if (p.mode === 'thin') {
    return { ...base, thickness: 0, frontFocalDistance: p.focalLength, firstVertex: center, valid: true };
  }
  // Plano-convex. Paraxial EFL f = R/(n-1) (exact for plano-convex).
  const R = p.focalLength * (nGlass - 1);
  const c = 1 / R;
  const k = p.mode === 'aspheric' ? p.conicK : 0;
  const q2 = 1 - (1 + k) * c * c * a * a;
  const valid = q2 > 0;
  const sagA = valid ? (c * a * a) / (1 + Math.sqrt(q2)) : NaN;
  const thickness = valid ? sagA + p.edgeThickness : NaN;
  const ffd = p.flip ? p.focalLength : p.focalLength - thickness / nGlass;
  return {
    ...base, R, c, k, sagA, thickness, edgeThickness: p.edgeThickness, valid,
    frontFocalDistance: ffd, firstVertex: center,
    invalidReason: valid ? null : `Aperture ${p.aperture} mm is too large for R = ${R.toFixed(2)} mm (conic k = ${k}); the surface does not exist at the rim.`,
  };
}

// ------------------------------------------------------------ to tracer objects

export function buildOpticalObjects({ oled, prism, collimator, driver, glasses, frame, prismMaterial, lensMaterial, specMaterial, coating }) {
  const objects = [];
  if (driver) objects.push(boxAbsorber('driver', 'HDMI driver board', driver.matrix, driver.envelope));

  // OLED housing (absorbing, sits behind the emitting surface)
  objects.push(boxAbsorber('oledHousing', 'OLED housing', oled.housing.matrix, oled.housing.size));

  // Prism
  const prismFaces = Object.values(prism.faces);
  if (coating === 'mirror') {
    // Aluminised hypotenuse: modelled as an absorbing-backed mirror; see
    // RayTracer coatedMirror handling via role.
    prism.faces.hypotenuse.mirrorR = 0.9;
  }
  objects.push(dielectricSolid('prism', 'BK7 prism', prismMaterial, prismFaces));

  // Collimator
  if (collimator && collimator.valid) {
    const ax = collimator.axis;
    const barrelRadius = collimator.apertureRadius + 0.25;
    const barrelLength = Math.max(0.1, collimator.center.clone().sub(oled.center).dot(oled.normal) - 0.05);
    objects.push({
      kind: 'absorber', shape: 'cylinder', id: 'barrel', label: 'Lens barrel',
      face: cylinderFace(oled.center.clone().addScaledVector(oled.normal, 0.05), oled.normal, barrelRadius, barrelLength, { absorb: true }),
    });
    if (collimator.mode === 'thin') {
      objects.push(thinLens('collimator', 'Collimator (ideal thin lens)', collimator.center, ax, collimator.f, collimator.apertureRadius, collimator.apertureRadius + 1.5));
    } else {
      const { thickness: t, sagA, apertureRadius: a, c, k } = collimator;
      const faces = [];
      if (!collimator.flip) {
        faces.push(discFace(collimator.center, ax.clone().negate(), a, { role: 'plano' }));
        faces.push(conicFace(collimator.center.clone().addScaledVector(ax, t), ax, c, k, a, { role: 'convex' }));
        faces.push(cylinderFace(collimator.center, ax, a, t - sagA, { role: 'edge', absorb: true }));
      } else {
        faces.push(conicFace(collimator.center, ax.clone().negate(), c, k, a, { role: 'convex' }));
        faces.push(discFace(collimator.center.clone().addScaledVector(ax, t), ax, a, { role: 'plano' }));
        faces.push(cylinderFace(collimator.center.clone().addScaledVector(ax, sagA), ax, a, t - sagA, { role: 'edge', absorb: true }));
      }
      objects.push(dielectricSolid('collimator', 'Collimator (plano-convex)', lensMaterial, faces, 'lens'));
      // mount ring around the clear aperture
      objects.push({
        kind: 'absorber', shape: 'disc', id: 'collimator-mount', label: 'Lens mount',
        face: discFace(collimator.center.clone().addScaledVector(ax, -0.01), ax, a + 1.5, { innerRadius: a }),
      });
    }
  }

  // Spectacle lenses (plano CR-39, rim edge absorbs)
  if (frame.lensesPresent) {
    for (const side of [1, -1]) {
      const lf = side === 1 ? glasses.lenses.R : glasses.lenses.L;
      const t2 = frame.lensThickness / 2;
      // outline is defined for the right lens seen from the front; mirror it for the left
      const ol = side === 1 ? glasses.outline : glasses.outline.map(([x, y]) => [-x, y]).reverse();
      const front = ol.map(([x, y]) => lf.toWorld(x, y, t2));
      const back = ol.map(([x, y]) => lf.toWorld(x, y, -t2));
      const faces = [polygonFace(front, { role: 'lensFront' }), polygonFace(back.slice().reverse(), { role: 'lensBack' })];
      for (let i = 0; i < front.length; i++) {
        const j = (i + 1) % front.length;
        faces.push(polygonFace([back[i], back[j], front[j], front[i]], { role: 'rim', absorb: true }));
      }
      // fix orientation of front/back if needed
      for (const f of faces.slice(0, 2)) {
        const want = f.role === 'lensFront' ? 1 : -1;
        if (Math.sign(f.normal.dot(lf.normal)) !== want) f.normal.negate();
      }
      objects.push(dielectricSolid(side === 1 ? 'specLensR' : 'specLensL', side === 1 ? 'Right lens' : 'Left lens', specMaterial, faces, null));
    }
  }

  // Temples (absorbing). The right temple's display housing is treated as
  // having an optical window toward the prism; its walls are a containment
  // check, not traced surfaces (see README limitations).
  for (const t of glasses.temples) {
    const behindHousing = t.side === 1;
    const len = behindHousing ? t.size.z - frame.housingLength : t.size.z;
    const start = t.start.clone().addScaledVector(t.dir, behindHousing ? frame.housingLength : 0);
    const center = start.clone().addScaledVector(t.dir, len / 2);
    const m = new Matrix4().compose(center, t.quaternion, new Vector3(1, 1, 1));
    objects.push(boxAbsorber(t.side === 1 ? 'templeR' : 'templeL', t.side === 1 ? 'Right temple' : 'Left temple', m, new Vector3(t.size.x, t.size.y, len)));
  }
  return objects;
}

export { orthonormalBasis };

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

export function roundedRectArea(w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  return w * h - (4 - Math.PI) * rr * rr;
}

export function computeGlasses(frame) {
  const {
    lensWidth, lensHeight, lensCorner, lensThickness, bridge, endpiece,
    rimDepth, templeLength, templeThickness, templeHeight, templeSplayDeg,
    housingLength, housingDepth, housingHeight, housingWall, hingeY = 0, housingOffsetY = 0,
  } = frame;
  const rightLensCenter = new Vector3(-(bridge / 2 + lensWidth / 2), 0, 0);
  const leftLensCenter = new Vector3(-rightLensCenter.x, 0, 0);
  const hingeX = bridge / 2 + lensWidth + endpiece;
  const hingeZ = -rimDepth / 2 - 1;
  const outline = roundedRectOutline(lensWidth, lensHeight, lensCorner);
  const lensArea = roundedRectArea(lensWidth, lensHeight, lensCorner);
  const lensBackZ = -lensThickness / 2;
  const lensFrontZ = lensThickness / 2;

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
  // the face, +x) from the temple's outer surface.
  const outerX = -(hingeX + templeThickness / 2);
  const housing = {
    min: new Vector3(outerX, hingeY + housingOffsetY - housingHeight / 2, hingeZ - housingLength),
    max: new Vector3(outerX + housingDepth, hingeY + housingOffsetY + housingHeight / 2, hingeZ),
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
    rightLensCenter, leftLensCenter, hingeX, hingeZ, outline, lensArea,
    lensBackZ, lensFrontZ, temples, housing, cavity,
    hingeY, hinges: [new Vector3(-hingeX, hingeY, hingeZ), new Vector3(hingeX, hingeY, hingeZ)],
  };
}

export function pointInBox(p, box, margin = 0) {
  return p.x >= box.min.x - margin && p.x <= box.max.x + margin &&
    p.y >= box.min.y - margin && p.y <= box.max.y + margin &&
    p.z >= box.min.z - margin && p.z <= box.max.z + margin;
}

// Right side of the wearer's head, as far as the HUD hardware cares.
//
// - The lateral orbital rim (the bone at the outer edge of the eye socket)
//   sits `hertelDepth` behind the corneal apex and `hertelBase / 2` from the
//   midline. These are the two numbers a Hertel exophthalmometer reads
//   (adult means ~15.5 mm and ~114 mm).
// - In front of the rim plane, beside the eye, there is open air.
// - Behind it and lateral of the rim, the side of the head runs back beside
//   the temple arm at the measured gaps (20 mm and 40 mm behind the hinge).
// - Behind it and medial of the rim is the eye socket: off limits.

export function computeHead(params, glasses, eye) {
  const h = params.head;
  const innerTempleX = -(glasses.hingeX - params.frame.templeThickness / 2);
  const zRim = eye.corneaVertex.z - h.hertelDepth;
  const rimX = -h.hertelBase / 2;
  const z20 = glasses.hingeZ - 20, z40 = glasses.hingeZ - 40;
  const gapAt = (z) => Math.max(0, h.gap20 + (h.gap40 - h.gap20) * ((z20 - z) / (z20 - z40)));
  const skinX = (z) => innerTempleX + gapAt(z);
  // > 0: how far a point (right side, x < 0) is inside the head, in mm
  const intrusion = (p) => {
    if (p.x >= 0 || p.z >= zRim) return -Infinity;
    if (p.x > rimX) return Math.min(zRim - p.z, p.x - rimX); // behind the rim, medial: eye socket / skull
    return p.x - skinX(p.z);
  };
  return { zRim, rimX, innerTempleX, skinX, gapAt, intrusion };
}

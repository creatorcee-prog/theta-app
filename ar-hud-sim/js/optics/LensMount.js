// Standoff pins that bond the combiner (prism or mirror patch) to the back of
// the right spectacle lens, so it is carried by the frame. Each pin runs along
// the lens normal from a point on the combiner (pulled 1 mm inside its edge)
// to the lens back plane, glued at both ends. Traced as absorbers.

import { Vector3 } from 'three';
import { cylinderFace } from './RayTracer.js';

export const PIN_RADIUS = 0.75;

export function computeLensMount(combiner, glasses, eye, centralClearDeg = 10) {
  if (!combiner.kind || combiner.kind === 'patch') {
    const lf = glasses.lenses.R;
    const depth = (q) => -q.clone().sub(lf.backCenter).dot(lf.normal);
    const c = combiner.center;
    let cand = Object.values(combiner.vertices).filter((q) => q.distanceTo(c) > 1.5).map((q) => q.clone().add(c.clone().sub(q).setLength(1)));
    // a mirror patch is lit from the display side: keep its pins on the far half of the rim
    if (combiner.kind === 'patch') cand = cand.filter((q) => q.clone().sub(c).dot(combiner.toSource) < -1);
    // and keep every pin out of the central zone of vision
    const offAxis = (q) => (q.clone().sub(eye.pupilCenter).angleTo(new Vector3(0, 0, 1)) * 180) / Math.PI;
    const clear = cand.filter((q) => offAxis(q) >= centralClearDeg + 2);
    if (clear.length >= 2) cand = clear;
    cand.sort((a, b) => depth(a) - depth(b));
    // nearest point, then the nearest ones at least 5 mm from the pins already chosen
    const pins = [];
    for (const q of cand) {
      if (pins.length === (combiner.kind === 'patch' ? 3 : 2)) break;
      if (pins.every((p) => p.base.distanceTo(q) >= 5)) pins.push({ base: q, length: Math.max(0.05, depth(q)) });
    }
    for (const p of pins) p.axis = lf.normal.clone();
    return { pins, longest: Math.max(...pins.map((p) => p.length)), radius: PIN_RADIUS };
  }
  return null; // the waveguide is held by its rim clip
}

export function lensMountObjects(mount) {
  return (mount?.pins ?? []).map((p, k) => ({ kind: 'absorber', shape: 'cylinder', id: `mount-${k}`, label: 'Lens standoff pin', face: cylinderFace(p.base, p.axis, PIN_RADIUS, p.length, { absorb: true }) }));
}

export function lensMountPoints(mount) {
  const pts = [];
  for (const p of mount?.pins ?? []) for (const t of [0, 0.5, 1]) pts.push(p.base.clone().addScaledVector(p.axis, p.length * t));
  return pts;
}

// Standoff pins that bond the combiner (prism or mirror patch) to the back of
// the right spectacle lens, so it is carried by the frame. Each pin runs along
// the lens normal from a point on the combiner (pulled 1 mm inside its edge)
// to the lens back plane, glued at both ends. Traced as absorbers.

import { Vector3 } from 'three';
import { cylinderFace } from './RayTracer.js';

export const PIN_RADIUS = 0.75;

export function computeLensMount(combiner, glasses, eye, centralClearDeg = 10) {
  // a reflecting lens surface or a mirror cast in the lens needs no mount
  if (combiner.kind === 'patch' && combiner.mode) return null;
  if (!combiner.kind || combiner.kind === 'patch') {
    const lf = glasses.lenses.R;
    const depth = (q) => -q.clone().sub(lf.backCenter).dot(lf.normal);
    const c = combiner.center;
    let cand = Object.values(combiner.vertices).filter((q) => q.distanceTo(c) > 1.5).map((q) => q.clone().add(c.clone().sub(q).setLength(1)));
    // a mirror patch is lit from the display side: keep its pins on the far half of the rim
    // (not the third of the rim that faces the display)
    if (combiner.kind === 'patch') cand = cand.filter((q) => q.clone().sub(c).dot(combiner.toSource) < 0.3 * combiner.a);
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

/** Surface points of each pin separately (a hull around all pins would
 *  wrongly cover the open space between them). */
export function lensMountPointsPerPin(mount) {
  return (mount?.pins ?? []).map((p) => {
    const ref = Math.abs(p.axis.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
    const e1 = new Vector3().crossVectors(p.axis, ref).normalize(), e2 = new Vector3().crossVectors(p.axis, e1);
    const pts = [];
    for (const t of [0, 0.5, 1]) for (let k = 0; k < 8; k++) {
      const a = (k / 8) * Math.PI * 2;
      pts.push(p.base.clone().addScaledVector(p.axis, p.length * t).addScaledVector(e1, PIN_RADIUS * Math.cos(a)).addScaledVector(e2, PIN_RADIUS * Math.sin(a)));
    }
    return pts;
  });
}

// Preferred HUD positions on the right lens (the wearer's request): the
// middle and the four corners, pulled `inset` of the way in from the centre
// toward the corner of the lens outline's bounding box so the whole HUD can
// sit inside the rim. Returned as the eye's viewing angles (temporal + / up +).


import { directionToAngles } from './eye.js';

export const SPOTS = [
  ['middle', 'Middle'], ['topTemporal', 'Top, temple side'], ['topNasal', 'Top, nose side'],
  ['bottomTemporal', 'Bottom, temple side'], ['bottomNasal', 'Bottom, nose side'],
];

// right lens: local +x points toward the nose
const LOCAL = { middle: [0, 0], topTemporal: [-1, 1], topNasal: [1, 1], bottomTemporal: [-1, -1], bottomNasal: [1, -1] };

export function lensSpots(glasses, eye, inset = 0.6) {
  const lf = glasses.lenses.R, ol = glasses.outline;
  const xs = ol.map((q) => q[0]), ys = ol.map((q) => q[1]);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const hw = (Math.max(...xs) - Math.min(...xs)) / 2, hh = (Math.max(...ys) - Math.min(...ys)) / 2;
  return SPOTS.map(([id, label]) => {
    const [sx, sy] = LOCAL[id];
    const pt = lf.toWorld(cx + sx * inset * hw, cy + sy * inset * hh, 0);
    const a = directionToAngles(pt.sub(eye.pupilCenter).normalize(), 1);
    return { id, label, h: Math.round(a.h * 10) / 10, v: Math.round(a.v * 10) / 10 };
  });
}

/** The whole right lens as seen from the pupil (angular bounding box). */
export function lensZone(glasses, eye) {
  const lf = glasses.lenses.R;
  const angs = glasses.outline.map(([x, y]) => directionToAngles(lf.toWorld(x, y, 0).sub(eye.pupilCenter).normalize(), 1));
  const r = (x) => Math.round(x * 10) / 10;
  return { hMin: r(Math.min(...angs.map((a) => a.h))), hMax: r(Math.max(...angs.map((a) => a.h))), vMin: r(Math.min(...angs.map((a) => a.v))), vMax: r(Math.max(...angs.map((a) => a.v))) };
}

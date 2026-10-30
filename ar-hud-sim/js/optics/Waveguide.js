// Geometric (reflective, Lumus-type) waveguide: a thin glass plate bonded
// behind the right spectacle lens. Collimated light from the temple enters
// the plate's slanted temple-end face, travels toward the nose by total
// internal reflection between the plate faces, and partially reflective
// facets embedded in the glass in front of the eye send copies of it out
// through the back face to the pupil (each facet adds a copy: a wider
// eye-box). Facet coatings are angle-selective (assumed): they reflect the
// intended bounce phase and pass the other one, which would otherwise make a
// ghost image.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { polygonFace, dielectricSolid, refract } from './RayTracer.js';
import { anglesToDirection } from '../model/eye.js';

export function computeWaveguide(p, glasses, eye) {
  const W = p.waveguide;
  const lf = glasses.lenses.R;
  const t = W.thickness, h = W.height;
  // plate frame: u toward the nose (lens local +x), v up, n forward (lens normal)
  const u = new Vector3(1, 0, 0).applyQuaternion(lf.quaternion);
  const v = new Vector3(0, 1, 0).applyQuaternion(lf.quaternion);
  const n = lf.normal.clone();
  const mid = lf.backCenter.clone().addScaledVector(n, -(W.gapToLens + t / 2)); // plate mid-plane point
  const toWorld = (uu, vv, nn) => mid.clone().addScaledVector(u, uu).addScaledVector(v, vv).addScaledVector(n, nn);
  const local = (pt) => { const d = pt.clone().sub(mid); return { u: d.dot(u), v: d.dot(v), n: d.dot(n) }; };

  // where the HUD direction crosses the plate mid-plane: the out-coupling area
  const A = anglesToDirection(p.intent.azimuth, p.intent.elevation, 1);
  const tHit = mid.clone().sub(eye.pupilCenter).dot(n) / A.dot(n);
  const C = local(eye.pupilCenter.clone().addScaledVector(A, tHit));

  // guided direction (bounce phase that the facets serve) and the in-glass
  // direction that leaves the back face toward the eye along -A
  const g = (W.guideAngle * Math.PI) / 180;
  const I = u.clone().multiplyScalar(Math.sin(g)).addScaledVector(n, Math.cos(g));
  const ng = p.prism.n;
  const inGlass = refract(A.clone(), n.clone().negate(), 1.000293, ng); // eye -> plate, reversed below
  const Rin = inGlass ? inGlass.clone().negate() : n.clone().negate();
  const nf = I.clone().sub(Rin).normalize(); // facet normal: reflects I into Rin

  const N = Math.max(1, Math.round(W.facets));
  const facets = [];
  for (let k = 0; k < N; k++) {
    const uc = C.u + (k - (N - 1) / 2) * W.facetSpacing;
    const centre = toWorld(uc, C.v, 0);
    // corners: facet plane ∩ plate faces (n = ±t/2) ∩ (v = C.v ± h/2)
    const corner = (vv, nn) => {
      const q = toWorld(0, vv, nn);
      const s = centre.clone().sub(q).dot(nf) / u.dot(nf);
      return q.addScaledVector(u, s);
    };
    facets.push({ centre, corners: [corner(C.v - h / 2, -t / 2), corner(C.v - h / 2, t / 2), corner(C.v + h / 2, t / 2), corner(C.v + h / 2, -t / 2)] });
  }
  // incidence of the two bounce phases on the facets -> coating cut-off
  const Idown = u.clone().multiplyScalar(Math.sin(g)).addScaledVector(n, -Math.cos(g));
  const incWanted = (Math.acos(Math.abs(I.dot(nf))) * 180) / Math.PI;
  const incOther = (Math.acos(Math.abs(Idown.dot(nf))) * 180) / Math.PI;
  const cutoff = (incWanted + incOther) / 2;

  // plate extent: temple end near the lens's temporal edge, nasal end past the last facet
  const uT = -p.frame.lensWidth / 2 + W.templeMargin;
  const uN = Math.max(C.u + ((N - 1) / 2) * W.facetSpacing + 3 + t, uT + 8);
  // temple end face perpendicular to I (light enters it at normal incidence)
  const uEnd = (nn) => uT - (I.dot(n) / I.dot(u)) * nn;
  const P = (uu, vv, nn) => toWorld(uu, C.v + vv, nn);
  const c = {
    tb: P(uEnd(-t / 2), -h / 2, -t / 2), tt: P(uEnd(-t / 2), h / 2, -t / 2), tbf: P(uEnd(t / 2), -h / 2, t / 2), ttf: P(uEnd(t / 2), h / 2, t / 2),
    nb: P(uN, -h / 2, -t / 2), nt: P(uN, h / 2, -t / 2), nbf: P(uN, -h / 2, t / 2), ntf: P(uN, h / 2, t / 2),
  };
  const centroid = Object.values(c).reduce((s, x) => s.add(x), new Vector3()).multiplyScalar(1 / 8);
  const face = (verts, role) => {
    let f = polygonFace(verts, { role });
    if (f.normal.dot(f.centroid.clone().sub(centroid)) < 0) f = polygonFace(verts.slice().reverse(), { role });
    return f;
  };
  const faces = {
    back: face([c.tb, c.nb, c.nt, c.tt], 'guideBack'),
    front: face([c.tbf, c.ttf, c.ntf, c.nbf], 'guideFront'),
    bottom: face([c.tb, c.tbf, c.nbf, c.nb], 'guideEdge'),
    top: face([c.tt, c.nt, c.ntf, c.ttf], 'guideEdge'),
    nasal: face([c.nb, c.nbf, c.ntf, c.nt], 'guideEnd'),
    entry: face([c.tb, c.tt, c.ttf, c.tbf], 'guideEntry'),
  };
  faces.bottom.absorb = true; faces.top.absorb = true; faces.nasal.absorb = true; // blackened edges
  const facetFaces = facets.map((f, k) => {
    const pf = polygonFace(f.corners, { role: 'facet' });
    // 'selective': custom angle-selective coating; 'plain': a stock partial
    // reflector, same reflectance at every incidence (conservative)
    pf.facetR = W.facetR; pf.facetCutoffDeg = W.coating === 'plain' ? null : cutoff; pf.facetRHigh = 0.01;
    pf.facetIndex = k;
    return pf;
  });
  const entryPoint = P(uT, 0, 0);
  const volumeMm3 = t * h * (uN - uT);
  const vertices = c;
  const center = P((uT + uN) / 2, 0, 0);
  return {
    kind: 'waveguide', vertices, center, entryCenter: entryPoint, exitCenter: facets[Math.floor(N / 2)].centre,
    Lac: t / Math.max(0.2, Math.abs(I.dot(u))), H: h, w: v.clone(), length: uN - uT,
    u, v, n, mid, I, Rin, nf, t, h, uT, uN, C, facets, facetFaces, faces, entryPoint, corners: c, cutoff, incWanted, incOther,
    volumeMm3, quaternion: new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(u, v, n)),
    entryWidth: t / Math.max(0.2, Math.abs(I.dot(u))),
  };
}

export function waveguideObjects(wg, material) {
  return [dielectricSolid('guide', 'Waveguide', material, [...Object.values(wg.faces), ...wg.facetFaces], undefined)];
}

/** Places the OLED + collimator on the waveguide's input axis (behind the
 *  temple end), disables the prism, and sizes the lens stop to the entry face. */
export function alignWaveguide(p, glasses, eye, { distance } = {}) {
  const wg = computeWaveguide(p, glasses, eye);
  const s = distance ?? p.collimator.distance + 2;
  const oled = wg.entryPoint.clone().addScaledVector(wg.I, -s);
  const z = wg.I.clone();
  const y = wg.v.clone().sub(z.clone().multiplyScalar(wg.v.dot(z))).normalize();
  const x = new Vector3().crossVectors(y, z);
  return { wg, oledCenter: oled, basis: { x, y, z } };
}

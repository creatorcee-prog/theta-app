// Geometric (sequential-free) ray tracer for the HUD optics.
//
// Ray/surface intersection uses three.js's math library (THREE.Ray,
// Triangle, Sphere, Box3, Plane), which is pure geometry and runs without a
// renderer, so this module also runs in Node for the unit tests. The optical
// physics on top of it is implemented here explicitly:
//   * Snell's law in vector form at every dielectric interface
//   * Fresnel reflectance/transmittance (unpolarised) with optional ghost rays
//   * total internal reflection, decided per hit from the actual angle
//   * vector reflection R = I - 2(I.N)N
//   * an ideal thin lens and real conic (aspheric/spherical) lens surfaces
// Units: millimetres everywhere.

import { Ray, Vector3, Sphere, Box3, Matrix4, Plane } from 'three';
import { fresnel, AIR } from './materials.js';

const EPS = 1e-6;

// ---------------------------------------------------------------- vectors

// R = I - 2(I.N)N. I and N unit vectors; sign of N does not matter.
export function reflect(I, N) {
  return I.clone().sub(N.clone().multiplyScalar(2 * I.dot(N))).normalize();
}

// Vector Snell's law. N must face against I (I.N < 0). Returns null on TIR.
//   n1 sin(t1) = n2 sin(t2)
export function refract(I, N, n1, n2) {
  const eta = n1 / n2;
  const cosI = -I.dot(N);
  const sinT2 = eta * eta * (1 - cosI * cosI);
  if (sinT2 > 1) return null;
  const cosT = Math.sqrt(1 - sinT2);
  return I.clone().multiplyScalar(eta).add(N.clone().multiplyScalar(eta * cosI - cosT)).normalize();
}

// ---------------------------------------------------------------- surfaces
// Every face exposes intersect(ray, tMin) -> {t, point, normal} | null, where
// normal is the OUTWARD normal of the solid that owns it.

const _tmp = new Vector3();

export function polygonFace(vertices, { role = 'face', absorb = false } = {}) {
  // Convex planar polygon, vertices ordered so (v1-v0)x(v2-v0) is outward.
  const n = new Vector3().subVectors(vertices[1], vertices[0])
    .cross(new Vector3().subVectors(vertices[2], vertices[0])).normalize();
  const centroid = vertices.reduce((c, v) => c.add(v), new Vector3()).multiplyScalar(1 / vertices.length);
  return {
    type: 'polygon', role, absorb, vertices, normal: n, centroid,
    intersect(ray, tMin) {
      for (let i = 1; i < vertices.length - 1; i++) {
        const p = ray.intersectTriangle(vertices[0], vertices[i], vertices[i + 1], false, _tmp);
        if (p) {
          const t = p.distanceTo(ray.origin);
          if (t > tMin) return { t, point: p.clone(), normal: n.clone() };
          return null;
        }
      }
      return null;
    },
  };
}

// Flat circular disc (lens plano side, mounts, pupils). normal = outward.
export function discFace(center, normal, radius, { role = 'disc', absorb = false, innerRadius = 0 } = {}) {
  const plane = new Plane().setFromNormalAndCoplanarPoint(normal, center);
  return {
    type: 'disc', role, absorb, center, normal: normal.clone(), radius, innerRadius,
    intersect(ray, tMin) {
      const denom = plane.normal.dot(ray.direction);
      if (Math.abs(denom) < 1e-12) return null;
      const t = -(ray.origin.dot(plane.normal) + plane.constant) / denom;
      if (t <= tMin) return null;
      const p = ray.at(t, new Vector3());
      const r = p.distanceTo(center);
      if (r > radius || r < innerRadius) return null;
      return { t, point: p, normal: normal.clone() };
    },
  };
}

// Conic surface of a lens, defined in a local frame (origin at the surface
// vertex, +z = outward axis). sag(r) = c r^2 / (1 + sqrt(1 - (1+k) c^2 r^2)),
// surface points: z = -sag(r). Solved analytically as a quadric.
export function conicFace(vertex, axis, curvature, conicK, apertureRadius, { role = 'conic' } = {}) {
  const c = curvature;
  const k = conicK;
  const toLocal = new Matrix4();
  const toWorld = new Matrix4();
  const basis = orthonormalBasis(axis);
  toWorld.makeBasis(basis.x, basis.y, basis.z).setPosition(vertex);
  toLocal.copy(toWorld).invert();
  const sag = (r) => {
    const q = 1 - (1 + k) * c * c * r * r;
    if (q < 0) return NaN;
    return (c * r * r) / (1 + Math.sqrt(q));
  };
  return {
    type: 'conic', role, absorb: false, vertex, axis: axis.clone(), c, k, apertureRadius, sag,
    intersect(ray, tMin) {
      const o = ray.origin.clone().applyMatrix4(toLocal);
      const d = ray.direction.clone().transformDirection(toLocal);
      // zeta = -z (sag measured into the glass)
      const z0 = -o.z, dz = -d.z;
      const A = c * (d.x * d.x + d.y * d.y) + (1 + k) * c * dz * dz;
      const B = 2 * c * (o.x * d.x + o.y * d.y) + 2 * (1 + k) * c * z0 * dz - 2 * dz;
      const C = c * (o.x * o.x + o.y * o.y) + (1 + k) * c * z0 * z0 - 2 * z0;
      const roots = [];
      if (Math.abs(A) < 1e-14) {
        if (Math.abs(B) > 1e-14) roots.push(-C / B);
      } else {
        const disc = B * B - 4 * A * C;
        if (disc < 0) return null;
        const s = Math.sqrt(disc);
        roots.push((-B - s) / (2 * A), (-B + s) / (2 * A));
      }
      roots.sort((a, b) => a - b);
      for (const t of roots) {
        if (t <= tMin) continue;
        const px = o.x + t * d.x, py = o.y + t * d.y, zeta = z0 + t * dz;
        const r = Math.hypot(px, py);
        if (r > apertureRadius) continue;
        const sg = sag(r);
        if (!Number.isFinite(sg) || Math.abs(sg - zeta) > 1e-6 * (1 + Math.abs(zeta))) continue;
        // gradient of c(x^2+y^2) + (1+k)c zeta^2 - 2 zeta, with z = -zeta
        const nl = new Vector3(2 * c * px, 2 * c * py, 2 - 2 * (1 + k) * c * zeta).normalize();
        const point = new Vector3(px, py, -zeta).applyMatrix4(toWorld);
        const normal = nl.transformDirection(toWorld);
        return { t, point, normal };
      }
      return null;
    },
  };
}

// Cylindrical lens edge (ground/blackened: absorbing). Axis from base along
// axis for `length`.
export function cylinderFace(base, axis, radius, length, { role = 'edge', absorb = true } = {}) {
  const a = axis.clone().normalize();
  return {
    type: 'cylinder', role, absorb,
    intersect(ray, tMin) {
      const oc = ray.origin.clone().sub(base);
      const d = ray.direction;
      const dPerp = d.clone().sub(a.clone().multiplyScalar(d.dot(a)));
      const oPerp = oc.clone().sub(a.clone().multiplyScalar(oc.dot(a)));
      const A = dPerp.lengthSq(), B = 2 * dPerp.dot(oPerp), C = oPerp.lengthSq() - radius * radius;
      if (A < 1e-14) return null;
      const disc = B * B - 4 * A * C;
      if (disc < 0) return null;
      const s = Math.sqrt(disc);
      for (const t of [(-B - s) / (2 * A), (-B + s) / (2 * A)]) {
        if (t <= tMin) continue;
        const p = ray.at(t, new Vector3());
        const h = p.clone().sub(base).dot(a);
        if (h < 0 || h > length) continue;
        const normal = p.clone().sub(base).sub(a.clone().multiplyScalar(h)).normalize();
        return { t, point: p, normal };
      }
      return null;
    },
  };
}

export function orthonormalBasis(z) {
  const zz = z.clone().normalize();
  const helper = Math.abs(zz.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
  const x = new Vector3().crossVectors(helper, zz).normalize();
  const y = new Vector3().crossVectors(zz, x).normalize();
  return { x, y, z: zz };
}

// ---------------------------------------------------------------- objects

// Convex dielectric solid bounded by faces (prism, real lens, spectacle lens).
// exitType: segment type after leaving the solid (undefined -> 'emerge',
// null -> keep the type the ray had before it entered).
export function dielectricSolid(id, label, material, faces, exitType) {
  return { kind: 'solid', id, label, material, faces, exitType };
}

// Ideal thin lens: a disc where ray slopes change by -h/f. Exact for an
// aberration-free lens: every ray from a point on the front focal plane
// leaves parallel. Rays beyond the clear aperture but inside the mount are
// absorbed.
export function thinLens(id, label, center, axis, focalLength, apertureRadius, mountRadius) {
  return { kind: 'thinLens', id, label, center, axis: axis.clone().normalize(), f: focalLength, apertureRadius, mountRadius };
}

// Oriented box absorber (housings, frame parts, boards).
export function boxAbsorber(id, label, matrixWorld, size) {
  const inv = matrixWorld.clone().invert();
  const box = new Box3(size.clone().multiplyScalar(-0.5), size.clone().multiplyScalar(0.5));
  return { kind: 'absorber', shape: 'box', id, label, matrixWorld, inv, box };
}

export function sphereAbsorber(id, label, center, radius) {
  return { kind: 'absorber', shape: 'sphere', id, label, sphere: new Sphere(center.clone(), radius) };
}

export function discAbsorber(id, label, center, normal, radius, innerRadius = 0) {
  return { kind: 'absorber', shape: 'disc', id, label, face: discFace(center, normal, radius, { innerRadius }) };
}

// Eye detector: entrance-pupil disc plus eyeball/cornea spheres. External
// rays are tested against the entrance pupil directly (the standard way to
// handle corneal refraction for rays arriving from outside the eye).
export function eyeDetector(id, label, eye) {
  return {
    kind: 'eye', id, label, eye,
    pupil: discFace(eye.pupilCenter, eye.gaze, eye.pupilRadius),
    spheres: [new Sphere(eye.rotationCenter.clone(), eye.eyeballRadius), new Sphere(eye.corneaCenter.clone(), eye.corneaRadius)],
  };
}

// ---------------------------------------------------------------- tracing

function intersectObject(obj, ray, tMin, insideSolidId) {
  if (obj.kind === 'solid') {
    if (insideSolidId != null && insideSolidId !== obj.id) return null;
    let best = null;
    for (const f of obj.faces) {
      const h = f.intersect(ray, tMin);
      if (h && (!best || h.t < best.t)) best = { ...h, face: f };
    }
    return best ? { ...best, obj } : null;
  }
  if (insideSolidId != null) return null; // nothing else exists inside glass
  if (obj.kind === 'thinLens') {
    obj._disc ??= discFace(obj.center, obj.axis, obj.mountRadius);
    const d = obj._disc.intersect(ray, tMin);
    if (!d) return null;
    return { ...d, obj, inAperture: d.point.distanceTo(obj.center) <= obj.apertureRadius };
  }
  if (obj.kind === 'absorber') {
    if (obj.shape === 'sphere') {
      const p = ray.intersectSphere(obj.sphere, new Vector3());
      if (!p) return null;
      const t = p.distanceTo(ray.origin);
      return t > tMin ? { t, point: p, obj } : null;
    }
    if (obj.shape === 'disc' || obj.shape === 'cylinder') {
      const h = obj.face.intersect(ray, tMin);
      return h ? { ...h, obj } : null;
    }
    const local = ray.clone().applyMatrix4(obj.inv);
    // Box3 test ignores rays starting inside; that is fine for solid absorbers.
    const p = local.intersectBox(obj.box, new Vector3());
    if (!p) return null;
    const pw = p.applyMatrix4(obj.matrixWorld);
    const t = pw.distanceTo(ray.origin);
    return t > tMin ? { t, point: pw, obj } : null;
  }
  if (obj.kind === 'eye') {
    const hp = obj.pupil.intersect(ray, tMin);
    const frontFacing = ray.direction.dot(obj.eye.gaze) < 0;
    let best = null;
    for (const s of obj.spheres) {
      const p = ray.intersectSphere(s, new Vector3());
      if (p) {
        const t = p.distanceTo(ray.origin);
        if (t > tMin && (!best || t < best.t)) best = { t, point: p };
      }
    }
    if (hp && frontFacing) {
      // Count at the cornea's t so ordering against other objects is right.
      return { t: best ? Math.min(best.t, hp.t) : hp.t, point: hp.point, obj, pupil: true };
    }
    return best ? { ...best, obj, pupil: false } : null;
  }
  return null;
}

/**
 * Trace a set of source rays through an optical scene.
 * scene: { objects: [...], escapeLength }
 * sources: [{ origin, dir, weight, lambda, color, pixel, chief }]
 * options: { maxDepth, ghosts, ghostMin, recordPaths }
 * Returns paths: one per (branch of a) ray with segments and an outcome.
 */
export function trace(scene, sources, options = {}) {
  const { maxDepth = 16, ghosts = false, ghostMin = 0.01, minWeight = 1e-4 } = options;
  const paths = [];
  const stack = sources.map((s, i) => ({
    origin: s.origin.clone(), dir: s.dir.clone().normalize(), weight: s.weight,
    lambda: s.lambda, color: s.color, pixel: s.pixel, source: i, chief: !!s.chief,
    inside: null, depth: 0, primary: true, lastType: 'emit', parent: -1, events: [],
  }));

  while (stack.length) {
    const r = stack.pop();
    const path = {
      source: r.source, pixel: r.pixel, lambda: r.lambda, color: r.color, chief: r.chief,
      primary: r.primary, parent: r.parent, segments: [], events: r.events, weight0: r.weight,
      outcome: 'escaped', finalWeight: r.weight, finalRay: null, lastOptic: null,
    };
    const pathIndex = paths.push(path) - 1;
    let { origin, dir, weight, inside, depth, lastType } = r;
    let typeBeforeEntry = lastType;
    const ray = new Ray();

    while (true) {
      ray.set(origin, dir);
      let hit = null;
      for (const obj of scene.objects) {
        const h = intersectObject(obj, ray, EPS, inside);
        if (h && (!hit || h.t < hit.t)) hit = h;
      }
      if (!hit) {
        const end = origin.clone().addScaledVector(dir, scene.escapeLength ?? 40);
        path.segments.push({ a: origin.clone(), b: end, type: lastType, w: weight });
        path.outcome = inside ? 'trapped' : 'escaped';
        path.finalRay = { origin: origin.clone(), dir: dir.clone(), weight };
        break;
      }
      path.segments.push({ a: origin.clone(), b: hit.point.clone(), type: lastType, w: weight });
      const obj = hit.obj;

      if (obj.kind === 'eye') {
        path.finalRay = { origin: origin.clone(), dir: dir.clone(), weight };
        path.outcome = hit.pupil ? `pupil:${obj.id}` : `eyeMiss:${obj.id}`;
        path.hitPoint = hit.point.clone();
        break;
      }
      if (obj.kind === 'absorber') {
        path.outcome = `absorbed:${obj.id}`;
        path.hitPoint = hit.point.clone();
        break;
      }
      if (obj.kind === 'thinLens') {
        if (!hit.inAperture) { path.outcome = `absorbed:${obj.id}-mount`; break; }
        // ideal lens: slope vector s = d_perp/(d.n); s' = s - h/f
        const n = obj.axis.clone();
        let dn = dir.dot(n);
        const sign = dn >= 0 ? 1 : -1;
        if (sign < 0) { n.negate(); dn = -dn; }
        const h = hit.point.clone().sub(obj.center);
        h.sub(n.clone().multiplyScalar(h.dot(n)));
        const s = dir.clone().sub(n.clone().multiplyScalar(dn)).multiplyScalar(1 / dn);
        s.sub(h.multiplyScalar(1 / obj.f));
        dir = n.clone().add(s).normalize();
        origin = hit.point.clone();
        lastType = 'lens';
        path.lastOptic = obj.id;
        r.events.push({ obj: obj.id, kind: 'thinLens' });
        if (++depth > maxDepth) { path.outcome = 'maxDepth'; break; }
        continue;
      }

      // ---- dielectric interface
      const face = hit.face;
      if (face.absorb) { path.outcome = `absorbed:${obj.id}-${face.role}`; path.hitPoint = hit.point.clone(); break; }
      const nGlass = obj.material.indexAt(r.lambda);
      const entering = inside == null;
      const n1 = entering ? AIR.indexAt() : nGlass;
      const n2 = entering ? nGlass : AIR.indexAt();
      // Normal facing against the incident ray
      const N = hit.normal.clone();
      if (N.dot(dir) > 0) N.negate();
      const cosI = Math.min(1, -dir.dot(N));
      const fr = fresnel(n1, n2, cosI);
      const incidence = Math.acos(cosI);
      const ev = {
        obj: obj.id, face: face.role, entering, incidenceDeg: (incidence * 180) / Math.PI,
        criticalDeg: n1 > n2 ? (Math.asin(n2 / n1) * 180) / Math.PI : null,
        tir: fr.tir, R: fr.R, T: fr.T, point: hit.point.clone(),
      };
      r.events.push(ev);
      path.lastOptic = obj.id;
      const R = reflect(dir, N);

      if (face.facetR != null) {
        // partially reflective facet embedded in the glass (same glass on both
        // sides, so no refraction): the reflected share continues on this path,
        // the transmitted share continues as its own path. facetT = 0 makes a
        // full mirror (e.g. the in-coupling mirror).
        // angle-selective coating (reflective waveguides): full reflectance
        // below the cut-off incidence, ~1% above it
        const facetR = face.facetCutoffDeg != null && incidence * 180 / Math.PI > face.facetCutoffDeg ? (face.facetRHigh ?? 0.01) : face.facetR;
        const T = face.facetT ?? 1 - facetR;
        ev.tir = false; ev.mirror = true; ev.facet = true; ev.R = facetR; ev.T = T;
        if (T > 0 && weight * T >= minWeight && depth < maxDepth) {
          stack.push({
            origin: hit.point.clone(), dir: dir.clone(), weight: weight * T, lambda: r.lambda, color: r.color,
            pixel: r.pixel, source: r.source, chief: false, inside, depth: depth + 1, primary: r.primary,
            lastType, parent: pathIndex, events: [...r.events],
          });
        }
        weight *= facetR;
        dir = R;
        origin = hit.point.clone();
        lastType = r.primary ? 'reflect' : 'ghost';
        if (++depth > maxDepth || weight < minWeight) { path.outcome = 'maxDepth'; break; }
        continue;
      }
      if (face.mirrorR != null) {
        // metal-coated face: specular reflection with fixed reflectance
        ev.tir = false; ev.mirror = true; ev.R = face.mirrorR; ev.T = 0;
        weight *= face.mirrorR;
        dir = R;
        origin = hit.point.clone();
        lastType = r.primary ? 'reflect' : 'ghost';
        if (++depth > maxDepth || weight < minWeight) { path.outcome = 'maxDepth'; break; }
        continue;
      }
      if (fr.tir) {
        dir = R;
        origin = hit.point.clone();
        lastType = 'tir';
      } else {
        const Tdir = refract(dir, N, n1, n2);
        // ghost (Fresnel-reflected) branch
        if (ghosts && weight * fr.R >= ghostMin && depth < maxDepth) {
          stack.push({
            origin: hit.point.clone(), dir: R, weight: weight * fr.R, lambda: r.lambda, color: r.color,
            pixel: r.pixel, source: r.source, chief: false, inside, depth: depth + 1, primary: false,
            lastType: 'ghost', parent: pathIndex, events: [...r.events],
          });
        }
        weight *= fr.T;
        dir = Tdir;
        origin = hit.point.clone();
        if (entering) { inside = obj.id; typeBeforeEntry = lastType; lastType = 'glass'; }
        else {
          inside = null;
          if (face.role === 'hypotenuse') lastType = 'leak';
          else lastType = obj.exitType === undefined ? 'emerge' : (obj.exitType ?? typeBeforeEntry);
        }
      }
      if (!r.primary) lastType = 'ghost';
      if (++depth > maxDepth || weight < minWeight) { path.outcome = 'maxDepth'; break; }
    }
    path.finalWeight = weight;
  }
  return paths;
}

// Uniform-in-solid-angle directions inside a cone of half-angle alpha around
// +z (Fibonacci spiral on the spherical cap). Deterministic.
export function coneDirections(count, halfAngle) {
  const out = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  const cosA = Math.cos(halfAngle);
  for (let i = 0; i < count; i++) {
    const cz = 1 - (1 - cosA) * ((i + 0.5) / count);
    const sz = Math.sqrt(Math.max(0, 1 - cz * cz));
    const phi = i * golden;
    out.push(new Vector3(sz * Math.cos(phi), sz * Math.sin(phi), cz));
  }
  return out;
}

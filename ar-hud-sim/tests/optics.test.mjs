// Physics checks against closed-form results. Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import { refract, reflect, trace, polygonFace, dielectricSolid, thinLens, coneDirections, conicFace, discFace, cylinderFace } from '../js/optics/RayTracer.js';
import { fresnel, criticalAngle, sellmeierBK7, makeGlass, deg, rad, AIR } from '../js/optics/materials.js';
import { computePrism } from '../js/optics/OpticalComponents.js';
import { defaultParams } from '../js/config/defaults.js';
import { runSimulation } from '../js/optics/Simulation.js';
import { analyzeCoverage, clipPolygon, polygonArea, convexHull } from '../js/optics/CoverageAnalyzer.js';
import { roundedRectArea, roundedRectOutline } from '../js/model/glassesGeometry.js';

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg ?? ''} expected ${b}, got ${a}`);
const N = 1.517;
const NA = AIR.n550; // the tracer uses the real index of air

test('Snell: 30° air → BK7 refracts to asin(sin30/n)', () => {
  const I = new Vector3(Math.sin(rad(30)), 0, -Math.cos(rad(30)));
  const T = refract(I, new Vector3(0, 0, 1), 1, N);
  near(deg(Math.asin(Math.hypot(T.x, T.y))), deg(Math.asin(0.5 / N)), 1e-9, 'refraction angle');
});

test('Snell: beyond critical angle returns null (TIR)', () => {
  const a = rad(42);
  const I = new Vector3(Math.sin(a), 0, -Math.cos(a));
  assert.equal(refract(I, new Vector3(0, 0, 1), N, 1), null);
  const b = rad(40);
  assert.notEqual(refract(new Vector3(Math.sin(b), 0, -Math.cos(b)), new Vector3(0, 0, 1), N, 1), null);
});

test('critical angle of BK7 (n=1.517) is ≈41.2°', () => {
  near(deg(criticalAngle(N, 1)), 41.24, 0.01);
  near(deg(criticalAngle(N, NA)), 41.25, 0.01);
});

test('reflection R = I - 2(I.N)N', () => {
  const R = reflect(new Vector3(1, -1, 0).normalize(), new Vector3(0, 1, 0));
  near(R.x, Math.SQRT1_2, 1e-12); near(R.y, Math.SQRT1_2, 1e-12);
});

test('Fresnel: normal incidence R = ((n-1)/(n+1))^2, Brewster Rp = 0, energy conserved', () => {
  const f0 = fresnel(1, N, 1);
  near(f0.R, ((N - 1) / (N + 1)) ** 2, 1e-12);
  const fb = fresnel(1, N, Math.cos(Math.atan(N)));
  near(fb.Rp, 0, 1e-12);
  for (const c of [0.1, 0.5, 0.9]) { const f = fresnel(N, 1, c); if (!f.tir) near(f.R + f.T, 1, 1e-12); }
  assert.equal(fresnel(N, 1, Math.cos(rad(45))).tir, true);
});

test('BK7 Sellmeier gives n_d ≈ 1.5168 at 587.6 nm', () => {
  near(sellmeierBK7(587.56), 1.5168, 2e-4);
});

test('45-45-90 prism: axial ray folds 90° by TIR with (1-R)^2 throughput', () => {
  const prism = computePrism({ size: 10, angle: 45, pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } });
  const glass = makeGlass('BK7', N, { dispersive: false });
  const scene = { objects: [dielectricSolid('prism', 'p', glass, Object.values(prism.faces))] };
  const [p] = trace(scene, [{ origin: new Vector3(-20, 0, 0), dir: new Vector3(1, 0, 0), weight: 1 }]);
  const last = p.finalRay.dir;
  near(last.x, 0, 1e-9); near(last.y, -1, 1e-9);
  const hyp = p.events.find((e) => e.face === 'hypotenuse');
  assert.equal(hyp.tir, true); near(hyp.incidenceDeg, 45, 1e-9);
  near(p.finalWeight, (1 - ((N - NA) / (N + NA)) ** 2) ** 2, 1e-9);
});

test('45-45-90 prism: a ray tilted 6° in air breaks TIR (leaks), 5° does not', () => {
  const prism = computePrism({ size: 10, angle: 45, pos: { x: 0, y: 0, z: 0 }, rot: { yaw: 0, pitch: 0, roll: 0 } });
  const glass = makeGlass('BK7', N, { dispersive: false });
  const scene = { objects: [dielectricSolid('prism', 'p', glass, Object.values(prism.faces))] };
  // tilting toward +y lowers the hypotenuse incidence: 45 - asin(sin(a)/n)
  const run = (a) => trace(scene, [{ origin: new Vector3(-20, -20 * Math.tan(rad(a)), 0), dir: new Vector3(Math.cos(rad(a)), Math.sin(rad(a)), 0), weight: 1 }])[0];
  const leak = run(6), ok = run(5);
  near(leak.events.find((e) => e.face === 'hypotenuse').incidenceDeg, 45 - deg(Math.asin((NA * Math.sin(rad(6))) / N)), 1e-6);
  assert.equal(leak.events.find((e) => e.face === 'hypotenuse').tir, false);
  assert.ok(leak.segments.some((s) => s.type === 'leak'));
  assert.equal(ok.events.find((e) => e.face === 'hypotenuse').tir, true);
});

test('equilateral prism minimum deviation matches n = sin((A+D)/2)/sin(A/2)', () => {
  // Build a 60° prism from generic faces; trace the symmetric ray.
  const s = 20, h = (s * Math.sqrt(3)) / 2;
  const A2 = [0, h * 2 / 3], B2 = [-s / 2, -h / 3], C2 = [s / 2, -h / 3];
  const V = (p, z) => new Vector3(p[0], p[1], z);
  const faces = [
    polygonFace([V(A2, -5), V(B2, -5), V(B2, 5), V(A2, 5)]),
    polygonFace([V(C2, -5), V(A2, -5), V(A2, 5), V(C2, 5)]),
    polygonFace([V(B2, -5), V(C2, -5), V(C2, 5), V(B2, 5)]),
  ].map((f) => (f.normal.dot(f.centroid) < 0 ? polygonFace(f.vertices.slice().reverse()) : f));
  const glass = makeGlass('BK7', N, { dispersive: false });
  const Dmin = 2 * Math.asin((N / NA) * Math.sin(rad(30))) - rad(60);
  // symmetric passage: incidence angle i = (A + Dmin)/2 on the left face
  const i = (rad(60) + Dmin) / 2;
  const nL = new Vector3(-Math.cos(rad(30)), Math.sin(rad(30)), 0); // left face outward normal
  const tang = new Vector3(nL.y, -nL.x, 0);
  const dir = nL.clone().negate().multiplyScalar(Math.cos(i)).addScaledVector(tang, -Math.sin(i)).normalize();
  const hitPt = new Vector3((A2[0] + B2[0]) / 2, (A2[1] + B2[1]) / 2, 0);
  const [p] = trace({ objects: [dielectricSolid('p', 'p', glass, faces)] }, [{ origin: hitPt.clone().addScaledVector(dir, -30), dir, weight: 1 }]);
  const dev = Math.acos(dir.dot(p.finalRay.dir));
  near(deg(dev), deg(Dmin), 1e-6, 'deviation');
});

test('ideal thin lens collimates every ray from a focal-plane point', () => {
  const lens = thinLens('L', 'L', new Vector3(0, 0, 10), new Vector3(0, 0, 1), 10, 5, 6);
  const src = new Vector3(1.3, -0.7, 0);
  const rays = coneDirections(50, rad(15)).map((d) => ({ origin: src, dir: d, weight: 1 }));
  const paths = trace({ objects: [lens] }, rays).filter((p) => p.outcome === 'escaped');
  const d0 = paths[0].finalRay.dir;
  for (const p of paths) near(p.finalRay.dir.angleTo(d0), 0, 1e-9);
  // field angle = atan(h/f)
  near(Math.atan2(Math.hypot(d0.x, d0.y), d0.z), Math.atan(Math.hypot(1.3, 0.7) / 10), 1e-9);
});

test('plano-convex real lens has f = R/(n-1): axial parallel rays focus near f behind', () => {
  const n = N, f = 20, R = f * (n - 1), a = 3;
  const sag = R - Math.sqrt(R * R - a * a), t = sag + 1;
  const ax = new Vector3(0, 0, 1);
  const faces = [
    conicFace(new Vector3(0, 0, 0), ax.clone().negate(), 1 / R, 0, a), // convex facing -z
    discFace(new Vector3(0, 0, t), ax, a),
    cylinderFace(new Vector3(0, 0, sag), ax, a, t - sag),
  ];
  const glass = makeGlass('BK7', n, { dispersive: false });
  const h = 0.3; // paraxial
  const [p] = trace({ objects: [dielectricSolid('L', 'L', glass, faces, 'lens')] }, [{ origin: new Vector3(h, 0, -10), dir: ax, weight: 1 }]);
  const fr = p.finalRay;
  const zCross = fr.origin.z + (-fr.origin.x / fr.dir.x) * fr.dir.z;
  // Back focal distance from the plano surface = f - t/n
  near(zCross - t, f - t / n, 0.05, 'BFD');
});

test('polygon clipping and hull areas', () => {
  const sq = [[0, 0], [2, 0], [2, 2], [0, 2]];
  const sq2 = [[1, 1], [3, 1], [3, 3], [1, 3]];
  near(polygonArea(clipPolygon(sq, sq2)), 1, 1e-12);
  near(polygonArea(convexHull([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]])), 1, 1e-12);
  near(polygonArea(roundedRectOutline(50, 38, 12, 200)), roundedRectArea(50, 38, 12), 0.05);
});

test('default design: chief ray reaches pupil via TIR and numbers are not inflated', () => {
  const r = runSimulation(defaultParams());
  assert.equal(r.chief.outcome, 'pupil:eyeR');
  const cov = analyzeCoverage(r);
  assert.ok(cov.lens.coveragePct < 10, 'coverage is small, as geometry demands');
  // rays at the pupil never exceed rays emitted, power never exceeds emitted
  assert.ok(r.counts.pupil <= r.counts.emitted);
  assert.ok(r.power.pupil <= r.power.emitted + 1e-9);
  // FOV cannot exceed the 2*atan(W/2f) limit of the display + collimator
  const lim = 2 * deg(Math.atan(r.system.oled.width / 2 / 12));
  assert.ok(cov.field.hfov <= lim + 0.5, `hfov ${cov.field.hfov} vs ${lim}`);
  assert.equal(r.counts.leftPupil, 0);
});

test('mirror-coated hypotenuse removes TIR leakage', () => {
  const p = defaultParams();
  const a = runSimulation(p);
  p.prism.coating = 'mirror';
  const b = runSimulation(p);
  assert.ok(a.counts.leaked > 0);
  assert.equal(b.counts.leaked, 0);
});

test('removing the collimator destroys the virtual image (strong divergence)', () => {
  const p = defaultParams();
  p.collimator.enabled = false;
  const r = runSimulation(p);
  const v = r.pixelResults.map((x) => x.vergence).filter(Boolean);
  if (v.length) assert.ok(v.every((x) => x.mean < -10), 'diverging by more than 10 D');
});

test('world frame is right-handed: one fold mirror reports a mirrored image, right eye sits at x < 0', async () => {
  const { runDiagnostics } = await import('../js/optics/Diagnostics.js');
  const r = runSimulation(defaultParams());
  assert.ok(r.system.eye.pupilCenter.x < 0);
  const right = r.system.eye.right;
  assert.ok(right.x < -0.99, 'wearer right is -x');
  const d = runDiagnostics(r, analyzeCoverage(r));
  assert.match(d.checks.find((c) => c.id === 'orientation').value, /^mirrored left–right/);
});

test('measured vergence matches thin-lens prediction for a defocused source', async () => {
  const { bundleVergence } = await import('../js/optics/Simulation.js');
  const f = 12, so = 11, L = 30;
  const lens = thinLens('L', 'L', new Vector3(0, 0, so), new Vector3(0, 0, 1), f, 4, 5);
  const rays = coneDirections(200, rad(14)).map((d) => ({ origin: new Vector3(0.3, -0.2, 0), dir: d, weight: 1 }));
  const paths = trace({ objects: [lens] }, rays).filter((p) => p.outcome === 'escaped' && p.lastOptic === 'L');
  // pupil plane L mm after the lens, facing back toward the lens
  const eye = { pupilCenter: new Vector3(0, 0, so + L), gaze: new Vector3(0, 0, -1), right: new Vector3(1, 0, 0), up: new Vector3(0, 1, 0) };
  const finals = paths.map((p) => {
    const r = p.finalRay; const t = (so + L - r.origin.z) / r.dir.z;
    return { point: r.origin.clone().addScaledVector(r.dir, t), dir: r.dir, w: 1 };
  });
  const v = bundleVergence(finals, eye);
  const si = 1 / (1 / f - 1 / so); // negative: virtual image before the lens
  near(v.mean, -1000 / (-si + L), 0.05, 'vergence D');
  near(v.astig, 0, 1e-6);
});

test('alignment helper aims the real exit ray at the pupil for any prism angle', async () => {
  const { baseParams, alignChain } = await import('../js/config/defaults.js');
  for (const angle of [42, 45, 52, 56]) {
    const p = baseParams();
    p.prism.angle = angle;
    p.prism.coating = 'mirror'; // TIR fails at the low angles; isolate the geometry
    const r = runSimulation(alignChain(p));
    assert.equal(r.chief.outcome, 'pupil:eyeR', `angle ${angle}: ${r.chief.outcome}`);
  }
});

test('vision: spectacle Rx converts to the cornea and drives the focus check', async () => {
  const { cornealPower, assessFocus, meridianPowers } = await import('../js/optics/Vision.js');
  near(cornealPower(-5, 12), -5 / (1 + 0.06), 1e-12);
  near(cornealPower(+5, 12), 5 / (1 - 0.06), 1e-12);
  const m = meridianPowers({ sphere: -1, cyl: -2, axis: 90 });
  near(m.h, -3, 1e-12); near(m.v, -1, 1e-12); // axis 90: full cylinder power acts horizontally
  const eye = { rx: { sphere: -2, cyl: 0, axis: 0 }, eyeRelief: 12, ampMode: 'manual', amplitude: 6, pupilDiameter: 4 };
  const atInf = assessFocus({ Vx: 0, Vy: 0 }, eye);
  assert.ok(atInf.residual > 1.8 && atInf.tooConverging, 'myope cannot focus a collimated HUD');
  const matched = assessFocus({ Vx: atInf.targetVergence, Vy: atInf.targetVergence }, eye);
  near(matched.residual, 0, 1e-9);
});

test('focus solver moves the OLED so the traced vergence matches a -2 D eye', async () => {
  const { solveFocusDistance } = await import('../js/optics/focus.js');
  const p = defaultParams();
  p.prism.coating = 'mirror';
  const r = solveFocusDistance(p, -2);
  assert.ok(r.ok, r.reason);
  near(r.vergence, -2, 0.05);
  assert.ok(r.distance < 12, 'diverging output needs the OLED inside the focal length');
});

test('lens tilt and wrap: alignment still reaches the pupil and keeps the prism behind the tilted lens', async () => {
  const { baseParams, alignChain } = await import('../js/config/defaults.js');
  const { runDiagnostics } = await import('../js/optics/Diagnostics.js');
  const p = baseParams();
  p.frame.pantoTiltDeg = 10; p.frame.wrapDeg = 8; p.prism.coating = 'mirror';
  const r = runSimulation(alignChain(p));
  assert.equal(r.chief.outcome, 'pupil:eyeR');
  const gap = runDiagnostics(r, analyzeCoverage(r)).checks.find((c) => c.id === 'prismLens').value;
  near(parseFloat(gap), p.intent.prismClearance, 0.05, 'clearance to tilted lens plane');
});

test('placed parts block light; BOM totals split sourced and estimated', async () => {
  const { bomTotals } = await import('../js/model/parts.js');
  const p = defaultParams();
  const prism = p.prism.pos;
  p.parts.push({ id: 'blocker', name: 'blocker', size: { x: 30, y: 30, z: 1 }, pos: { ...prism, z: prism.z - 8 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#000', blocksLight: true });
  const r = runSimulation(p);
  assert.ok((r.counts.absorbed['part:blocker'] ?? 0) > 0);
  assert.equal(r.counts.pupil, 0);
  const t = bomTotals([{ unit: 10, qty: 2, include: true, sourced: true }, { unit: 5, qty: 1, include: true, sourced: false }, { unit: 99, qty: 1, include: false, sourced: true }]);
  assert.deepEqual([t.sourced, t.estimated, t.total, t.excluded], [20, 5, 25, 99]);
});

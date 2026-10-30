// Meshes for the Micro-OLED module, HDMI driver board, ribbon cable,
// collimator and BK7 prism. Built from the same geometry objects the tracer
// uses (computeOled / computePrism / computeCollimator).

import * as THREE from 'three';
import { makeLabel } from './labels.js';
import { renderHud } from './hudContent.js';

function ribbonGeometry(curve, width, upHint, segments = 48) {
  const pos = [], idx = [];
  const frames = curve.computeFrenetFrames(segments, false);
  for (let i = 0; i <= segments; i++) {
    const p = curve.getPointAt(i / segments);
    const t = frames.tangents[i];
    const side = new THREE.Vector3().crossVectors(t, upHint).normalize();
    if (side.lengthSq() < 1e-6) side.copy(frames.binormals[i]);
    const width2 = side.multiplyScalar(width / 2);
    pos.push(p.x - width2.x, p.y - width2.y, p.z - width2.z, p.x + width2.x, p.y + width2.y, p.z + width2.z);
    if (i < segments) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

export class OpticalMeshes {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.groups = {};
    for (const [id, label] of [['oled', 'Micro-OLED 0.23″ 640×400'], ['driver', 'HDMI driver board'], ['ribbon', 'Ribbon (FPC) cable'],
      ['collimator', 'Collimating lens'], ['prism', 'BK7 right-angle prism']]) {
      const g = new THREE.Group();
      g.userData.componentId = id;
      g.userData.label = label;
      sceneManager.scene.add(g);
      sceneManager.pickables.push(g);
      this.groups[id] = g;
    }
    // drag handles (the gizmo moves these; main.js maps them back to params)
    this.handles = {};
    for (const id of ['oled', 'prism', 'collimator', 'driver']) {
      const h = new THREE.Object3D();
      h.userData.componentId = id;
      sceneManager.scene.add(h);
      this.handles[id] = h;
    }
    this.hudCanvas = document.createElement('canvas');
    this.hudTexture = null;
  }

  update(system, params, { labels = true } = {}) {
    const { oled, prism, collimator } = system;
    for (const g of Object.values(this.groups)) g.clear();
    const std = (p) => new THREE.MeshStandardMaterial(p);

    // ---------------- OLED
    const og = this.groups.oled;
    const housing = new THREE.Mesh(new THREE.BoxGeometry(oled.housing.size.x, oled.housing.size.y, oled.housing.size.z), std({ color: 0x1c1f24, roughness: 0.6, metalness: 0.3 }));
    housing.position.copy(oled.housing.center);
    housing.quaternion.copy(oled.quaternion);
    og.add(housing);
    // The emitting surface shows the content as the OLED displays it (after
    // the optional driver flip), so the 3D panel matches the eye view.
    const prevSize = [this.hudCanvas.width, this.hudCanvas.height];
    renderHud(this.hudCanvas, params.hud, params.oled, { mirrored: params.hud.driverFlip });
    if (!this.hudTexture || prevSize[0] !== this.hudCanvas.width || prevSize[1] !== this.hudCanvas.height) {
      this.hudTexture?.dispose();
      this.hudTexture = new THREE.CanvasTexture(this.hudCanvas);
      this.hudTexture.colorSpace = THREE.SRGBColorSpace;
    }
    this.hudTexture.needsUpdate = true;
    const b = params.oled.brightness / 100;
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(oled.width, oled.height),
      new THREE.MeshBasicMaterial({ map: this.hudTexture, color: new THREE.Color(b, b, b), toneMapped: false }));
    screen.position.copy(oled.center).addScaledVector(oled.normal, 0.01);
    screen.quaternion.copy(oled.quaternion);
    og.add(screen);
    const frameLine = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) =>
      oled.center.clone().addScaledVector(oled.xAxis, (u * oled.width) / 2).addScaledVector(oled.yAxis, (v * oled.height) / 2).addScaledVector(oled.normal, 0.02))),
    new THREE.LineBasicMaterial({ color: 0xffd36b }));
    og.add(frameLine);
    if (labels) { const l = makeLabel('Micro-OLED'); l.position.copy(oled.housing.center).add(new THREE.Vector3(0, 6, 0)); og.add(l); }
    this.handles.oled.position.copy(oled.center);
    this.handles.oled.quaternion.copy(oled.quaternion);

    // ---------------- driver board + ribbon
    const dg = this.groups.driver;
    const board = new THREE.Group();
    const bs = system.driver.size;
    const pcb = new THREE.Mesh(new THREE.BoxGeometry(bs.x, bs.y, bs.z), std({ color: 0x1f6b3a, roughness: 0.7 }));
    board.add(pcb);
    const chip = new THREE.Mesh(new THREE.BoxGeometry(1.2, 6, 6), std({ color: 0x111111, roughness: 0.4 }));
    chip.position.set(bs.x / 2 + 0.6, 0, 2);
    board.add(chip);
    const hdmi = new THREE.Mesh(new THREE.BoxGeometry(3.2, 7.5, 6), std({ color: 0xb8bec8, metalness: 0.9, roughness: 0.3 }));
    hdmi.position.set(bs.x / 2 + 1.6, 0, -bs.z / 2 + 3);
    board.add(hdmi);
    const dp = system.driver;
    board.position.copy(dp.center);
    board.quaternion.copy(dp.quaternion);
    dg.add(board);
    if (labels) { const l = makeLabel('HDMI driver'); l.position.copy(dp.center).add(new THREE.Vector3(0, bs.y / 2 + 3, 0)); dg.add(l); }
    this.handles.driver.position.copy(dp.center);
    this.handles.driver.quaternion.copy(dp.quaternion);

    const rg = this.groups.ribbon;
    const start = oled.housing.center.clone().addScaledVector(oled.normal, -oled.housing.size.z / 2 - 0.2);
    const end = new THREE.Vector3(bs.x / 2 + 0.3, 0, bs.z / 2 - 2).applyQuaternion(dp.quaternion).add(dp.center);
    const mid1 = start.clone().addScaledVector(oled.normal, -4);
    const mid2 = end.clone().add(new THREE.Vector3(3, 0, 5).applyQuaternion(dp.quaternion));
    const curve = new THREE.CatmullRomCurve3([start, mid1, mid1.clone().lerp(mid2, 0.5).add(new THREE.Vector3(0, -1.5, 0)), mid2, end]);
    const ribbon = new THREE.Mesh(ribbonGeometry(curve, params.driver.ribbonWidth, oled.yAxis.clone().cross(oled.normal).normalize()),
      new THREE.MeshStandardMaterial({ color: 0xd9822b, roughness: 0.5, side: THREE.DoubleSide }));
    rg.add(ribbon);

    // ---------------- collimator
    const cg = this.groups.collimator;
    if (collimator) {
      const a = collimator.apertureRadius;
      let profile;
      if (collimator.mode === 'thin' || !collimator.valid) {
        // symbolic biconvex disc; the tracer uses an ideal thin lens
        const sag = 0.45;
        profile = [];
        for (let i = 0; i <= 16; i++) { const r = (a * i) / 16; profile.push(new THREE.Vector2(r, sag * (1 - (r / a) ** 2) + 0.05)); }
        for (let i = 16; i >= 0; i--) { const r = (a * i) / 16; profile.push(new THREE.Vector2(r, -sag * (1 - (r / a) ** 2) - 0.05)); }
      } else {
        const { thickness: t, sagA } = collimator;
        const sagf = (r) => {
          const q = 1 - (1 + collimator.k) * collimator.c ** 2 * r * r;
          return (collimator.c * r * r) / (1 + Math.sqrt(Math.max(0, q)));
        };
        // local y = axis; plano at y=0 (OLED side) unless flipped
        profile = [new THREE.Vector2(0, 0), new THREE.Vector2(a, 0), new THREE.Vector2(a, t - sagA)];
        for (let i = 16; i >= 0; i--) { const r = (a * i) / 16; profile.push(new THREE.Vector2(r, t - sagf(r))); }
        if (collimator.flip) profile = profile.map((p) => new THREE.Vector2(p.x, t - p.y));
      }
      const geo = new THREE.LatheGeometry(profile, 48);
      geo.rotateX(Math.PI / 2); // lathe axis y -> z
      const lens = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: 0xbfe6ff, transparent: true, opacity: 0.4, roughness: 0.05, metalness: 0, side: THREE.DoubleSide, depthWrite: false }));
      lens.position.copy(collimator.center);
      lens.quaternion.copy(collimator.quaternion);
      cg.add(lens);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(a + 0.7, 0.6, 8, 40), std({ color: 0x30353d, metalness: 0.6, roughness: 0.4 }));
      ring.position.copy(collimator.center);
      ring.quaternion.copy(collimator.quaternion);
      cg.add(ring);
      // lens barrel (printed): holds the whole glass and joins the OLED housing
      const len = Math.max(0.1, collimator.center.clone().sub(oled.center).dot(oled.normal)) + (collimator.thickness || 0);
      const br = Math.max(a + 0.25, (collimator.glassDiameter ?? 2 * a) / 2 + 0.1) + 0.8;
      const barrel = new THREE.Mesh(new THREE.CylinderGeometry(br, br, len, 32, 1, true),
        new THREE.MeshStandardMaterial({ color: 0x56606e, transparent: true, opacity: 0.82, side: THREE.DoubleSide, roughness: 0.6 }));
      barrel.geometry.rotateX(Math.PI / 2);
      barrel.position.copy(oled.center).addScaledVector(oled.normal, len / 2);
      barrel.quaternion.copy(oled.quaternion);
      cg.add(barrel);
      if (labels) { const l = makeLabel(collimator.mode === 'thin' ? `Collimator f=${collimator.f} mm (ideal)` : `Collimator f=${collimator.f} mm`); l.position.copy(collimator.center).add(new THREE.Vector3(0, a + 4, 0)); cg.add(l); }
      this.handles.collimator.position.copy(collimator.center);
      this.handles.collimator.quaternion.copy(collimator.quaternion);
    }

    // ---------------- optics arm (tube from the lens to the prism)
    const arm = system.arm;
    if (arm && arm.length > 0.6) {
      const r = arm.radius + arm.wall / 2;
      const tube = new THREE.Mesh(new THREE.CylinderGeometry(r, r, arm.length, 28, 1, true),
        new THREE.MeshStandardMaterial({ color: 0x56606e, transparent: true, opacity: 0.8, side: THREE.DoubleSide, roughness: 0.6 }));
      tube.geometry.rotateX(Math.PI / 2);
      tube.position.copy(arm.start).addScaledVector(arm.axis, arm.length / 2);
      tube.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), arm.axis);
      cg.add(tube);
      const rings = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.CylinderGeometry(r, r, arm.length, 14, 1, true).rotateX(Math.PI / 2)), new THREE.LineBasicMaterial({ color: 0xaab4c6, transparent: true, opacity: 0.5 }));
      rings.position.copy(tube.position); rings.quaternion.copy(tube.quaternion);
      cg.add(rings);
      if (labels) { const l = makeLabel('Optics arm (holds the prism)'); l.position.copy(tube.position).add(new THREE.Vector3(0, r + 5, 0)); cg.add(l); }
    }

    // ---------------- standoff pins bonding the combiner to the lens back
    const lm = system.lensMount;
    if (lm) {
      const pinMat = new THREE.MeshStandardMaterial({ color: 0x56606e, roughness: 0.5, metalness: 0.2 });
      for (const pin of lm.pins) {
        const m = new THREE.Mesh(new THREE.CylinderGeometry(lm.radius, lm.radius, pin.length, 12), pinMat);
        m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), pin.axis);
        m.position.copy(pin.base).addScaledVector(pin.axis, pin.length / 2);
        this.groups.prism.add(m);
        // glue pad on the lens
        const pad = new THREE.Mesh(new THREE.CylinderGeometry(lm.radius * 1.8, lm.radius * 1.8, 0.3, 16), pinMat);
        pad.quaternion.copy(m.quaternion); pad.position.copy(pin.base).addScaledVector(pin.axis, pin.length - 0.15);
        this.groups.prism.add(pad);
      }
      if (labels) {
        const l = makeLabel(`${lm.pins.length} standoff pins bonded to the lens`, 'muted');
        l.position.copy(lm.pins[0].base).addScaledVector(lm.pins[0].axis, lm.pins[0].length).add(new THREE.Vector3(0, -4, 0));
        this.groups.prism.add(l);
      }
    }

    // ---------------- waveguide plate (replaces the prism)
    if (prism.kind === 'waveguide') { this.drawWaveguide(prism, params, labels); return; }
    if (prism.kind === 'patch') { this.drawPatch(prism, params, labels); if (system.fold) this.drawFold(system.fold, labels); return; }

    // ---------------- prism
    const pg = this.groups.prism;
    const V = prism.vertices;
    const coated = params.prism.coating === 'mirror';
    const faceColors = { entry: 0x9fd8ff, exit: 0x9fd8ff, capTop: 0x9fd8ff, capBottom: 0x9fd8ff, hypotenuse: coated ? 0xd0d4dc : 0xff7ad9 };
    for (const [role, f] of Object.entries(prism.faces)) {
      const pts = f.vertices;
      const pos = [];
      for (let i = 1; i < pts.length - 1; i++) for (const p of [pts[0], pts[i], pts[i + 1]]) pos.push(p.x, p.y, p.z);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      geo.computeVertexNormals();
      const isHyp = role === 'hypotenuse';
      const m = new THREE.MeshPhysicalMaterial({
        color: faceColors[role], transparent: true, opacity: isHyp ? (coated ? 0.85 : 0.32) : 0.16,
        roughness: 0.05, metalness: isHyp && coated ? 0.9 : 0, side: THREE.DoubleSide, depthWrite: false,
      });
      const mesh = new THREE.Mesh(geo, m);
      mesh.renderOrder = 3;
      pg.add(mesh);
    }
    const edges = [['A+', 'B+'], ['B+', 'C+'], ['C+', 'A+'], ['A-', 'B-'], ['B-', 'C-'], ['C-', 'A-'], ['A+', 'A-'], ['B+', 'B-'], ['C+', 'C-']];
    const ep = [];
    for (const [a1, b1] of edges) ep.push(V[a1], V[b1]);
    pg.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(ep), new THREE.LineBasicMaterial({ color: 0xcfeaff })));
    // hypotenuse diagonal hatching so the reflective face reads clearly
    const hv = prism.faces.hypotenuse.vertices;
    const hatch = [];
    for (let k = 1; k < 6; k++) { const t = k / 6; hatch.push(hv[0].clone().lerp(hv[3], t), hv[1].clone().lerp(hv[2], t)); }
    pg.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(hatch), new THREE.LineBasicMaterial({ color: coated ? 0xffffff : 0xff7ad9, transparent: true, opacity: 0.6 })));
    if (labels) {
      const l = makeLabel(`BK7 prism ${params.prism.size}×${params.prism.height} mm, ${params.prism.angle}°`); l.position.copy(prism.center).add(new THREE.Vector3(0, 9, 0)); pg.add(l);
      const lh = makeLabel(coated ? 'Hypotenuse (mirror)' : 'Hypotenuse (TIR face)', 'accent');
      lh.position.copy(prism.faces.hypotenuse.centroid).addScaledVector(prism.faces.hypotenuse.normal, 3); pg.add(lh);
    }
    this.handles.prism.position.copy(prism.center);
    this.handles.prism.quaternion.copy(prism.quaternion);
  }

  drawWaveguide(wg, params, labels) {
    const pg = this.groups.prism;
    const tri = (pts) => {
      const pos = [];
      for (let i = 1; i < pts.length - 1; i++) for (const p of [pts[0], pts[i], pts[i + 1]]) pos.push(p.x, p.y, p.z);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      geo.computeVertexNormals();
      return geo;
    };
    for (const [role, f] of Object.entries(wg.faces)) {
      const edge = f.absorb;
      const m = new THREE.MeshPhysicalMaterial({ color: edge ? 0x2a2f38 : role === 'entry' ? 0x9fd8ff : 0xb8e6ff, transparent: true, opacity: edge ? 0.7 : role === 'entry' ? 0.35 : 0.13, roughness: 0.05, side: THREE.DoubleSide, depthWrite: false });
      const mesh = new THREE.Mesh(tri(f.vertices), m); mesh.renderOrder = 3; pg.add(mesh);
    }
    // embedded partial mirrors
    for (const f of wg.facetFaces) {
      const mesh = new THREE.Mesh(tri(f.vertices), new THREE.MeshPhysicalMaterial({ color: 0xffc46b, transparent: true, opacity: 0.42, metalness: 0.4, roughness: 0.1, side: THREE.DoubleSide, depthWrite: false }));
      mesh.renderOrder = 4; pg.add(mesh);
      const v = f.vertices, ln = [];
      for (let i = 0; i < v.length; i++) ln.push(v[i], v[(i + 1) % v.length]);
      pg.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(ln), new THREE.LineBasicMaterial({ color: 0xffc46b })));
    }
    const c = wg.corners;
    const E = [['tb', 'nb'], ['tt', 'nt'], ['tbf', 'nbf'], ['ttf', 'ntf'], ['tb', 'tt'], ['tbf', 'ttf'], ['nb', 'nt'], ['nbf', 'ntf'], ['tb', 'tbf'], ['tt', 'ttf'], ['nb', 'nbf'], ['nt', 'ntf']];
    pg.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(E.flatMap(([a, b]) => [c[a], c[b]])), new THREE.LineBasicMaterial({ color: 0xcfeaff, transparent: true, opacity: 0.8 })));
    if (labels) {
      const W = params.waveguide;
      const l = makeLabel(`Waveguide ${W.thickness} mm, ${wg.facets.length} facets R ${Math.round(100 * W.facetR)}%, guided at ${W.guideAngle}°`);
      l.position.copy(wg.center).addScaledVector(wg.v, wg.h / 2 + 4); pg.add(l);
      const le = makeLabel('In-coupling face', 'accent'); le.position.copy(wg.entryCenter).addScaledVector(wg.v, -wg.h / 2 - 3); pg.add(le);
    }
    this.handles.prism.position.copy(wg.center);
    this.handles.prism.quaternion.copy(wg.quaternion);
  }

  drawFold(fp, labels) {
    const pg = this.groups.prism;
    for (const [role, f] of Object.entries(fp.faces)) {
      const pts = f.vertices, pos = [];
      for (let i = 1; i < pts.length - 1; i++) for (const q of [pts[0], pts[i], pts[i + 1]]) pos.push(q.x, q.y, q.z);
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.computeVertexNormals();
      const hyp = role === 'hypotenuse';
      const m = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: hyp ? 0xff7ad9 : 0x9fd8ff, transparent: true, opacity: hyp ? 0.35 : 0.18, roughness: 0.05, side: THREE.DoubleSide, depthWrite: false }));
      m.renderOrder = 3; pg.add(m);
    }
    const V = fp.vertices, E = [['A+', 'B+'], ['B+', 'C+'], ['C+', 'A+'], ['A-', 'B-'], ['B-', 'C-'], ['C-', 'A-'], ['A+', 'A-'], ['B+', 'B-'], ['C+', 'C-']];
    pg.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(E.flatMap(([a, b]) => [V[a], V[b]])), new THREE.LineBasicMaterial({ color: 0xcfeaff })));
    if (labels) { const l = makeLabel(`Fold prism ${fp.L} mm (TIR) in the hinge block`); l.position.copy(fp.center).add(new THREE.Vector3(0, fp.L / 2 + 5, 0)); pg.add(l); }
  }

  drawPatch(pt, params, labels) {
    const pg = this.groups.prism;
    if (pt.mode === 'lensback') {
      // the lens back surface is the reflector: tint it
      const o = pt.outline, pos = [];
      for (let i = 1; i < o.length - 1; i++) for (const q of [o[0], o[i], o[i + 1]]) pos.push(q.x, q.y, q.z);
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.computeVertexNormals();
      const m = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: 0xffc46b, transparent: true, opacity: params.patch.coating === 'bare' ? 0.12 : 0.3, metalness: 0.4, roughness: 0.1, side: THREE.DoubleSide, depthWrite: false }));
      m.renderOrder = 4; pg.add(m);
      if (labels) { const l = makeLabel(params.patch.coating === 'bare' ? 'Lens back surface reflects (bare glass)' : 'Lens back surface: partial mirror coating'); l.position.copy(pt.center).add(new THREE.Vector3(0, 8, 0)); pg.add(l); }
      this.handles.prism.position.copy(pt.center);
      return;
    }
    const NR = 6, NA = 32, pos = [], idx = [];
    for (let i = 0; i <= NR; i++) for (let j = 0; j < NA; j++) { const q = pt.at((pt.a * i) / NR, (j / NA) * Math.PI * 2); pos.push(q.x, q.y, q.z); }
    for (let i = 0; i < NR; i++) for (let j = 0; j < NA; j++) {
      const a = i * NA + j, b = i * NA + ((j + 1) % NA), c = (i + 1) * NA + j, d = (i + 1) * NA + ((j + 1) % NA);
      idx.push(a, c, b, b, c, d);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx); geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: 0xffc46b, transparent: true, opacity: 0.45, metalness: 0.5, roughness: 0.1, side: THREE.DoubleSide, depthWrite: false }));
    mesh.renderOrder = 4; pg.add(mesh);
    const rim = []; for (let j = 0; j <= NA; j++) rim.push(pt.at(pt.a, (j / NA) * Math.PI * 2));
    pg.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(rim), new THREE.LineBasicMaterial({ color: 0xffc46b })));
    if (labels) {
      const P = params.patch;
      const l = makeLabel(pt.mode === 'embedded' ? `Partial mirror Ø${P.diameter} mm cast inside the lens` : P.coating === 'bare' ? `Glass reflector Ø${P.diameter} mm (bare cover slip)` : `Mirror patch Ø${P.diameter} mm, R ${P.radius} mm, ${Math.round(100 * P.reflectance)}% reflective`);
      l.position.copy(pt.center).add(new THREE.Vector3(0, pt.a + 5, 0)); pg.add(l);
    }
    this.handles.prism.position.copy(pt.center);
    this.handles.prism.quaternion.copy(pt.quaternion);
  }
}

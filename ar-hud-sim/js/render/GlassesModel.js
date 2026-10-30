// Meshes for the frame, lenses, hinges, temples and the right-temple
// housing, plus the lens-coverage overlay. Geometry comes from
// model/glassesGeometry.js so rendering matches what is traced.

import * as THREE from 'three';
import { offsetPolygon } from '../model/glassesGeometry.js';
import { makeLabel } from './labels.js';

const FRAME_COLOR = 0x2a2f38;

function shapeFrom(points) {
  const s = new THREE.Shape();
  points.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  s.closePath();
  return s;
}

export class GlassesModel {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.root = new THREE.Group();
    this.root.name = 'glasses';
    sceneManager.scene.add(this.root);
    this.overlay = new THREE.Group();
    this.overlay.userData.componentId = 'coverage';
    sceneManager.scene.add(this.overlay);
    this.groups = {};
  }

  mat(params) {
    const m = new THREE.MeshStandardMaterial(params);
    this.sm.registerClippable(m);
    return m;
  }

  build(glasses, frame, head) {
    this.root.clear();
    const g = (id, label) => {
      const grp = new THREE.Group();
      grp.userData.componentId = id;
      grp.userData.label = label;
      this.root.add(grp);
      this.groups[id] = grp;
      return grp;
    };
    const frameMat = this.mat({ color: FRAME_COLOR, roughness: 0.55, metalness: 0.2 });
    const lensMat = this.mat({ color: 0xcfe3ff, transparent: true, opacity: 0.16, roughness: 0.05, metalness: 0, depthWrite: false, side: THREE.DoubleSide });

    // ---- rims + lenses
    const frameGrp = g('frame', 'Front frame');
    for (const side of [1, -1]) {
      const c = side === 1 ? glasses.rightLensCenter : glasses.leftLensCenter;
      const lf = side === 1 ? glasses.lenses.R : glasses.lenses.L;
      // the outline is defined for the right lens seen from the front; the
      // left lens is its mirror image
      const outlineL = side === 1 ? glasses.outline : glasses.outline.map(([x, y]) => [-x, y]).reverse();
      const outer = offsetPolygon(outlineL, frame.rimWidth);
      const shape = shapeFrom(outer);
      shape.holes.push(new THREE.Path(outlineL.slice().reverse().map(([x, y]) => new THREE.Vector2(x, y))));
      const rim = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: frame.rimDepth, bevelEnabled: false, curveSegments: 6 }), frameMat);
      const rimHolder = new THREE.Group();
      rimHolder.position.copy(c); rimHolder.quaternion.copy(lf.quaternion);
      rim.position.set(0, 0, -frame.rimDepth / 2);
      rimHolder.add(rim);
      frameGrp.add(rimHolder);
      // endpiece to hinge
      const sx = Math.sign(c.x);
      const ex0 = sx * (Math.abs(c.x) + frame.lensWidth / 2 + frame.rimWidth / 2);
      const ex1 = sx * glasses.hingeX;
      const end = new THREE.Mesh(new THREE.BoxGeometry(Math.abs(ex1 - ex0) + 2, 8, frame.rimDepth), frameMat);
      end.position.set((ex0 + ex1) / 2, glasses.hingeY, -frame.rimDepth / 2 - 0.5);
      frameGrp.add(end);

      const lensGrp = g(side === 1 ? 'lensR' : 'lensL', side === 1 ? 'Right lens' : 'Left lens');
      const lens = new THREE.Mesh(new THREE.ExtrudeGeometry(shapeFrom(outlineL), { depth: frame.lensThickness, bevelEnabled: false }), lensMat);
      const lensHolder = new THREE.Group();
      lensHolder.position.copy(c); lensHolder.quaternion.copy(lf.quaternion);
      lens.position.set(0, 0, -frame.lensThickness / 2);
      lens.renderOrder = 2;
      lensHolder.add(lens);
      lensGrp.add(lensHolder);
      const edge = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(outlineL.map(([x, y]) => lf.toWorld(x, y, -frame.lensThickness / 2 - 0.02))),
        new THREE.LineBasicMaterial({ color: 0x7fa6d9, transparent: true, opacity: 0.6 }));
      lensGrp.add(edge);
      lensGrp.visible = frame.lensesPresent;
    }
    // bridge
    const bridgeCurve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(-frame.bridge / 2 - 1, frame.lensHeight / 2 - 6, 0),
      new THREE.Vector3(0, frame.lensHeight / 2 + 2, 1.5),
      new THREE.Vector3(frame.bridge / 2 + 1, frame.lensHeight / 2 - 6, 0));
    frameGrp.add(new THREE.Mesh(new THREE.TubeGeometry(bridgeCurve, 16, 1.6, 8), frameMat));
    // nose pads
    for (const s of [1, -1]) {
      const pad = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 8), this.mat({ color: 0x9aa6b8, transparent: true, opacity: 0.7 }));
      pad.scale.set(1.6, 4, 0.8);
      pad.position.set(s * (frame.bridge / 2 + 1.5), -4, -4);
      frameGrp.add(pad);
    }

    // ---- hinges + temples
    for (const t of glasses.temples) {
      const hg = g(t.side === 1 ? 'hingeR' : 'hingeL', t.side === 1 ? 'Right hinge' : 'Left hinge');
      const hinge = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.4, frame.templeHeight + 2, 16), this.mat({ color: 0x8f99a8, metalness: 0.8, roughness: 0.3 }));
      hinge.position.copy(t.start);
      hg.add(hinge);
      const tg = g(t.side === 1 ? 'templeR' : 'templeL', t.side === 1 ? 'Right temple' : 'Left temple');
      const arm = new THREE.Mesh(new THREE.BoxGeometry(t.size.x, t.size.y, t.size.z), frameMat);
      arm.position.copy(t.center);
      arm.quaternion.copy(t.quaternion);
      tg.add(arm);
      // ear bend
      const tip = new THREE.Mesh(new THREE.BoxGeometry(t.size.x * 0.9, t.size.y * 0.9, 30), frameMat);
      const endPt = t.start.clone().addScaledVector(t.dir, t.size.z);
      tip.position.set(endPt.x, endPt.y - 10, endPt.z - 10);
      tip.rotation.x = -0.75;
      tg.add(tip);
    }
    // ---- housing + internal cavity
    const hgp = g('housing', 'Right-temple display housing');
    const h = glasses.housing;
    const shell = new THREE.Mesh(new THREE.BoxGeometry(h.size.x, h.size.y, h.size.z),
      this.mat({ color: 0x3b4352, transparent: true, opacity: 0.22, roughness: 0.6, depthWrite: false }));
    shell.position.copy(h.center);
    hgp.add(shell);
    const shellEdges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(h.size.x, h.size.y, h.size.z)), new THREE.LineBasicMaterial({ color: 0x6d7a90 }));
    shellEdges.position.copy(h.center);
    hgp.add(shellEdges);
    const cav = glasses.cavity;
    const cavLines = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(cav.size.x, cav.size.y, cav.size.z)),
      new THREE.LineDashedMaterial({ color: 0x5fb3ff, dashSize: 1.5, gapSize: 1 }));
    cavLines.computeLineDistances();
    cavLines.position.copy(cav.center);
    hgp.add(cavLines);
    const lab = makeLabel('Internal space (temple cavity)', 'muted');
    lab.position.set(cav.center.x, cav.max.y + 2, cav.min.z + 6);
    hgp.add(lab);

    // ---- side of the head beside the right temple (from your measurements)
    if (head) {
      const hg2 = g('head', 'Head (temple area)');
      const pts = [], idx = [];
      const zs = [head.zRim, head.zRim - 10, head.zRim - 25, head.zRim - 45, head.zRim - 65];
      for (const z of zs) for (const y of [glasses.hingeY - 18, glasses.hingeY + 14]) pts.push(head.skinX(z), y, z);
      for (let i = 0; i < zs.length - 1; i++) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
      // the orbital rim face, from the rim to the temple skin
      const base = pts.length / 3;
      pts.push(head.rimX, glasses.hingeY - 18, head.zRim, head.rimX, glasses.hingeY + 14, head.zRim);
      idx.push(0, 1, base, 1, base + 1, base);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      geo.setIndex(idx); geo.computeVertexNormals();
      hg2.add(new THREE.Mesh(geo, this.mat({ color: 0xd9a58a, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false })));
      const lab2 = makeLabel('Your head: orbital rim + temple (measurements)', 'muted');
      lab2.position.set(head.skinX(zs[2]), glasses.hingeY + 16, zs[2]);
      hg2.add(lab2);
    }

    this.glasses = glasses;
    this.frame = frame;
    for (const grp of Object.values(this.groups)) this.sm.pickables.push(grp);
  }

  updateOverlay(coverage, glasses, show) {
    this.overlay.clear();
    this.overlay.visible = show;
    if (!coverage) return;
    // overlay lives in the right lens's own (tilted/wrapped) frame
    const lf = glasses.lenses.R;
    const holder = new THREE.Group();
    holder.position.copy(lf.center); holder.quaternion.copy(lf.quaternion);
    this.overlay.add(holder);
    const z = -this.frame.lensThickness / 2 - 0.08;
    const L = coverage.lens;
    const fillPoly = (poly, color, opacity, dz = 0) => {
      if (poly.length < 3) return;
      const m = new THREE.Mesh(new THREE.ShapeGeometry(shapeFrom(poly)),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false }));
      m.position.set(0, 0, z + dz);
      m.renderOrder = 5;
      holder.add(m);
    };
    const outline = (poly, color, dashed = false, dz = 0) => {
      if (poly.length < 2) return;
      const geo = new THREE.BufferGeometry().setFromPoints(poly.map(([x, y]) => new THREE.Vector3(x, y, z + dz)));
      const mat = dashed ? new THREE.LineDashedMaterial({ color, dashSize: 1.2, gapSize: 0.8 }) : new THREE.LineBasicMaterial({ color });
      const line = new THREE.LineLoop(geo, mat);
      if (dashed) line.computeLineDistances();
      line.renderOrder = 6;
      holder.add(line);
    };
    fillPoly(L.inside, 0x32d27a, 0.38);
    outline(L.footprint, L.outsidePct > 1 ? 0xff5a4f : 0x32d27a);
    outline(L.targetHull, 0xf2c94c, true, -0.01);
    if (L.physicalFootprint.length >= 3) outline(L.physicalFootprint, 0x5fb3ff, false, -0.02);
    if (L.strayHits.length) {
      const pts = new THREE.Points(new THREE.BufferGeometry().setFromPoints(L.strayHits.map(([x, y]) => new THREE.Vector3(x, y, z + 0.03))),
        new THREE.PointsMaterial({ color: 0xff9f43, size: 2.2, sizeAttenuation: false }));
      holder.add(pts);
    }
    const lab = makeLabel(`HUD footprint ${L.coveragePct.toFixed(1)}% of lens`, 'good');
    const cx = L.inside.length ? L.inside.reduce((s, p) => s + p[0], 0) / L.inside.length : 0;
    const cy = L.inside.length ? L.inside.reduce((s, p) => s + p[1], 0) / L.inside.length : 0;
    lab.position.set(cx, cy + 4, z);
    holder.add(lab);
  }
}

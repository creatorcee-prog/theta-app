// Meshes and drag handles for the generic hardware parts (battery, charger,
// compute board, IMU, brackets, custom parts). Geometry from model/parts.js.

import * as THREE from 'three';
import { makeLabel } from './labels.js';

export class PartsModel {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.root = new THREE.Group();
    sceneManager.scene.add(this.root);
    this.groups = {};
    this.handles = {};
  }

  update(system, { labels = true } = {}) {
    this.root.clear();
    this.groups = {};
    this.comGroup = null;
    const seen = new Set();
    for (const pf of system.parts ?? []) {
      const id = `part:${pf.part.id}`;
      seen.add(id);
      const g = new THREE.Group();
      g.userData.componentId = id;
      g.userData.label = pf.part.name;
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(pf.size.x, pf.size.y, pf.size.z),
        new THREE.MeshStandardMaterial({ color: new THREE.Color(pf.part.color || '#666'), roughness: 0.6, metalness: 0.15 }));
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: 0xc9d3e0, transparent: true, opacity: 0.5 }));
      for (const o of [mesh, edges]) { o.position.copy(pf.position); o.quaternion.copy(pf.quaternion); g.add(o); }
      if (labels) {
        const l = makeLabel(pf.part.name.replace(/ \(.*\)$/, ''), 'muted');
        l.position.copy(pf.position).add(new THREE.Vector3(0, pf.size.y / 2 + 3, 0));
        g.add(l);
      }
      g.visible = pf.part.visible !== false;
      this.root.add(g);
      this.groups[id] = g;
      this.sm.pickables.push(g);
      let h = this.handles[id];
      if (!h) {
        h = new THREE.Object3D();
        h.userData.componentId = id;
        this.sm.scene.add(h);
        this.handles[id] = h;
      }
      h.position.copy(pf.position);
      h.quaternion.copy(pf.quaternion);
    }
    for (const id of Object.keys(this.handles)) if (!seen.has(id)) { this.sm.scene.remove(this.handles[id]); delete this.handles[id]; }
  }

  setCentreOfMass(com, gramsTotal) {
    if (this.comGroup) { this.comGroup.traverse((o) => o.isCSS2DObject && o.element?.remove()); this.comGroup.parent?.remove(this.comGroup); }
    if (!com) return;
    const g = new THREE.Group();
    g.userData.componentId = 'com';
    const s = new THREE.Mesh(new THREE.SphereGeometry(1.6, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffb000 }));
    s.position.set(com.x, com.y, com.z);
    g.add(s);
    const l = makeLabel(`Centre of mass · ${gramsTotal.toFixed(1)} g`, 'accent');
    l.position.set(com.x, com.y + 5, com.z);
    g.add(l);
    this.root.add(g);
    this.comGroup = g;
    this.groups.com = g;
  }
}

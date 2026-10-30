// Eye meshes: eyeball, iris with pupil aperture, cornea, entrance-pupil
// ring (the aperture the tracer tests against) and viewing direction.
// Geometry comes from model/eye.js.

import * as THREE from 'three';
import { makeLabel } from './labels.js';

export class EyeModel {
  constructor(sceneManager, id, label) {
    this.sm = sceneManager;
    this.group = new THREE.Group();
    this.group.userData.componentId = id;
    this.group.userData.label = label;
    sceneManager.scene.add(this.group);
    sceneManager.pickables.push(this.group);
    this.id = id;
    // handle object for the drag gizmo (sits at the corneal vertex)
    this.handle = new THREE.Object3D();
    this.handle.userData.componentId = id;
    sceneManager.scene.add(this.handle);
  }

  update(eye, { showLabel = true } = {}) {
    const g = this.group;
    g.clear();
    const mat = (p) => { const m = new THREE.MeshStandardMaterial(p); this.sm.registerClippable(m); return m; };
    const ball = new THREE.Mesh(new THREE.SphereGeometry(eye.eyeballRadius, 40, 28), mat({ color: 0xf1ece6, roughness: 0.5 }));
    ball.position.copy(eye.rotationCenter);
    g.add(ball);

    const q = eye.quaternion;
    const fwd = eye.gaze;
    // iris at the real pupil plane (~3.6 mm behind vertex), radius 6 mm
    const irisPlane = eye.pupilCenter.clone().addScaledVector(fwd, -0.55);
    const iris = new THREE.Mesh(new THREE.RingGeometry(eye.pupilRadius / 1.13, 6, 48), mat({ color: 0x4a6b8a, roughness: 0.7, side: THREE.DoubleSide }));
    iris.position.copy(irisPlane);
    iris.quaternion.copy(q);
    g.add(iris);
    const pupil = new THREE.Mesh(new THREE.CircleGeometry(eye.pupilRadius / 1.13, 32), mat({ color: 0x050505, side: THREE.DoubleSide }));
    pupil.position.copy(irisPlane).addScaledVector(fwd, -0.05);
    pupil.quaternion.copy(q);
    g.add(pupil);

    // cornea cap
    const capAngle = Math.asin(Math.min(1, 6 / eye.corneaRadius));
    const corneaGeo = new THREE.SphereGeometry(eye.corneaRadius, 40, 16, 0, Math.PI * 2, 0, capAngle);
    corneaGeo.rotateX(Math.PI / 2); // cap points along +z
    const cornea = new THREE.Mesh(corneaGeo, mat({ color: 0xd8f0ff, transparent: true, opacity: 0.25, roughness: 0.02, depthWrite: false }));
    cornea.position.copy(eye.corneaCenter);
    cornea.quaternion.copy(q);
    g.add(cornea);

    // entrance pupil ring = the traced aperture
    const ep = new THREE.Mesh(new THREE.RingGeometry(eye.pupilRadius - 0.12, eye.pupilRadius, 48), new THREE.MeshBasicMaterial({ color: 0x32d27a, side: THREE.DoubleSide }));
    ep.position.copy(eye.pupilCenter);
    ep.quaternion.copy(q);
    g.add(ep);

    // viewing direction
    const arrow = new THREE.ArrowHelper(fwd, eye.corneaVertex, 34, 0x8fb7ff, 3, 1.4);
    arrow.line.material.transparent = true; arrow.line.material.opacity = 0.7;
    g.add(arrow);

    if (showLabel) {
      const lab = makeLabel(eye.side === 1 ? 'Right pupil' : 'Left eye', eye.side === 1 ? 'good' : 'muted');
      lab.position.copy(eye.corneaVertex).add(new THREE.Vector3(0, -9, 0));
      g.add(lab);
    }
    this.handle.position.copy(eye.corneaVertex);
  }
}

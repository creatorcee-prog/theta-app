// 3D rendering, cameras, controls, camera presets, picking and drag gizmo.
// Reads geometry/results; never computes optics.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';

export class SceneManager {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.localClippingEnabled = true;
    this.renderer.setClearColor(0x0d1117, 1);
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.classList.add('viewport-canvas');

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = 'label-layer';
    container.appendChild(this.labelRenderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.3, 4000);
    this.camera.position.set(-150, 95, 150);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.target.set(-30, 0, -25);
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 2;
    this.controls.maxDistance = 900;
    this.controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };

    this.gizmo = new TransformControls(this.camera, this.renderer.domElement);
    this.gizmo.setSize(0.7);
    this.gizmo.addEventListener('dragging-changed', (e) => {
      this.controls.enabled = !e.value;
      this.onGizmoDrag?.(e.value ? 'start' : 'end');
    });
    this.gizmo.addEventListener('objectChange', () => this.onGizmoChange?.(this.gizmo.object));
    this.scene.add(this.gizmo);

    // lights
    this.scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x20242c, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(120, 200, 160);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x9fc4ff, 0.6);
    rim.position.set(-150, 60, -120);
    this.scene.add(rim);

    // 10 mm engineering grid under the frame
    const grid = new THREE.GridHelper(400, 40, 0x2c3a4d, 0x1b2430);
    grid.position.set(0, -40, -60);
    this.scene.add(grid);
    this.grid = grid;
    const axes = new THREE.AxesHelper(15);
    axes.position.set(100, -39.9, 40);
    this.scene.add(axes);

    // cross-section clipping plane (applied per material)
    this.sectionPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    this.sectionOn = false;
    this.clippable = [];

    this.pickables = [];
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._down = null;
    const el = this.renderer.domElement;
    let hoverT = 0;
    el.addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'mouse' || e.buttons || performance.now() - hoverT < 60) return;
      hoverT = performance.now();
      const id = this.idAt(e);
      if (id !== this.hovered) { this.hovered = id; this.onHover?.(id); }
    });
    el.addEventListener('pointerleave', () => { if (this.hovered) { this.hovered = null; this.onHover?.(null); } });
    el.addEventListener('pointerdown', (e) => { this._down = { x: e.clientX, y: e.clientY, t: performance.now() }; });
    el.addEventListener('pointerup', (e) => {
      if (!this._down || this.gizmo.dragging) return;
      const moved = Math.hypot(e.clientX - this._down.x, e.clientY - this._down.y);
      if (moved < 6 && performance.now() - this._down.t < 500) this.pick(e);
      this._down = null;
    });

    this.tween = null;
    this.clock = new THREE.Clock();
    this.onFrame = null;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.labelRenderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  registerClippable(material) {
    this.clippable.push(material);
    material.clippingPlanes = this.sectionOn ? [this.sectionPlane] : null;
  }

  clearClippable() { this.clippable = []; }

  setSection(on, plane) {
    this.sectionOn = on;
    if (plane) this.sectionPlane.copy(plane);
    for (const m of this.clippable) { m.clippingPlanes = on ? [this.sectionPlane] : null; m.needsUpdate = true; }
  }

  // component under the pointer (null if none), for hover labels
  idAt(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.pickables.filter((o) => isVisible(o)), true);
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.componentId) o = o.parent;
      if (o && o.userData.componentId !== 'rays' && o.userData.componentId !== 'coverage') return o.userData.componentId;
    }
    return null;
  }

  pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const visible = this.pickables.filter((o) => isVisible(o));
    const hits = this.raycaster.intersectObjects(visible, true);
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.componentId) o = o.parent;
      if (o) { this.onPick?.(o.userData.componentId, o); return; }
    }
    this.onPick?.(null, null);
  }

  attachGizmo(object, mode = 'translate') {
    if (!object) { this.gizmo.detach(); return; }
    this.gizmo.setMode(mode);
    this.gizmo.attach(object);
  }

  flyTo(position, target, { fov = 40, duration = 650, near = 0.3 } = {}) {
    const from = { p: this.camera.position.clone(), t: this.controls.target.clone(), fov: this.camera.fov };
    this.camera.near = near;
    this.tween = { from, to: { p: position.clone(), t: target.clone(), fov }, start: performance.now(), duration };
  }

  frame() {
    const dt = this.clock.getDelta();
    if (this.tween) {
      const { from, to, start, duration } = this.tween;
      let k = Math.min(1, (performance.now() - start) / duration);
      const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
      this.camera.position.lerpVectors(from.p, to.p, e);
      this.controls.target.lerpVectors(from.t, to.t, e);
      this.camera.fov = from.fov + (to.fov - from.fov) * e;
      this.camera.updateProjectionMatrix();
      if (k >= 1) this.tween = null;
    }
    this.controls.update();
    this.onFrame?.(dt);
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}

function isVisible(o) {
  while (o) { if (!o.visible) return false; o = o.parent; }
  return true;
}

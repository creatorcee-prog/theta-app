// App bootstrap: owns the parameter state, runs optics -> analysis ->
// diagnostics, then hands the results to the renderers and UI.

import * as THREE from 'three';
import { defaultParams, alignChain } from './config/defaults.js';
import { runSimulation } from './optics/Simulation.js';
import { analyzeCoverage } from './optics/CoverageAnalyzer.js';
import { runDiagnostics } from './optics/Diagnostics.js';
import { computeCollimator, computeOled, eulerDegFromBasis } from './optics/OpticalComponents.js';
import { SceneManager } from './render/SceneManager.js';
import { GlassesModel } from './render/GlassesModel.js';
import { EyeModel } from './render/EyeModel.js';
import { OpticalMeshes } from './render/OpticalMeshes.js';
import { RayRenderer } from './render/RayRenderer.js';
import { FirstPersonView } from './render/FirstPersonView.js';
import { UIController, setPath } from './ui/UIController.js';
import { NOTES_HTML } from './ui/notes.js';

const $ = (s) => document.querySelector(s);

let params = defaultParams();
let results = null, coverage = null, diag = null;
let dirty = true, lastRun = 0, dragging = false;
let selected = null;
let currentPreset = 'full';
const visibility = {};

const sm = new SceneManager($('#viewport'));
const glassesModel = new GlassesModel(sm);
const eyeR = new EyeModel(sm, 'eyeR', 'Right eye');
const eyeL = new EyeModel(sm, 'eyeL', 'Left eye');
const optics = new OpticalMeshes(sm);
const rays = new RayRenderer(sm);
const fpv = new FirstPersonView($('#fpv-canvas'));

const ui = new UIController({
  controlsEl: $('#controls'), resultsEl: $('#results'), notesEl: $('#notes'), selectionEl: $('#selection'),
  visibilityEl: $('#visibility'), legendEl: $('#legend'), metricsEl: $('#metrics'),
}, {
  getParams: () => params,
  onChange: (key, value) => { setPath(params, key, value); schedule(); if (key.startsWith('collimator.mode') || key === 'collimator.enabled') ui.refresh(); },
  onAction: (a) => action(a),
  onVisibility: (id, on) => { visibility[id] = on; applyVisibility(); },
  onRayFilter: (k, on) => { rays.filters[k] = on; drawRays(); },
  onSelect: (id) => select(id),
  onGizmoMode: (id, mode) => sm.attachGizmo(handleFor(id), mode),
});
ui.renderNotes(NOTES_HTML);

function schedule() { dirty = true; }

function disposeTree(obj) {
  obj.traverse((o) => {
    o.geometry?.dispose?.();
    // material.dispose() leaves textures alone, so the shared HUD texture survives
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m !== rays.material) m.dispose(); });
  });
}

function run() {
  const t0 = performance.now();
  try {
    results = runSimulation(params);
    coverage = analyzeCoverage(results);
    diag = runDiagnostics(results, coverage);
  } catch (err) {
    console.error(err);
    $('#status').textContent = `Simulation error: ${err.message}`;
    return;
  }
  // rebuild meshes from the same geometry the tracer used
  sm.clearClippable();
  for (const g of [glassesModel.root, glassesModel.overlay, eyeR.group, eyeL.group, ...Object.values(optics.groups)]) disposeTree(g);
  glassesModel.build(results.system.glasses, params.frame);
  glassesModel.updateOverlay(coverage, results.system.glasses, visibility.coverage !== false);
  eyeR.update(results.system.eye);
  eyeL.update(results.system.leftEye);
  optics.update(results.system, params);
  sm.pickables = [...new Set(sm.pickables.filter((o) => o.parent))];
  sm.setSection(sm.sectionOn);
  drawRays();
  fpv.set(results, coverage, diag);
  ui.renderMetrics(results, coverage, diag);
  if (!dragging) ui.renderResults(results, coverage, diag);
  ui.refresh();
  applyVisibility();
  $('#status').textContent = `${results.counts.emitted} rays traced in ${(performance.now() - t0).toFixed(0)} ms`;
}

function drawRays() {
  rays.update(results, { maxPaths: params.sim.drawRays, brightness: params.oled.brightness / 100 });
  rays.group.visible = visibility.rays !== false;
}

function applyVisibility() {
  const map = {
    ...glassesModel.groups, eyeR: eyeR.group, eyeL: eyeL.group, ...optics.groups,
    rays: rays.group, coverage: glassesModel.overlay, grid: sm.grid,
  };
  for (const [id, obj] of Object.entries(map)) if (obj) obj.visible = visibility[id] !== false && !(id === 'eyeR' && currentPreset === 'eye');
  sm.labelRenderer.domElement.style.display = visibility.labels === false ? 'none' : '';
}

// ------------------------------------------------------------ selection + gizmo
function handleFor(id) {
  if (id === 'eyeR') return eyeR.handle;
  return optics.handles[id] ?? null;
}

function select(id) {
  selected = id;
  ui.showSelection(id);
  if (!id) sm.attachGizmo(null);
  else if (!handleFor(id)) sm.attachGizmo(null);
}

sm.onPick = (id) => {
  if (id === 'rays' || id === 'coverage') return;
  select(id);
  if (id && handleFor(id)) sm.attachGizmo(handleFor(id), 'translate');
};
sm.onGizmoDrag = (phase) => {
  dragging = phase === 'start';
  if (!dragging) { schedule(); }
};
sm.onGizmoChange = (h) => {
  const id = h.userData.componentId;
  const r3 = (x) => Math.round(x * 100) / 100;
  if (id === 'oled' || id === 'prism') {
    params[id].pos = { x: r3(h.position.x), y: r3(h.position.y), z: r3(h.position.z) };
    const x = new THREE.Vector3(1, 0, 0).applyQuaternion(h.quaternion);
    const y = new THREE.Vector3(0, 1, 0).applyQuaternion(h.quaternion);
    const z = new THREE.Vector3(0, 0, 1).applyQuaternion(h.quaternion);
    params[id].rot = eulerDegFromBasis(x, y, z);
  } else if (id === 'collimator') {
    const oled = computeOled(params.oled);
    const d = h.position.clone().sub(oled.center);
    params.collimator.distance = r3(Math.max(0.5, d.dot(oled.normal)));
    params.collimator.offsetX = r3(d.dot(oled.xAxis));
    params.collimator.offsetY = r3(d.dot(oled.yAxis));
  } else if (id === 'eyeR') {
    const sys = results.system;
    const C = h.position.clone().addScaledVector(sys.eye.gaze, -13.5);
    params.eye.dx = r3(C.x + params.eye.ipd / 2);
    params.eye.dy = r3(C.y);
    params.eye.eyeRelief = r3(Math.max(4, sys.glasses.lensBackZ - (C.z + 13.5)));
  } else if (id === 'driver') {
    params.driver.pos = { x: r3(h.position.x), y: r3(h.position.y), z: r3(h.position.z) };
  }
  schedule();
};

// ------------------------------------------------------------ actions
function action(a) {
  if (a === 'refocus') {
    const oled = computeOled(params.oled);
    const c = computeCollimator({ ...params.collimator, enabled: true }, oled, params.prism.n);
    if (c?.valid) params.collimator.distance = Math.round(c.frontFocalDistance * 1000) / 1000;
  } else if (a === 'align') {
    params.intent.azimuth = params.targets.azimuth;
    params.intent.elevation = params.targets.elevation;
    params = alignChain(params);
    action('refocus');
  } else if (a === 'lookAtHud' && coverage?.field.hCenter != null) {
    params.eye.gazeYaw = Math.round(coverage.field.hCenter * 2) / 2;
    params.eye.gazePitch = Math.round(coverage.field.vCenter * 2) / 2;
  } else if (a === 'lookAhead') {
    params.eye.gazeYaw = 0; params.eye.gazePitch = 0;
  } else if (a === 'reset') {
    params = defaultParams();
    select(null);
    preset('full');
  }
  ui.refresh();
  schedule();
}

// ------------------------------------------------------------ camera presets
function preset(name) {
  currentPreset = name;
  document.querySelectorAll('[data-preset]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.preset === name)));
  const sys = results?.system;
  sm.setSection(false);
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  const optCenter = sys ? sys.prism.center.clone().lerp(sys.oled.center, 0.5) : V(45, 0, -10);
  if (name === 'full') sm.flyTo(V(-125, 80, 105), V(-22, -4, -32));
  else if (name === 'side') sm.flyTo(V(-240, 12, -25), V(-40, 0, -30));
  else if (name === 'top') sm.flyTo(V(-35, 230, -28), V(-35, 0, -30));
  else if (name === 'front') sm.flyTo(V(0, 4, 230), V(0, 0, -20));
  else if (name === 'section' && sys) {
    const w = sys.prism.w.clone();
    const toCam = w.dot(V(0, 1, 0)) >= 0 ? w : w.clone().negate();
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(toCam.clone().negate(), sys.prism.center.clone().addScaledVector(toCam, 0.5));
    sm.setSection(true, plane);
    sm.flyTo(optCenter.clone().addScaledVector(toCam, 75), optCenter, { fov: 35 });
  } else if (name === 'eye' && sys) {
    const e = sys.eye;
    sm.flyTo(e.pupilCenter.clone().addScaledVector(e.gaze, 0.6), e.pupilCenter.clone().addScaledVector(e.gaze, 40), { fov: 95, near: 0.1 });
  }
  applyVisibility();
}
document.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => preset(b.dataset.preset)));

// ------------------------------------------------------------ toolbar
const playBtn = $('#play');
playBtn.addEventListener('click', () => {
  rays.setPaused(!rays.paused);
  playBtn.textContent = rays.paused ? 'Resume light' : 'Pause light';
  playBtn.setAttribute('aria-pressed', String(rays.paused));
});
$('#reset').addEventListener('click', () => action('reset'));
document.querySelectorAll('[data-fpv]').forEach((b) => b.addEventListener('click', () => {
  fpv.mode = b.dataset.fpv;
  document.querySelectorAll('[data-fpv]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  fpv.draw();
}));
$('#fpv-flip').addEventListener('change', (e) => { fpv.driverFlip = e.target.checked; fpv.draw(); });
$('#fpv-expand').addEventListener('click', () => {
  const pip = $('#fpv');
  const on = pip.classList.toggle('expanded');
  $('#fpv-expand').textContent = on ? 'Shrink' : 'Expand';
  requestAnimationFrame(() => fpv.draw());
});
$('#fpv-hide').addEventListener('click', () => { $('#fpv').hidden = true; $('#fpv-show').hidden = false; });
$('#fpv-show').addEventListener('click', () => { $('#fpv').hidden = false; $('#fpv-show').hidden = true; requestAnimationFrame(() => fpv.draw()); });

// tabs
document.querySelectorAll('[role=tab]').forEach((t) => t.addEventListener('click', () => {
  document.querySelectorAll('[role=tab]').forEach((x) => x.setAttribute('aria-selected', String(x === t)));
  document.querySelectorAll('[role=tabpanel]').forEach((p) => { p.hidden = p.id !== t.getAttribute('aria-controls'); });
  if (t.getAttribute('aria-controls') === 'tab-results' && results) ui.renderResults(results, coverage, diag);
}));

window.addEventListener('keydown', (e) => {
  if (e.target.closest('input,select,textarea')) return;
  if (e.key === ' ') { e.preventDefault(); playBtn.click(); }
  if (e.key === 'Escape') select(null);
});

// ------------------------------------------------------------ loop
sm.onFrame = (dt) => {
  rays.tick(dt);
  const now = performance.now();
  if (dirty && now - lastRun > (dragging ? 60 : 25)) {
    dirty = false; lastRun = now;
    run();
  }
};

run();
preset('full');

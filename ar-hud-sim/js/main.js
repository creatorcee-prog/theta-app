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
import { setImageReadyHandler } from './render/hudContent.js';
import { PartsModel } from './render/PartsModel.js';
import { computeHead } from './model/head.js';
import { MAKES, TUNED, tunedParams, applyPrintedCosts } from './config/makes.js';
import { scoreDesign } from './optics/Scorecard.js';
import { mapReach } from './optics/reach.js';
import { partFrame, hostFrameInverse } from './model/parts.js';
import { solveFocusDistance, solveFieldFocus } from './optics/focus.js';
import { assessFocus } from './optics/Vision.js';
import { applyLabelMode } from './render/labels.js';

const $ = (s) => document.querySelector(s);

let params = defaultParams();
let results = null, coverage = null, diag = null;
let dirty = true, lastRun = 0, dragging = false;
let selected = null;
let currentPreset = 'full';
const visibility = {};
// labels: 'focus' shows only the hovered / selected part's label so labels never cover the model
let labelMode = 'focus', hovered = null;

const sm = new SceneManager($('#viewport'));
const glassesModel = new GlassesModel(sm);
const eyeR = new EyeModel(sm, 'eyeR', 'Right eye');
const eyeL = new EyeModel(sm, 'eyeL', 'Left eye');
const optics = new OpticalMeshes(sm);
const rays = new RayRenderer(sm);
const partsModel = new PartsModel(sm);
const housingHandle = new THREE.Object3D();
housingHandle.userData.componentId = 'housing';
sm.scene.add(housingHandle);
const fpv = new FirstPersonView($('#fpv-canvas'));

const ui = new UIController({
  controlsEl: $('#controls'), resultsEl: $('#results'), notesEl: $('#notes'), selectionEl: $('#selection'),
  visibilityEl: $('#visibility'), legendEl: $('#legend'), metricsEl: $('#metrics'),
}, {
  getParams: () => params,
  getScore: () => score,
  onChange: (key, value) => {
    setPath(params, key, value);
    // display content and animation speed do not change the optics: redraw only
    if (key.startsWith('hud.') || key === 'sim.raySpeed') { redrawContent(); ui.refresh(); return; }
    schedule();
    if (key.startsWith('collimator.mode') || key === 'collimator.enabled' || key === 'sim.ghosts') ui.refresh();
  },
  onAction: (a) => action(a),
  onVisibility: (id, on) => { visibility[id] = on; applyVisibility(); },
  onRayFilter: (k, on) => { rays.filters[k] = on; drawRays(); },
  onSelect: (id) => select(id),
  onBomChange: (id, key, value) => {
    const b = params.bom.find((x) => x.id === id);
    if (!b) return;
    b[key] = key === 'qty' ? Math.max(0, Math.round(value)) : (key === 'unit' || key === 'weight') ? Math.max(0, value) : value;
    if (key === 'weight' && b.weightBasis === 'calc') b.autoWeight = false; // typed value overrides geometry
    ui.renderParts(params, results); ui.renderMetrics(results, coverage, diag);
    schedule();
  },
  onPartChange: (id, key, value) => {
    const part = params.parts.find((x) => x.id === id);
    if (!part) return;
    if (key === 'attach') {
      // keep the part where it is in the world when changing what it is attached to
      const before = partFrame(part, results.system);
      part.attach = value;
      const host = partFrame(part, results.system).host;
      let pos = before.position.clone(), q = before.quaternion.clone();
      if (host) { pos = hostFrameInverse(host)(pos); q = host.quaternion.clone().invert().multiply(q); }
      part.pos = { x: +pos.x.toFixed(2), y: +pos.y.toFixed(2), z: +pos.z.toFixed(2) };
      part.rot = eulerFromQuat(q);
    } else if (key.startsWith('size.')) setPath(part, key, Math.max(0.2, value));
    else setPath(part, key, value);
    if (key === 'name') { const b = params.bom.find((x) => x.part === id); if (b) b.name = value; }
    schedule();
  },
  onGizmoMode: (id, mode) => sm.attachGizmo(handleFor(id), mode),
});
ui.renderNotes(NOTES_HTML);
ui.bindParts($('#parts'));
ui.bindMakes($('#makes'));
let score = null;
setImageReadyHandler(() => redrawContent());

function schedule() { dirty = true; }

function redrawContent() {
  rays.speed = params.sim.raySpeed;
  $('#fpv-flip').checked = !!params.hud.driverFlip;
  if (!results) return;
  for (const g of Object.values(optics.groups)) disposeTree(g);
  optics.update(results.system, params);
  applyVisibility();
  fpv.draw();
}

function disposeTree(obj) {
  obj.traverse((o) => {
    // three.js only detaches a CSS2D label's element when the label itself is
    // removed, not when an ancestor group is cleared: do it here
    if (o.isCSS2DObject) o.element?.remove();
    o.geometry?.dispose?.();
    // material.dispose() leaves textures alone, so the shared HUD texture survives
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m !== rays.material) m.dispose(); });
  });
}

function run() {
  const t0 = performance.now();
  try {
    results = runSimulation(params);
    applyPrintedCosts(params);
    coverage = analyzeCoverage(results);
    diag = runDiagnostics(results, coverage);
    score = scoreDesign(results, coverage, diag, params);
  } catch (err) {
    console.error(err);
    $('#status').textContent = `Simulation error: ${err.message}`;
    return;
  }
  // rebuild meshes from the same geometry the tracer used
  sm.clearClippable();
  for (const g of [glassesModel.root, glassesModel.overlay, eyeR.group, eyeL.group, partsModel.root, ...Object.values(optics.groups)]) disposeTree(g);
  glassesModel.build(results.system.glasses, params.frame, computeHead(params, results.system.glasses, results.system.eye));
  partsModel.update(results.system);
  partsModel.setCentreOfMass(results.weights?.com, results.weights?.grams ?? 0);
  housingHandle.position.copy(results.system.glasses.housing.center);
  glassesModel.updateOverlay(coverage, results.system.glasses, visibility.coverage !== false);
  eyeR.update(results.system.eye);
  eyeL.update(results.system.leftEye);
  optics.update(results.system, params);
  sm.pickables = [...new Set(sm.pickables.filter((o) => o.parent))];
  sm.setSection(sm.sectionOn);
  drawRays();
  fpv.set(results, coverage, diag);
  ui.renderMetrics(results, coverage, diag);
  if (!dragging) { ui.renderResults(results, coverage, diag); ui.renderParts(params, results); ui.renderMakes(MAKES, TUNED, score, params.make?.id); }
  ui.refresh();
  $('#fpv-flip').checked = !!params.hud.driverFlip;
  rays.speed = params.sim.raySpeed;
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
    rays: rays.group, coverage: glassesModel.overlay, grid: sm.grid, ...partsModel.groups,
  };
  for (const [id, obj] of Object.entries(map)) if (obj) obj.visible = visibility[id] !== false && !(id === 'eyeR' && currentPreset === 'eye');
  sm.labelRenderer.domElement.style.display = visibility.labels === false ? 'none' : '';
  updateLabels();
}

function updateLabels() {
  applyLabelMode(sm.scene, labelMode, [selected, hovered].filter(Boolean));
}
sm.onHover = (id) => { hovered = id; updateLabels(); sm.renderer.domElement.style.cursor = id ? 'pointer' : ''; };
document.querySelectorAll('[data-labels]').forEach((b) => b.addEventListener('click', () => {
  labelMode = b.dataset.labels;
  document.querySelectorAll('[data-labels]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  updateLabels();
}));

// ------------------------------------------------------------ selection + gizmo
function handleFor(id) {
  if (id === 'eyeR') return eyeR.handle;
  if (id === 'housing') return housingHandle;
  if (id?.startsWith('part:')) return partsModel.handles[id] ?? null;
  // the waveguide follows the spectacle lens (adjust it in the Waveguide section)
  if (id === 'prism' && results?.system.prism.kind) return null;
  return optics.handles[id] ?? null;
}

function select(id) {
  selected = id;
  updateLabels();
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
    const vr = params.eye.constants.vertexToRotationCenter;
    const C = h.position.clone().addScaledVector(sys.eye.gaze, -vr);
    params.eye.monoPDRight = r3(Math.max(20, -C.x));
    params.eye.pupilHeight = r3(C.y - sys.glasses.outlineMinY);
    params.eye.eyeRelief = r3(Math.max(4, sys.glasses.lensBackZ - (C.z + vr)));
  } else if (id === 'driver') {
    params.driver.pos = { x: r3(h.position.x), y: r3(h.position.y), z: r3(h.position.z) };
    params.driver.rot = eulerFromQuat(h.quaternion);
  } else if (id === 'housing') {
    const g = results.system.glasses, f = params.frame;
    // only the vertical position and the position along the temple can move
    f.housingOffsetY = r3(h.position.y - g.hingeY);
    f.housingOffsetZ = r3(Math.max(0, g.hingeZ - (h.position.z + f.housingLength / 2)));
  } else if (id.startsWith('part:')) {
    const part = params.parts.find((p) => `part:${p.id}` === id);
    if (part) {
      const host = partFrame(part, results.system).host;
      let pos = h.position.clone(), q = h.quaternion.clone();
      if (host) { pos = hostFrameInverse(host)(pos); q = host.quaternion.clone().invert().multiply(q); }
      part.pos = { x: r3(pos.x), y: r3(pos.y), z: r3(pos.z) };
      part.rot = eulerFromQuat(q);
    }
  }
  schedule();
};

function eulerFromQuat(q) {
  const x = new THREE.Vector3(1, 0, 0).applyQuaternion(q), y = new THREE.Vector3(0, 1, 0).applyQuaternion(q), z = new THREE.Vector3(0, 0, 1).applyQuaternion(q);
  return eulerDegFromBasis(x, y, z);
}

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
  } else if (a === 'applySizeCode') {
    const m = String(params.frame.sizeCode).match(/(\d+(?:\.\d+)?)\D+?(\d+(?:\.\d+)?)\D+?(\d+(?:\.\d+)?)/);
    if (m) { params.frame.lensWidth = +m[1]; params.frame.bridge = +m[2]; params.frame.templeLength = +m[3]; ui.flash('Frame size applied: lens ' + m[1] + ' mm, bridge ' + m[2] + ' mm, temple ' + m[3] + ' mm.'); }
    else ui.flash('Enter the code printed inside the temple arm, like 52□18-145.');
  } else if (a === 'focusForEye') {
    const target = assessFocus({ Vx: 0, Vy: 0 }, params.eye).targetVergence;
    const r = solveFocusDistance(params, target);
    if (r.distance != null) params.collimator.distance = Math.round(r.distance * 1000) / 1000;
    const ff = r.ok ? solveFieldFocus(params) : null;
    if (ff?.ok) params.collimator.distance = Math.round(ff.distance * 1000) / 1000;
    ui.flash(r.ok ? `OLED moved to ${params.collimator.distance.toFixed(2)} mm from the lens: centre vergence matched to your eye (${target.toFixed(2)} D), then the whole field balanced (90% within ${ff?.ok ? ff.residual.toFixed(2) : '—'} D).` : `Could not focus: ${r.reason}`);
  } else if (a === 'addPart') {
    const n = params.parts.filter((p) => p.custom).length + 1;
    const id = `custom${Date.now().toString(36)}`;
    params.parts.push({ id, name: `Custom part ${n}`, size: { x: 5, y: 10, z: 15 }, pos: { x: -72, y: 6, z: -60 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#8a7350', blocksLight: true, custom: true });
    params.bom.push({ id, name: `Custom part ${n}`, part: id, qty: 1, unit: 0, include: true, sourced: false, note: 'Enter your price.', sources: [] });
  } else if (a.startsWith('deletePart:')) {
    const id = a.slice('deletePart:'.length);
    params.parts = params.parts.filter((p) => p.id !== id);
    params.bom = params.bom.filter((b) => b.part !== id);
    if (selected === `part:${id}`) select(null);
  } else if (a.startsWith('loadMake:')) {
    const p = tunedParams(a.slice('loadMake:'.length));
    if (p) { params = p; fpv.reach = TUNED[p.make.id]?.reach ?? null; select(null); ui.flash(`Loaded ${p.make.name}. Every number is re-traced live; edit anything and the scorecard updates.`); }
  } else if (a.startsWith('selectComponent:')) {
    const id = a.slice('selectComponent:'.length);
    select(id);
    if (handleFor(id)) sm.attachGizmo(handleFor(id), 'translate');
    return;
  } else if (a.startsWith('selectPart:')) {
    const id = `part:${a.slice('selectPart:'.length)}`;
    select(id);
    if (handleFor(id)) sm.attachGizmo(handleFor(id), 'translate');
    return;
  } else if (a === 'clearImage') {
    params.hud.image = null; params.hud.imageName = '';
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
// click in the eye view: aim the HUD there (re-aligns the same parts)
$('#fpv-canvas').addEventListener('click', (e) => {
  const a = fpv.toAngles(e.clientX, e.clientY);
  if (!a || fpv.mode === 'normal') return;
  params.intent.azimuth = Math.round(a.h * 2) / 2;
  params.intent.elevation = Math.round(a.v * 2) / 2;
  params = alignChain(params);
  const c = computeCollimator(params.collimator, computeOled(params.oled), params.prism.n);
  if (c?.valid && params.collimator.mode !== 'thin') params.collimator.distance = c.frontFocalDistance;
  fpv.reach = null;
  ui.flash(`HUD aimed at ${params.intent.azimuth}° temporal, ${params.intent.elevation}° up. The prism, arm, lens and OLED were re-aligned; "Focus HUD for my eye" fine-tunes focus.`);
  ui.refresh(); schedule();
});
$('#fpv-reach').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  const res = await mapReach(params, { onProgress: (d, n) => { btn.textContent = `Mapping ${d}/${n}`; } });
  fpv.reach = res;
  btn.disabled = false; btn.textContent = 'Map reach';
  const good = res.filter((p) => p.buildable && p.visible >= 0.999).length;
  ui.flash(`Reach map: ${good} of ${res.length} aim points in your zone give a fully visible HUD with buildable hardware (green). Amber: partly visible or a fit problem; red: not visible.`);
  fpv.draw();
});
$('#fpv-flip').addEventListener('change', (e) => { params.hud.driverFlip = e.target.checked; ui.refresh(); redrawContent(); });
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

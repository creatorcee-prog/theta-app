// Control panel, results, diagnostics and selection UI. Talks to the app
// through callbacks only; holds no optical state of its own.

import { SECTIONS, VISIBILITY, COMPONENT_NAMES } from './schema.js';
import { SEGMENT_STYLE } from '../render/RayRenderer.js';

export const getPath = (obj, key) => key.split('.').reduce((o, k) => o?.[k], obj);
export function setPath(obj, key, value) {
  const ks = key.split('.');
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
  o[ks[ks.length - 1]] = value;
}

const TAG_TEXT = { spec: 'spec', assumed: 'assumed', design: 'design' };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, step) => {
  if (typeof v !== 'number') return v;
  const d = step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3;
  return v.toFixed(d);
};

export class UIController {
  constructor({ controlsEl, resultsEl, notesEl, selectionEl, visibilityEl, legendEl, metricsEl }, callbacks) {
    Object.assign(this, { controlsEl, resultsEl, notesEl, selectionEl, visibilityEl, legendEl, metricsEl });
    this.cb = callbacks;
    this.inputs = [];
    this.buildControls();
    this.buildVisibility();
    this.buildLegend();
  }

  // ------------------------------------------------------------ controls
  buildControls() {
    const p = this.cb.getParams();
    const frag = document.createDocumentFragment();
    for (const sec of SECTIONS) {
      const det = document.createElement('details');
      det.className = 'ctl-section';
      det.id = `sec-${sec.id}`;
      det.open = !!sec.open;
      det.innerHTML = `<summary>${esc(sec.title)}</summary>`;
      const body = document.createElement('div');
      body.className = 'ctl-body';
      for (const c of sec.controls) body.appendChild(this.makeControl(sec, c, p));
      if (sec.id === 'prism' || sec.id === 'oled') {
        const row = document.createElement('div');
        row.className = 'btn-row';
        row.innerHTML = `<button type="button" class="btn small" data-action="align">Re-align chain to target direction</button>`;
        body.appendChild(row);
      }
      det.appendChild(body);
      frag.appendChild(det);
    }
    this.controlsEl.appendChild(frag);
    this.controlsEl.addEventListener('click', (e) => {
      const b = e.target.closest('[data-action]');
      if (b) this.cb.onAction(b.dataset.action);
    });
  }

  makeControl(sec, c, p) {
    const id = `ctl-${sec.id}-${c.key.replace(/\./g, '-')}`;
    const wrap = document.createElement('div');
    wrap.className = `ctl ctl-${c.type ?? 'range'}`;
    const tag = `<span class="tag tag-${c.tag}" title="${c.tag === 'spec' ? 'Value given in the brief' : c.tag === 'assumed' ? 'Unknown for the real hardware: adjustable assumption' : 'Placement / design choice'}">${TAG_TEXT[c.tag]}</span>`;
    const v = getPath(p, c.key);
    let input;
    if (c.type === 'toggle') {
      wrap.innerHTML = `<label class="toggle" for="${id}"><input type="checkbox" id="${id}"><span>${esc(c.label)}</span></label>${tag}`;
      input = wrap.querySelector('input');
      input.checked = !!v;
      input.addEventListener('change', () => this.cb.onChange(c.key, input.checked));
    } else if (c.type === 'select') {
      wrap.innerHTML = `<label for="${id}">${esc(c.label)} ${tag}</label><select id="${id}">${c.options.map(([val, lab]) => `<option value="${val}">${esc(lab)}</option>`).join('')}</select>`;
      input = wrap.querySelector('select');
      input.value = v;
      input.addEventListener('change', () => this.cb.onChange(c.key, input.value));
    } else {
      wrap.innerHTML = `<div class="ctl-head"><label for="${id}">${esc(c.label)}</label>${tag}
        <input class="num" type="number" id="${id}-n" step="${c.step}" aria-label="${esc(c.label)} value"><span class="unit">${esc(c.unit ?? '')}</span></div>
        <input type="range" id="${id}" min="${c.min}" max="${c.max}" step="${c.step}">`;
      input = wrap.querySelector('input[type=range]');
      const num = wrap.querySelector('input.num');
      input.value = v; num.value = fmt(v, c.step);
      input.addEventListener('input', () => { num.value = fmt(+input.value, c.step); this.cb.onChange(c.key, +input.value); });
      num.addEventListener('change', () => { const x = +num.value; if (Number.isFinite(x)) { input.value = x; this.cb.onChange(c.key, x); } });
      input._num = num;
    }
    if (c.help) {
      const h = document.createElement('p');
      h.className = 'help'; h.textContent = c.help;
      wrap.appendChild(h);
    }
    if (c.after === 'refocus') {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn small'; b.dataset.action = 'refocus';
      b.textContent = 'Place OLED at focal plane';
      wrap.appendChild(b);
    }
    if (c.after === 'lookAtHud') {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn small'; b.dataset.action = 'lookAtHud';
      b.textContent = 'Look at the HUD';
      wrap.appendChild(b);
      const b2 = document.createElement('button');
      b2.type = 'button'; b2.className = 'btn small ghost'; b2.dataset.action = 'lookAhead';
      b2.textContent = 'Look straight ahead';
      wrap.appendChild(b2);
    }
    this.inputs.push({ c, input, wrap });
    return wrap;
  }

  refresh() {
    const p = this.cb.getParams();
    for (const { c, input, wrap } of this.inputs) {
      const v = getPath(p, c.key);
      if (document.activeElement !== input) {
        if (c.type === 'toggle') input.checked = !!v;
        else input.value = v;
        if (input._num && document.activeElement !== input._num) input._num.value = fmt(v, c.step);
      }
      wrap.hidden = c.showIf ? !c.showIf(p) : false;
    }
  }

  openSection(id) {
    const d = document.getElementById(`sec-${id}`);
    if (d) { d.open = true; d.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
  }

  // ------------------------------------------------------------ visibility + legend
  buildVisibility() {
    this.visibilityEl.innerHTML = VISIBILITY.map(([id, label]) =>
      `<label class="chk" for="vis-${id}"><input type="checkbox" id="vis-${id}" data-vis="${id}" checked><span>${esc(label)}</span></label>`).join('');
    this.visibilityEl.addEventListener('change', (e) => {
      const t = e.target.closest('[data-vis]');
      if (t) this.cb.onVisibility(t.dataset.vis, t.checked);
    });
  }

  setVisibilityChecked(id, on) {
    const el = document.getElementById(`vis-${id}`);
    if (el) el.checked = on;
  }

  buildLegend() {
    const items = Object.entries(SEGMENT_STYLE).map(([k, s]) =>
      `<label class="legend-item" for="ray-${k}"><input type="checkbox" id="ray-${k}" data-ray="${k}" checked><i style="background:#${s.color.toString(16).padStart(6, '0')}"></i>${esc(s.label)}</label>`).join('');
    this.legendEl.innerHTML = `${items}<label class="legend-item" for="ray-onlyPupil"><input type="checkbox" id="ray-onlyPupil" data-ray="onlyPupil">Only rays reaching the pupil</label>
      <label class="legend-item" for="ray-chief"><input type="checkbox" id="ray-chief" data-ray="chief" checked><i style="background:#fff"></i>Chief ray (display centre, axial)</label>`;
    this.legendEl.addEventListener('change', (e) => {
      const t = e.target.closest('[data-ray]');
      if (t) this.cb.onRayFilter(t.dataset.ray, t.checked);
    });
  }

  // ------------------------------------------------------------ selection
  showSelection(id) {
    if (!id) { this.selectionEl.hidden = true; return; }
    this.selectionEl.hidden = false;
    const movable = { oled: ['translate', 'rotate'], prism: ['translate', 'rotate'], collimator: ['translate'], eyeR: ['translate'], driver: ['translate'] }[id] ?? [];
    const section = { oled: 'oled', prism: 'prism', collimator: 'collimator', eyeR: 'eye', eyeL: 'eye', driver: 'oled', ribbon: 'oled', frame: 'frame', lensR: 'frame', lensL: 'frame', templeR: 'frame', templeL: 'frame', housing: 'frame', hingeR: 'frame', hingeL: 'frame' }[id];
    this.selectionEl.innerHTML = `<div class="sel-head"><span class="sel-dot"></span><strong>${esc(COMPONENT_NAMES[id] ?? id)}</strong>
      <button type="button" class="btn small ghost" data-sel="close" aria-label="Clear selection">Clear</button></div>
      <div class="btn-row">${movable.map((m) => `<button type="button" class="btn small" data-sel="${m}">${m === 'translate' ? 'Drag to move' : 'Drag to rotate'}</button>`).join('')}
      ${section ? `<button type="button" class="btn small ghost" data-sel="edit">Edit values</button>` : ''}
      <button type="button" class="btn small ghost" data-sel="hide">Hide</button></div>
      ${movable.length ? '<p class="help">Drag the gizmo in the 3D view. Every change is re-traced.</p>' : '<p class="help">This part is fixed by the frame dimensions.</p>'}`;
    this.selectionEl.onclick = (e) => {
      const b = e.target.closest('[data-sel]');
      if (!b) return;
      const a = b.dataset.sel;
      if (a === 'close') this.cb.onSelect(null);
      else if (a === 'edit') this.openSection(section);
      else if (a === 'hide') { this.cb.onVisibility(id, false); this.setVisibilityChecked(id, false); }
      else this.cb.onGizmoMode(id, a);
    };
  }

  // ------------------------------------------------------------ results
  renderMetrics(results, coverage, diag) {
    const f = coverage.field, L = coverage.lens;
    const s = diag.summary;
    const chip = (label, value, status) => `<div class="metric ${status ?? ''}"><span class="m-label">${label}</span><span class="m-value">${value}</span></div>`;
    const st = (id) => diag.checks.find((c) => c.id === id)?.status;
    this.metricsEl.innerHTML = [
      chip('Pupil rays', `${results.counts.pupil}/${results.counts.emitted}`, results.counts.pupil ? 'info' : 'fail'),
      chip('Lens coverage', `${L.coveragePct.toFixed(1)}%`, st('lensCov')),
      chip('FOV', f.hfov != null ? `${f.hfov.toFixed(1)}°×${f.vfov.toFixed(1)}°` : '—', st('hfov')),
      chip('Offset', f.hCenter != null ? `${f.hCenter.toFixed(1)}° / ${f.vCenter.toFixed(1)}°` : '—', st('hoff')),
      chip('TIR', diag.checks.find((c) => c.id === 'tir')?.value ?? '—', st('tir')),
      chip('Checks', `<b class="ok">${s.pass}</b> · <b class="warn">${s.warn}</b> · <b class="bad">${s.fail}</b>`, ''),
    ].join('');
  }

  renderResults(results, coverage, diag) {
    const f = coverage.field, L = coverage.lens, eb = coverage.eyebox;
    const n1 = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toFixed(1));
    const n2 = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toFixed(2));
    const row = (k, v, tag = 'calc') => `<tr><th scope="row">${k}</th><td>${v}</td><td><span class="tag tag-${tag}">${tag === 'calc' ? 'calculated' : tag}</span></td></tr>`;
    const groups = {};
    for (const c of diag.checks) (groups[c.group] ??= []).push(c);
    const statusWord = { pass: 'Pass', warn: 'Adjust', fail: 'Fail', info: 'Info' };
    this.resultsEl.innerHTML = `
      <section class="res-block">
        <h3>Lens coverage</h3>
        <table class="kv"><tbody>
          ${row('Right lens area', `${n1(L.area)} mm²`, 'assumed')}
          ${row('HUD footprint on lens (apparent)', `${n1(L.footprintArea)} mm²`)}
          ${row('Footprint inside lens', `${n1(L.insideArea)} mm²`)}
          ${row('Lens illuminated (apparent)', `<b>${n2(L.coveragePct)}%</b> (target ${results.system.params.targets.coverageMin}–${results.system.params.targets.coverageMax}%)`)}
          ${row('Footprint outside lens / clipped', `${n1(L.outsideArea)} mm² (${n1(L.outsidePct)}%)`)}
          ${row('Physical beam crossing the lens', `${n1(L.physicalArea)} mm²`)}
          ${row('Stray light exiting through lens', `${n2(L.strayPowerPct)}% of emitted`)}
          ${row('Coverage if FOV target were met', `${n1(L.targetFovCoveragePct)}%`)}
        </tbody></table>
        <p class="help">The prism sits behind the lens, so HUD light never passes through it. The apparent footprint is the region of the lens the HUD overlays, found by back-projecting each visible pixel from the pupil centre onto the lens plane (green overlay in 3D). Stray points (orange) are rays that physically hit the lens.</p>
      </section>
      <section class="res-block">
        <h3>Visual field from the right pupil</h3>
        <table class="kv"><tbody>
          ${row('Horizontal FOV', `${n1(f.hfov)}° (unclipped ${n1(f.availHfov)}°)`)}
          ${row('Vertical FOV', `${n1(f.vfov)}° (unclipped ${n1(f.availVfov)}°)`)}
          ${row('Horizontal offset (temporal +)', `${n1(f.hCenter)}°`)}
          ${row('Vertical offset (up +)', `${n1(f.vCenter)}°`)}
          ${row('Angular boundaries', f.hMin != null ? `h ${n1(f.hMin)}…${n1(f.hMax)}°, v ${n1(f.vMin)}…${n1(f.vMax)}°` : '—')}
          ${row('Nearest HUD edge to line of sight', `${n1(f.minRadius)}°`)}
          ${row('Pupil interception (rays)', `${n2(f.pupilRayPct)}%`)}
          ${row('Pupil interception (power)', `${n2(f.pupilPowerPct)}% of cone, ${n2(f.pupilPowerPct * results.coneFractionOfHemisphere)}% of hemisphere`)}
          ${row('Display pixels visible', `${f.visiblePixels} / ${f.totalPixels}`)}
          ${row('Eye-box, full field', `${n1(eb.full.width)} × ${n1(eb.full.height)} mm`)}
          ${row('Eye-box, ≥50% field', `${n1(eb.half.width)} × ${n1(eb.half.height)} mm`)}
        </tbody></table>
        <figure class="eyebox"><canvas id="eyebox-canvas" width="240" height="240" aria-label="Eye-box map"></canvas>
          <figcaption>Eye-box map: share of the display visible as the pupil centre moves ±${eb.range} mm on the pupil plane (right/up). Ring = current ${results.system.params.eye.pupilDiameter} mm pupil.</figcaption></figure>
      </section>
      <section class="res-block">
        <h3>Diagnostics</h3>
        <p class="summary-line"><span class="pill pass">${diag.summary.pass} pass</span><span class="pill warn">${diag.summary.warn} adjust</span><span class="pill fail">${diag.summary.fail} fail</span><span class="muted">Traced in ${results.elapsedMs.toFixed(0)} ms</span></p>
        ${Object.entries(groups).map(([g, cs]) => `<h4>${esc(g)}</h4><ul class="checks">${cs.map((c) => `
          <li class="check ${c.status}"><span class="dot" aria-hidden="true"></span><span class="c-label">${esc(c.label)}</span>
          <span class="c-value">${esc(c.value)}</span><span class="sr-only">${statusWord[c.status]}</span>
          ${c.explain ? `<span class="c-explain">${esc(c.explain)}</span>` : ''}</li>`).join('')}</ul>`).join('')}
      </section>`;
    this.drawEyebox(document.getElementById('eyebox-canvas'), eb, results.system.eye.pupilRadius);
  }

  drawEyebox(cv, eb, pupilR) {
    if (!cv) return;
    const ctx = cv.getContext('2d');
    const W = cv.width, n = eb.n, cell = W / n;
    for (const g of eb.grid) {
      const ix = Math.round((g.ox + eb.range) / eb.step), iy = Math.round((g.oy + eb.range) / eb.step);
      const v = g.frac;
      ctx.fillStyle = v >= 0.999 ? '#2fbf71' : v >= 0.5 ? `rgba(242,201,76,${0.4 + 0.6 * v})` : v > 0 ? `rgba(255,90,79,${0.25 + 0.75 * v})` : '#1b2129';
      ctx.fillRect(ix * cell, W - (iy + 1) * cell, cell + 0.5, cell + 0.5);
    }
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
    const s = W / (2 * eb.range);
    ctx.beginPath(); ctx.arc(W / 2, W / 2, pupilR * s, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.85)'; ctx.font = '11px "IBM Plex Mono", monospace';
    ctx.fillText('nasal', 4, W / 2 - 4); ctx.fillText('temporal', W - 60, W / 2 - 4); ctx.fillText('up', W / 2 + 4, 12);
  }

  renderNotes(html) { this.notesEl.innerHTML = html; }
}

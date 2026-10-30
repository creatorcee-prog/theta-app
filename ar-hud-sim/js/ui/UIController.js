// Control panel, results, diagnostics and selection UI. Talks to the app
// through callbacks only; holds no optical state of its own.

import { SECTIONS, VISIBILITY, COMPONENT_NAMES } from './schema.js';
import { SEGMENT_STYLE } from '../render/RayRenderer.js';
import { bomTotals } from '../model/parts.js';

export const getPath = (obj, key) => key.split('.').reduce((o, k) => o?.[k], obj);
export function setPath(obj, key, value) {
  const ks = key.split('.');
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
  o[ks[ks.length - 1]] = value;
}

const TAG_TEXT = { spec: 'spec', assumed: 'assumed', design: 'design', measured: 'measured' };
const TAG_TITLE = { spec: 'Value given in the brief', assumed: 'Unknown for the real hardware: adjustable assumption', design: 'Placement / design choice', measured: 'Enter your own measurement (default is a typical adult value)' };
const money = (x) => `$${(Number(x) || 0).toFixed(2)}`;
const grams = (x) => `${(Number(x) || 0).toFixed(1)} g`;
const WEIGHT_BASIS = { calc: 'Volume of the modelled part × material density', spec: 'Taken from a product listing', estimate: 'No published weight found', measured: 'Enter your own measurement' };
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
      if (sec.id === 'prism' || sec.id === 'oled' || sec.id === 'align') {
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
    const tag = `<span class="tag tag-${c.tag}" title="${TAG_TITLE[c.tag]}">${TAG_TEXT[c.tag]}</span>`;
    const v = getPath(p, c.key);
    let input;
    if (c.type === 'toggle') {
      wrap.innerHTML = `<label class="toggle" for="${id}"><input type="checkbox" id="${id}"><span>${esc(c.label)}</span></label>${tag}`;
      input = wrap.querySelector('input');
      input.checked = !!v;
      input.addEventListener('change', () => this.cb.onChange(c.key, input.checked));
    } else if (c.type === 'textarea') {
      wrap.innerHTML = `<label for="${id}">${esc(c.label)} ${tag}</label><textarea id="${id}" rows="4" spellcheck="false"></textarea>`;
      input = wrap.querySelector('textarea');
      input.value = v ?? '';
      input.addEventListener('change', () => this.cb.onChange(c.key, input.value));
    } else if (c.type === 'text') {
      wrap.innerHTML = `<label for="${id}">${esc(c.label)} ${tag}</label><input type="text" id="${id}" maxlength="40" autocomplete="off">`;
      input = wrap.querySelector('input');
      input.value = v ?? '';
      input.addEventListener('input', () => this.cb.onChange(c.key, input.value));
    } else if (c.type === 'color') {
      wrap.innerHTML = `<label class="color-row" for="${id}"><span>${esc(c.label)}</span>${tag}<input type="color" id="${id}"></label>`;
      input = wrap.querySelector('input');
      input.value = v;
      input.addEventListener('input', () => this.cb.onChange(c.key, input.value));
    } else if (c.type === 'file') {
      wrap.innerHTML = `<label for="${id}">${esc(c.label)} ${tag}</label>
        <input type="file" id="${id}" accept="image/*">
        <div class="file-row"><span class="file-name muted"></span><button type="button" class="btn small ghost" data-action="clearImage">Remove image</button></div>`;
      input = wrap.querySelector('input');
      input.addEventListener('change', () => {
        const file = input.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          // downscale to the display's pixel grid so the page state stays small
          const img = new Image();
          img.onload = () => {
            const p2 = this.cb.getParams();
            const k = Math.min(1, Math.max(p2.oled.resX, 64) / img.naturalWidth, Math.max(p2.oled.resY, 40) / img.naturalHeight);
            const cv = document.createElement('canvas');
            cv.width = Math.max(1, Math.round(img.naturalWidth * k)); cv.height = Math.max(1, Math.round(img.naturalHeight * k));
            cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
            this.cb.onChange('hud.imageName', file.name);
            this.cb.onChange(c.key, cv.toDataURL('image/png'));
          };
          img.onerror = () => { wrap.querySelector('.file-name').textContent = 'That file could not be read as an image.'; };
          img.src = reader.result;
        };
        reader.readAsDataURL(file);
      });
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
      // typed values are clamped to the control's range
      num.addEventListener('change', () => {
        let x = +num.value;
        if (!Number.isFinite(x)) { num.value = fmt(+input.value, c.step); return; }
        x = Math.min(c.max, Math.max(c.min, x));
        num.value = fmt(x, c.step); input.value = x; this.cb.onChange(c.key, x);
      });
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
    const buttons = { applySizeCode: 'Apply size code', focusForEye: 'Focus HUD for my eye' };
    if (buttons[c.after]) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn small'; b.dataset.action = c.after;
      b.textContent = buttons[c.after];
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
      if (c.type === 'file') {
        wrap.querySelector('.file-name').textContent = p.hud.image ? (p.hud.imageName || 'Image loaded') : 'No image loaded';
        wrap.querySelector('[data-action=clearImage]').hidden = !p.hud.image;
        if (!p.hud.image) input.value = '';
      } else if (document.activeElement !== input) {
        if (c.type === 'toggle') input.checked = !!v;
        else input.value = v ?? '';
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
    const isPart = id.startsWith('part:');
    const movable = isPart ? ['translate', 'rotate'] : { oled: ['translate', 'rotate'], prism: ['translate', 'rotate'], collimator: ['translate'], eyeR: ['translate'], driver: ['translate', 'rotate'], housing: ['translate'] }[id] ?? [];
    const section = isPart ? null : { oled: 'oled', prism: 'prism', collimator: 'collimator', eyeR: 'measure', eyeL: 'measure', driver: 'driver', ribbon: 'driver', frame: 'frame', lensR: 'measure', lensL: 'measure', templeR: 'frame', templeL: 'frame', housing: 'frame', hingeR: 'frame', hingeL: 'frame', head: 'measure' }[id];
    const name = isPart ? (this.cb.getParams().parts.find((p) => `part:${p.id}` === id)?.name ?? id) : (COMPONENT_NAMES[id] ?? id);
    this.selectionEl.innerHTML = `<div class="sel-head"><span class="sel-dot"></span><strong>${esc(name)}</strong>
      <button type="button" class="btn small ghost" data-sel="close" aria-label="Clear selection">Clear</button></div>
      <div class="btn-row">${movable.map((m) => `<button type="button" class="btn small" data-sel="${m}">${m === 'translate' ? 'Drag to move' : 'Drag to rotate'}</button>`).join('')}
      ${section ? `<button type="button" class="btn small ghost" data-sel="edit">Edit values</button>` : ''}
      <button type="button" class="btn small ghost" data-sel="hide">Hide</button></div>
      ${movable.length ? `<p class="help">Drag the gizmo in the 3D view. Every change is re-traced.${id === 'housing' ? ' The housing moves up/down and along the temple.' : ''}${isPart ? ' Exact values: Parts &amp; cost tab.' : ''}</p>` : '<p class="help">Its size and position come from the frame dimensions: use Edit values.</p>'}`;
    this.selectionEl.onclick = (e) => {
      const b = e.target.closest('[data-sel]');
      if (!b) return;
      const a = b.dataset.sel;
      if (a === 'close') this.cb.onSelect(null);
      else if (a === 'edit') this.openSection(section);
      else if (a === 'hide') {
        if (isPart) this.cb.onPartChange(id.slice(5), 'visible', false);
        else { this.cb.onVisibility(id, false); this.setVisibilityChecked(id, false); }
      }
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
      results.system.prism.kind === 'patch'
        ? chip('Mirror incidence', diag.checks.find((c) => c.id === 'chiefInc')?.value ?? '—', st('chiefInc'))
        : chip('TIR', diag.checks.find((c) => c.id === 'tir' || c.id === 'guideTIR')?.value ?? '—', st(diag.checks.some((c) => c.id === 'guideTIR') ? 'guideTIR' : 'tir')),
      chip('Parts total', money(bomTotals(this.cb.getParams().bom).total), 'info'),
      chip('Weight', `${bomTotals(this.cb.getParams().bom).grams.toFixed(1)} g`, 'info'),
      ...(this.cb.getScore?.() ? [chip('Goals', `${Math.round(100 * this.cb.getScore().overall)}%`, this.cb.getScore().meetsBar ? 'pass' : 'fail')] : []),
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

  flash(text) {
    const el = document.getElementById('flash');
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(this._flashT);
    this._flashT = setTimeout(() => { el.hidden = true; }, 6000);
  }

  // ------------------------------------------------------------ makes
  renderMakes(makes, tuned, current, activeId) {
    const el = this.makesEl;
    if (!el) return;
    const pct = (x) => `${Math.round(100 * x)}%`;
    const bars = (goals) => goals.map((g) => `
      <div class="goal ${g.met ? 'met' : g.score >= 0.8 ? 'near' : 'miss'}">
        <span class="g-label">${esc(g.label)}</span><span class="g-val">${esc(g.value)}</span>
        <span class="g-bar" aria-hidden="true"><i style="width:${Math.round(100 * g.score)}%"></i></span><span class="g-pct">${pct(g.score)}</span>
      </div>`).join('');
    const cur = current ? `
      <section class="res-block make-card current">
        <h3>Current design${activeId ? ` · ${esc(makes.find((m) => m.id === activeId)?.name ?? '')}` : ''} <span class="score ${current.meetsBar ? 'ok' : 'bad'}">${pct(current.overall)}</span></h3>
        ${bars(current.goals)}
        ${current.structural.some((s) => !s.ok) ? `<p class="help">Failing structure checks: ${current.structural.filter((s) => !s.ok).map((s) => esc(s.label)).join(' · ')}</p>` : ''}
      </section>` : '';
    el.innerHTML = `
      <section class="res-block">
        <h3>Makes</h3>
        <p class="help">Four different ways to build the same HUD, each from parts that can be bought. A search ran each make's own design choices through the full tracer and kept the best result. Goals: 100% pupil coverage, ≤ 48 g, &lt; $200, every structure check passing. Each goal scores 0–100% (weight and cost as target ÷ actual), and the overall score is their mean; the bar is 80%.</p>
      </section>
      ${cur}
      ${makes.map((m) => {
        const t = tuned[m.id];
        if (!t) return '';
        const v = t.vars;
        return `<section class="res-block make-card">
          <h3>${esc(m.name)} <span class="tagline">${esc(m.tagline)}</span> <span class="score ${t.overall >= 0.8 ? 'ok' : 'bad'}">${pct(t.overall)}</span></h3>
          <p class="help">${esc(m.idea)}</p>
          ${bars(t.goals.map((g) => ({ ...g, label: { pupil: 'Pupil coverage', weight: 'Weight', cost: 'Cost', structure: 'Feasible structure' }[g.id] })))}
          <p class="make-spec">${v.prism != null ? `${v.prism} mm K9 prism` : v.radius != null ? `mirror patch Ø${v.diam} mm, R ${v.radius} mm, fold ${v.fold}°` : `${v.thick} mm waveguide, ${Math.round(v.facets)} facets, guided ${v.guide}°`} · ${esc(v.lens)} at ${v.stop} mm stop · HUD at ${v.az}° / ${v.el}° ·${v.tilt != null ? ` entry tilt ${v.tilt}° ·` : ''} FOV ${t.fov?.[0]?.toFixed(1)}° × ${t.fov?.[1]?.toFixed(1)}°</p>
          <div class="btn-row"><button type="button" class="btn small" data-act="loadMake:${m.id}">Load ${esc(m.name)}</button></div>
        </section>`;
      }).join('')}`;
  }

  bindMakes(el) {
    this.makesEl = el;
    el.addEventListener('click', (e) => { const b = e.target.closest('[data-act]'); if (b) this.cb.onAction(b.dataset.act); });
  }

  // ------------------------------------------------------------ parts & cost
  renderParts(params, results) {
    const el = this.partsEl;
    if (!el || el.contains(document.activeElement)) return; // don't rebuild under the cursor
    const tot = bomTotals(params.bom);
    const w = results?.weights;
    const partById = Object.fromEntries(params.parts.map((p) => [p.id, p]));
    const blocked = (pid) => results?.counts.absorbed[`part:${pid}`] ?? 0;
    const num = (attr, v, step = 0.1, w = 'w5') => `<input class="num ${w}" type="number" step="${step}" value="${v}" ${attr}>`;
    const rows = params.bom.map((b) => {
      const part = b.part ? partById[b.part] : null;
      const srcs = b.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join('<br>');
      const placeBtn = part ? `<button type="button" class="btn small ghost" data-act="selectPart:${part.id}">Select &amp; drag</button>`
        : b.component && ['oled', 'driver', 'collimator', 'prism', 'housing'].includes(b.component) ? `<button type="button" class="btn small ghost" data-act="selectComponent:${b.component}">Select &amp; drag</button>` : '';
      const editor = part ? `
        <details class="part-edit"><summary>Placement, size and options${blocked(part.id) ? ` · <span class="bad">blocks ${blocked(part.id)} rays</span>` : ''}</summary>
          <div class="grid3">
            ${['x', 'y', 'z'].map((k) => `<label>Pos ${k}${num(`data-part="${part.id}" data-key="pos.${k}"`, part.pos[k])}</label>`).join('')}
            ${['yaw', 'pitch', 'roll'].map((k) => `<label>${k}${num(`data-part="${part.id}" data-key="rot.${k}"`, part.rot[k], 0.5)}</label>`).join('')}
            ${['x', 'y', 'z'].map((k) => `<label>Size ${k}${num(`data-part="${part.id}" data-key="size.${k}"`, part.size[k])}</label>`).join('')}
          </div>
          <div class="part-opts">
            <label>Attached to <select data-part="${part.id}" data-key="attach"><option value="">Nothing (world)</option><option value="prism"${part.attach === 'prism' ? ' selected' : ''}>Prism</option><option value="oled"${part.attach === 'oled' ? ' selected' : ''}>Micro-OLED</option></select></label>
            <label class="chk"><input type="checkbox" data-part="${part.id}" data-key="blocksLight"${part.blocksLight ? ' checked' : ''}><span>Blocks light</span></label>
            <label class="chk"><input type="checkbox" data-part="${part.id}" data-key="visible"${part.visible !== false ? ' checked' : ''}><span>Shown</span></label>
            <input type="color" value="${part.color}" data-part="${part.id}" data-key="color" aria-label="Colour">
            ${part.custom ? `<input type="text" value="${esc(part.name)}" data-part="${part.id}" data-key="name" aria-label="Part name">` : ''}
            ${part.custom ? `<button type="button" class="btn small ghost" data-act="deletePart:${part.id}">Delete part</button>` : ''}
          </div>
          <p class="help">Positions in mm (world: −x = your right, +z forward${part.attach ? `; relative to the ${part.attach === 'prism' ? 'prism' : 'OLED'} when attached` : ''}).</p>
        </details>` : '';
      return `<li class="bom-row${b.include ? '' : ' off'}">
        <div class="bom-main">
          <label class="chk"><input type="checkbox" data-bom="${b.id}" data-key="include"${b.include ? ' checked' : ''}><span class="bom-name">${esc(b.name)}</span></label>
          <span class="bom-badge ${b.sourced ? 'src' : 'est'}">${b.sourced ? 'sourced' : 'estimate'}</span>
        </div>
        <div class="bom-nums">
          <label>Qty ${num(`data-bom="${b.id}" data-key="qty"`, b.qty, 1, 'w3')}</label>
          <label>Unit $ ${num(`data-bom="${b.id}" data-key="unit"`, b.unit, 0.01, 'w5')}</label>
          <span class="bom-sub">${money(b.unit * b.qty)}</span>
        </div>
        <div class="bom-nums">
          <label>Weight g ${num(`data-bom="${b.id}" data-key="weight"`, Math.round((b.weight || 0) * 100) / 100, 0.01, 'w5')}</label>
          <span class="bom-badge w-${b.weightBasis}" title="${WEIGHT_BASIS[b.weightBasis]}">${b.weightBasis === 'calc' ? 'calculated' : b.weightBasis}</span>
          ${b.weightBasis === 'calc' ? `<label class="chk"><input type="checkbox" data-bom="${b.id}" data-key="autoWeight"${b.autoWeight !== false ? ' checked' : ''}><span>from geometry</span></label>` : ''}
          <span class="bom-sub">${grams((b.weight || 0) * b.qty)}</span>
        </div>
        ${b.weightNote ? `<p class="help">Weight: ${esc(b.weightNote)}${(b.weightSources ?? []).map((s) => ` <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join(';')}</p>` : ''}
        ${b.note ? `<p class="help">${esc(b.note)}</p>` : ''}
        ${srcs ? `<p class="bom-src">${srcs}</p>` : ''}
        <div class="btn-row">${placeBtn}</div>
        ${editor}
      </li>`;
    }).join('');
    el.innerHTML = `
      <section class="res-block">
        <h3>Parts &amp; cost</h3>
        <div class="totals">
          <div><span class="m-label2">Grand total</span><b>${money(tot.total)}</b></div>
          <div><span class="m-label2">Sourced prices</span>${money(tot.sourced)}</div>
          <div><span class="m-label2">Estimates</span>${money(tot.estimated)}</div>
          <div><span class="m-label2">Excluded</span>${money(tot.excluded)}</div>
        </div>
        <div class="totals">
          <div><span class="m-label2">Total weight (worn)</span><b>${grams(tot.grams)}</b></div>
          <div><span class="m-label2">Of which estimated</span>${grams(tot.gramsEstimated)}</div>
          ${w ? `<div><span class="m-label2">Right / left side</span>${grams(w.right)} / ${grams(w.left)}</div>
          <div><span class="m-label2">Centre of mass</span>${w.com ? `x ${w.com.x.toFixed(0)}, z ${w.com.z.toFixed(0)} mm` : '—'}</div>` : ''}
        </div>
        <p class="help">Weights are per unit × quantity. <b>Calculated</b> lines come from the modelled geometry (N-BK7 2.51 g/cm³, PLA 1.24 g/cm³, FR-4 1.85 g/cm³) and update as you resize parts; typing a value overrides it. <b>Spec</b> lines come from a listing, <b>estimate</b> lines have no source, <b>measured</b> means enter your own. Centre of mass: −x is your right, z = 0 at the lenses, negative toward the ears. For comparison, Ray-Ban Meta glasses weigh about 48.6 g.</p>
        <p class="help">Single-unit retail prices from the linked listings (October 2026 snapshot), excluding shipping and tax. "Estimate" lines have no source; replace them with your quotes. Untick a line to leave it out of the total.</p>
        <ul class="bom">${rows}</ul>
        <div class="btn-row"><button type="button" class="btn small" data-act="addPart">Add a custom part</button></div>
      </section>`;
  }

  bindParts(el) {
    this.partsEl = el;
    el.addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]');
      if (b) this.cb.onAction(b.dataset.act);
    });
    const onEdit = (e) => {
      const t = e.target;
      const val = t.type === 'checkbox' ? t.checked : t.type === 'number' ? +t.value : t.value;
      if (t.type === 'number' && !Number.isFinite(val)) return;
      if (t.dataset.bom) this.cb.onBomChange(t.dataset.bom, t.dataset.key, val);
      else if (t.dataset.part) this.cb.onPartChange(t.dataset.part, t.dataset.key, t.dataset.key === 'attach' ? (val || null) : val);
    };
    el.addEventListener('change', onEdit);
  }
}

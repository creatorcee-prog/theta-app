// Draws traced ray paths exactly as the tracer produced them. Segment colour
// encodes the physical stage; a travelling pulse shows propagation direction.

import * as THREE from 'three';

export const SEGMENT_STYLE = {
  emit: { color: 0xffd36b, label: 'OLED emission' },
  lens: { color: 0xffa94d, label: 'After collimator' },
  glass: { color: 0x4fd1ff, label: 'Refracted into glass' },
  tir: { color: 0xff5fd2, label: 'Internal reflection (TIR)' },
  reflect: { color: 0xc6a8ff, label: 'Mirror reflection' },
  emerge: { color: 0x32d27a, label: 'Emerging → reaches pupil' },
  emergeMiss: { color: 0xff5a4f, label: 'Emerging → misses pupil' },
  leak: { color: 0xff9f43, label: 'Leaked through hypotenuse' },
  ghost: { color: 0x7b8aa3, label: 'Fresnel ghost reflection' },
};

const vert = /* glsl */`
  attribute float dist;
  attribute vec3 color;
  attribute float alphaBase;
  varying float vDist;
  varying vec3 vColor;
  varying float vAlpha;
  #include <clipping_planes_pars_vertex>
  void main() {
    vDist = dist; vColor = color; vAlpha = alphaBase;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mvPosition;
    #include <clipping_planes_vertex>
  }
`;
const frag = /* glsl */`
  uniform float time;
  uniform float spacing;
  uniform float animate;
  varying float vDist;
  varying vec3 vColor;
  varying float vAlpha;
  #include <clipping_planes_pars_fragment>
  void main() {
    #include <clipping_planes_fragment>
    float ph = fract((vDist - time) / spacing);
    float pulse = smoothstep(0.0, 0.08, ph) * (1.0 - smoothstep(0.08, 0.32, ph));
    float a = vAlpha * mix(1.0, 0.45 + 1.6 * pulse, animate);
    gl_FragColor = vec4(vColor * (0.8 + 0.6 * pulse * animate), clamp(a, 0.0, 1.0));
  }
`;

export class RayRenderer {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.group = new THREE.Group();
    this.group.userData.componentId = 'rays';
    sceneManager.scene.add(this.group);
    this.material = new THREE.ShaderMaterial({
      uniforms: { time: { value: 0 }, spacing: { value: 14 }, animate: { value: 1 } },
      vertexShader: vert, fragmentShader: frag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    this.speed = 22; // mm per second
    this.paused = false;
    this.filters = { emit: true, lens: true, glass: true, tir: true, reflect: true, emerge: true, emergeMiss: true, leak: true, ghost: true, onlyPupil: false, chief: true };
  }

  tick(dt) {
    if (!this.paused) this.material.uniforms.time.value += dt * this.speed;
  }

  setPaused(p) { this.paused = p; this.material.uniforms.animate.value = p ? 0.35 : 1; }

  update(results, { maxPaths = 900, brightness = 0.75 } = {}) {
    this.group.clear();
    if (!results) return;
    const f = this.filters;
    const all = results.paths;
    // Choose paths to draw: every pupil-reaching path first (up to half the
    // budget), then an even sample of the rest. Nothing is synthesised.
    const pupil = [], other = [];
    for (const p of all) (p.outcome === 'pupil:eyeR' ? pupil : other).push(p);
    const pick = (arr, n) => (arr.length <= n ? arr : arr.filter((_, i) => i % Math.ceil(arr.length / n) === 0));
    const chosen = pick(pupil, Math.floor(maxPaths / 2));
    if (!f.onlyPupil) chosen.push(...pick(other, maxPaths - chosen.length));
    if (f.chief && results.chief) chosen.push({ ...results.chief, isChief: true });

    const pos = [], col = [], dist = [], alpha = [];
    const color = new THREE.Color();
    const hitPts = { glass: [], tir: [], leak: [] };
    for (const p of chosen) {
      const reaches = p.outcome === 'pupil:eyeR';
      let d = 0;
      for (const s of p.segments) {
        let type = s.type;
        if (type === 'emerge' && !reaches) type = 'emergeMiss';
        const len = s.a.distanceTo(s.b);
        if (f[type] === false) { d += len; continue; }
        if (p.isChief) color.set(0xffffff);
        else if (type === 'emit' && p.color && results.bands.length > 1) color.set(p.color);
        else color.set(SEGMENT_STYLE[type].color);
        const w = Math.max(0.06, Math.min(1, s.w * 40)) * (0.35 + 0.65 * brightness);
        const a = p.isChief ? 1 : type === 'ghost' ? 0.25 : (reaches ? 0.85 : 0.35) * w;
        pos.push(s.a.x, s.a.y, s.a.z, s.b.x, s.b.y, s.b.z);
        col.push(color.r, color.g, color.b, color.r, color.g, color.b);
        dist.push(d, d + len);
        alpha.push(a, a);
        d += len;
        if (type === 'glass') hitPts.glass.push(s.a);
        if (type === 'tir') hitPts.tir.push(s.a);
        if (type === 'leak') hitPts.leak.push(s.a);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    geo.setAttribute('dist', new THREE.Float32BufferAttribute(dist, 1));
    geo.setAttribute('alphaBase', new THREE.Float32BufferAttribute(alpha, 1));
    const lines = new THREE.LineSegments(geo, this.material);
    lines.frustumCulled = false;
    this.group.add(lines);
    // interaction points (where refraction / reflection is computed)
    for (const [k, pts] of Object.entries(hitPts)) {
      if (!pts.length) continue;
      const sample = pick(pts, 400);
      const g = new THREE.BufferGeometry().setFromPoints(sample);
      this.group.add(new THREE.Points(g, new THREE.PointsMaterial({ color: SEGMENT_STYLE[k].color, size: 3, sizeAttenuation: false, transparent: true, opacity: 0.8, depthWrite: false })));
    }
    // ray crossings at the pupil plane (green inside the pupil, red outside)
    const inside = [], outside = [];
    const eye = results.system.eye;
    for (const px of results.pixelResults) for (const fr of px.finals) {
      if (fr.point.distanceTo(eye.pupilCenter) > 9) continue;
      (fr.point.distanceTo(eye.pupilCenter) <= eye.pupilRadius ? inside : outside).push(fr.point.clone().addScaledVector(eye.gaze, 0.05));
    }
    if (inside.length) this.group.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(pick(inside, 1500)), new THREE.PointsMaterial({ color: 0x32d27a, size: 2.5, sizeAttenuation: false })));
    if (outside.length) this.group.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(pick(outside, 1500)), new THREE.PointsMaterial({ color: 0xff5a4f, size: 2, sizeAttenuation: false, transparent: true, opacity: 0.7 })));
    this.drawnPaths = chosen.length;
  }
}

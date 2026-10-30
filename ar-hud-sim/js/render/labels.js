import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

export function makeLabel(text, tone = '') {
  const el = document.createElement('div');
  el.className = `scene-label ${tone}`;
  el.textContent = text;
  const obj = new CSS2DObject(el);
  obj.userData.isLabel = true;
  return obj;
}

import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

export function makeLabel(text, tone = '') {
  const el = document.createElement('div');
  el.className = `scene-label ${tone}`;
  el.textContent = text;
  const obj = new CSS2DObject(el);
  obj.userData.isLabel = true;
  return obj;
}

// The component a label describes: the nearest pickable component found
// under the label's parent group (labels sit beside their meshes).
export function labelOwner(label) {
  if (label.userData.owner !== undefined) return label.userData.owner;
  let owner = null;
  for (let g = label.parent; g && !owner; g = g.parent) {
    if (g.userData.componentId) { owner = g.userData.componentId; break; }
    g.traverse((o) => { if (!owner && o !== label && o.userData.componentId) owner = o.userData.componentId; });
  }
  label.userData.owner = owner;
  return owner;
}

/** mode 'all' | 'off' | 'focus' (only the hovered / selected component). */
export function applyLabelMode(root, mode, focusIds) {
  root.traverse((o) => {
    if (!o.userData.isLabel) return;
    o.visible = mode === 'all' || (mode === 'focus' && focusIds.includes(labelOwner(o)));
  });
}

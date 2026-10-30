// Placeable hardware parts and the bill of materials.
//
// Prices are single-unit retail snapshots found online in October 2026 and
// are only as good as their sources. `sourced: false` marks an estimate with
// no source found: it is excluded from the "sourced" total and shown
// separately. Edit any price; the totals update live.

import { Vector3, Quaternion, Matrix4 } from 'three';
import { quatFromEulerDeg } from '../optics/OpticalComponents.js';

// Generic box parts placed in the scene. pos/rot are world values, or
// relative to `attach` ('prism' | 'oled') when set.
export function defaultParts() {
  return [
    { id: 'prismMount', name: 'Prism mount bracket', size: { x: 11, y: 11, z: 1.5 }, pos: { x: 0, y: 0, z: 6 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: 'prism', color: '#56606e', blocksLight: true, custom: false },
    { id: 'battery', name: 'LiPo battery 3.7 V 150 mAh (501230)', size: { x: 5, y: 12, z: 30 }, pos: { x: 71, y: 6, z: -112 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#3c6fb0', blocksLight: true, custom: false },
    { id: 'charger', name: 'USB-C LiPo charger board', size: { x: 7.2, y: 19, z: 24 }, pos: { x: 71, y: 6, z: -82 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#2b2b33', blocksLight: true, custom: false },
    { id: 'compute', name: 'Raspberry Pi Zero 2 W (HDMI source)', size: { x: 5, y: 30, z: 65 }, pos: { x: -72, y: -4, z: -132 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#1f6b3a', blocksLight: true, custom: false },
    { id: 'imu', name: 'IMU breakout (head tracking)', size: { x: 3, y: 10, z: 18 }, pos: { x: -70.5, y: 6, z: -58 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#6b3a8f', blocksLight: true, custom: false },
  ];
}

const S = {
  dmPanel: { label: 'DisplayModule, 0.23″ OLEDoS panel listing ($139)', url: 'https://displaymodule.com/products/0-23-inch-micro-oled-display-640x400' },
  bonanza: { label: 'Bonanza listing ($159)', url: 'https://www.bonanza.com/items/like/1730698481' },
  walmart: { label: 'Walmart listing ($199)', url: 'https://www.walmart.com/c/kp/micro-oled' },
  dmDriver: { label: 'DisplayModule DMRXHMB HDMI driver board ($199)', url: 'https://www.displaymodule.com/products/dmrxhmb-hdmi-micro-driver-board-typec-oled-amoled-evaluation-demo' },
  tindieKit: { label: 'Tindie 0.23″ kit with HDMI board ($275, 800 nits)', url: 'https://www.tindie.com/products/oled-modules/microdisplay-023-inch-micro-oled-display-640x400/' },
  dmKit: { label: 'DisplayModule DM-ADTTR-024 kit ($599)', url: 'https://displaymodule.com/products/0-23-inch-micro-oled-display' },
  newportPrism: { label: 'Newport ValuMax BRP-10, 10 mm N-BK7, uncoated ($63)', url: 'https://np.s2.mks.com/f/valumax-right-angle-prisms' },
  edmundPrism: { label: 'Edmund Optics 10 mm N-BK7 RA prism (£74.80)', url: 'https://www.edmundoptics.co.uk/p/10mm-uncoated-n-bk7-high-tolerance-ra-prism/2409/' },
  newportAl: { label: 'Newport BRAP13-AV, aluminium hypotenuse (price not retrieved)', url: 'https://np.p1.mks.com/p/BRAP13-AV' },
  acl1512: { label: 'Thorlabs ACL1512 f = 12 mm asphere, 2015 catalog ($16.20 / $26.20 AR)', url: 'https://www.thorlabs.com/catalogpages/Obsolete/2015/ACL1210.pdf' },
  battery: { label: 'eBay 501230 150 mAh LiPo ($6.15)', url: 'https://www.ebay.com/itm/174683669832' },
  charger: { label: 'Adafruit Micro-Lipo USB-C charger #4410 ($5.95)', url: 'https://www.adafruit.com/product/4410' },
  piZero: { label: 'Raspberry Pi Zero 2 W launch price ($15, 2021)', url: 'https://betanews.com/2021/10/28/raspberry-pi-zero-2-w' },
  piWeight: { label: 'Kubii: Pi Zero 2 W, 65 × 30.5 mm, 16 g', url: 'https://kubii.com/en/nano-computers/3455-raspberry-pi-zero-2-w-wh.html' },
  bk7: { label: 'N-BK7 density 2.51 g/cm³ (PGO)', url: 'https://www.pgo-online.com/intl/BK7.html' },
  rbMeta: { label: 'Ray-Ban Meta Wayfarer 48.6 g (SHI)', url: 'https://www.uk.shi.com/Product/47381750/Ray-Ban---Meta-Smart-glasses' },
};

// Bill of materials. `part` links to a generic part id, `component` to a
// built-in optical component.
export function defaultBom() {
  return [
    { id: 'frame', name: 'Your glasses frame and lenses (existing)', component: 'frame', qty: 1, unit: 0, include: true, sourced: true, weight: 25, weightBasis: 'measured', weightNote: 'Weigh your glasses on a kitchen scale and enter it. 25 g is a placeholder; Ray-Ban Meta smart glasses weigh about 48.6 g for comparison.', weightSources: [S.rbMeta], note: 'Already owned: no cost.', sources: [] },
    { id: 'oled', name: 'Micro-OLED 0.23″ 640×400 panel', component: 'oled', qty: 1, unit: 166, include: true, sourced: true, weight: 1.5, weightBasis: 'estimate', weightNote: 'No published weight found; bare panel with FPC.',
      note: 'Average of three panel listings ($139 / $159 / $199). Kits that include an HDMI board run $275–$599.', sources: [S.dmPanel, S.bonanza, S.walmart, S.tindieKit, S.dmKit] },
    { id: 'driver', name: 'HDMI driver board', component: 'driver', qty: 1, unit: 199, include: true, sourced: true, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'FR-4 board volume × 1.85 g/cm³ + 1.5 g of components (estimate). The real DMRXHMB board is likely larger.',
      note: 'Generic DisplayModule board; compatibility with your panel is not confirmed. Panel + board kits ($275) can be cheaper.', sources: [S.dmDriver, S.tindieKit] },
    { id: 'ribbon', name: 'FPC ribbon / adapter board', component: 'ribbon', qty: 1, unit: 5, include: true, sourced: false, weight: 0.4, weightBasis: 'estimate', note: 'Estimate. Often bundled with the panel kit.', sources: [] },
    { id: 'collimator', name: 'Collimating asphere f ≈ 12 mm', component: 'collimator', qty: 1, unit: 21.2, include: true, sourced: true, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Modelled lens volume × 2.51 g/cm³ (a thin-lens model is weighed as the equivalent plano-convex BK7 lens).', weightSources: [S.bk7],
      note: 'Average of uncoated and AR-coated ACL1512 (Ø15 mm, larger than the modelled 8 mm aperture). Prices are from an obsolete 2015 Thorlabs catalog page as reported by a web search; I could not open the PDF to verify them, and current prices are likely higher.', sources: [S.acl1512] },
    { id: 'prism', name: '10 mm N-BK7 right-angle prism', component: 'prism', qty: 1, unit: 63, include: true, sourced: true, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Modelled prism volume × 2.51 g/cm³.', weightSources: [S.bk7],
      note: 'Uncoated. Edmund UK lists a similar part at £74.80. Aluminium-hypotenuse versions exist (Newport BRAP13-AV) but no price was retrieved.', sources: [S.newportPrism, S.edmundPrism, S.newportAl] },
    { id: 'arm', name: 'Optics arm to the prism (3D printed)', component: 'arm', qty: 1, unit: 1, include: true, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Tube shell (0.8 mm wall) × 1.24 g/cm³ (typical PLA).', note: 'Estimate: material only. Holds the prism and shields the beam.', sources: [] },
    { id: 'barrel', name: 'Collimator barrel / lens mount (3D printed)', component: 'collimator', qty: 1, unit: 1, include: true, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Barrel tube (0.8 mm wall) × 1.24 g/cm³ (typical PLA).', note: 'Estimate: material only.', sources: [] },
    { id: 'prismMount', name: 'Prism mount bracket (3D printed)', part: 'prismMount', qty: 1, unit: 2, include: true, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Part volume × 1.24 g/cm³ (typical PLA, solid).', note: 'Estimate: filament/resin cost only.', sources: [] },
    { id: 'housing', name: 'Temple display housing (3D printed)', component: 'housing', qty: 1, unit: 5, include: true, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Shell volume (housing minus cavity) × 1.24 g/cm³ (typical PLA, solid walls).', note: 'Estimate: material only.', sources: [] },
    { id: 'battery', name: 'LiPo battery 3.7 V 150 mAh (501230)', part: 'battery', qty: 1, unit: 6.15, include: true, sourced: true, weight: 3.5, weightBasis: 'estimate', weightNote: 'No weight on the listing; typical for this cell size.', note: '5 × 12 × 30 mm cell. Check runtime: the panel and driver draw far more than 150 mAh supports for long.', sources: [S.battery] },
    { id: 'charger', name: 'USB-C LiPo charger board', part: 'charger', qty: 1, unit: 5.95, include: true, sourced: true, weight: 1.5, weightBasis: 'estimate', weightNote: 'Adafruit lists 24.0 × 19.0 × 7.2 mm but no weight.', note: 'Single-unit price. Size from the Adafruit listing.', sources: [S.charger] },
    { id: 'compute', name: 'Raspberry Pi Zero 2 W (HDMI source)', part: 'compute', qty: 1, unit: 15, include: true, sourced: true, weight: 16, weightBasis: 'spec', weightNote: 'Retailer figure; other listings give 9–25 g.', weightSources: [S.piWeight], note: '2021 launch MSRP; retail listings are often $20–$35. 65 × 30 mm board.', sources: [S.piZero] },
    { id: 'imu', name: 'IMU breakout (head tracking)', part: 'imu', qty: 1, unit: 10, include: false, sourced: false, weight: 1, weightBasis: 'estimate', note: 'Optional. Estimate; no price found.', sources: [] },
    { id: 'wiring', name: 'Mini-HDMI flat cable, wire, connectors', qty: 1, unit: 8, include: true, sourced: false, weight: 3, weightBasis: 'estimate', weightNote: 'On-frame share only; a cable to a pocket device is not counted.', note: 'Estimate.', sources: [] },
  ];
}

export function bomTotals(bom) {
  let sourced = 0, estimated = 0, excluded = 0, grams = 0, gramsEstimated = 0, gramsExcluded = 0;
  for (const b of bom) {
    const sub = (Number(b.unit) || 0) * (Number(b.qty) || 0);
    const g = (Number(b.weight) || 0) * (Number(b.qty) || 0);
    if (!b.include) { excluded += sub; gramsExcluded += g; continue; }
    if (b.sourced) sourced += sub; else estimated += sub;
    grams += g;
    if (b.weightBasis === 'estimate') gramsEstimated += g;
  }
  return { sourced, estimated, total: sourced + estimated, excluded, grams, gramsEstimated, gramsExcluded };
}

// ---------------------------------------------------------------- weight

export const DENSITY = { bk7: 2.51, pla: 1.24, fr4: 1.85 }; // g/cm^3

const boxVol = (s) => s.x * s.y * s.z; // mm^3

function lensVolume(collimator, nGlass, f) {
  // plano-convex of the modelled aperture; thin lens -> equivalent spherical lens
  const a = (collimator.glassDiameter ?? 2 * collimator.apertureRadius) / 2;
  const c = collimator.mode === 'thin' ? 1 / (f * (nGlass - 1)) : collimator.c;
  const k = collimator.mode === 'aspheric' ? collimator.k : 0;
  const sag = (r) => { const q = 1 - (1 + k) * c * c * r * r; return q > 0 ? (c * r * r) / (1 + Math.sqrt(q)) : NaN; };
  const sagA = sag(a), te = collimator.edgeThickness ?? 0.8;
  if (!Number.isFinite(sagA)) return 0;
  const faces = collimator.biconvex ? 2 : 1; // equi-convex: both faces curved
  let v = 0; const n = 64;
  for (let i = 0; i < n; i++) { const r = ((i + 0.5) / n) * a; v += 2 * Math.PI * r * (te + faces * (sagA - sag(r))) * (a / n); }
  return v;
}

/**
 * Per-line weights (grams per unit) and positions for the centre of mass.
 * Calculated lines are refreshed from the current geometry unless the user
 * typed a value (autoWeight false).
 */
export function computeWeights(params, system) {
  const { prism, collimator, glasses, driver, oled } = system;
  const calc = {};
  calc.prism = (prism.volumeMm3 / 1000) * DENSITY.bk7;
  calc.fold = system.fold ? (system.fold.volumeMm3 / 1000) * DENSITY.bk7 : 0;
  if (collimator) {
    calc.collimator = (lensVolume({ ...collimator, edgeThickness: params.collimator.edgeThickness, glassDiameter: params.collimator.glassDiameter }, params.collimator.n ?? params.prism.n, collimator.f) / 1000) * (params.collimator.density ?? DENSITY.bk7);
    const len = Math.max(0, collimator.center.clone().sub(oled.center).dot(oled.normal));
    const r = Math.max(collimator.apertureRadius + 0.25, (params.collimator.glassDiameter ?? 0) / 2 + 0.1);
    calc.barrel = ((Math.PI * ((r + 0.8) ** 2 - r * r) * len) / 1000) * DENSITY.pla;
  } else { calc.collimator = 0; calc.barrel = 0; }
  calc.housing = ((boxVol(glasses.housing.size) - boxVol(glasses.cavity.size)) / 1000) * DENSITY.pla;
  if (system.housingShell) {
    // shell walls around each part (the hinge block is one of them)
    const w = system.housingShell.wall;
    calc.housing = (system.housingShell.parts.reduce((s, p) => s + boxVol(p.size) - Math.max(0, p.size.x - 2 * w) * Math.max(0, p.size.y - 2 * w) * Math.max(0, p.size.z - 2 * w), 0) / 1000) * DENSITY.pla;
  } else if (system.hingeBlock) { const s = system.hingeBlock.size, w = 1.2; calc.housing += ((boxVol(s) - Math.max(0, s.x - 2 * w) * Math.max(0, s.y - 2 * w) * Math.max(0, s.z - 2 * w)) / 1000) * DENSITY.pla; }
  const arm = system.arm;
  calc.arm = arm ? ((Math.PI * ((arm.radius + arm.wall) ** 2 - arm.radius ** 2) * arm.length) / 1000) * DENSITY.pla : 0;
  calc.driver = (boxVol(driver.size) / 1000) * DENSITY.fr4 + 1.5;
  const partPos = Object.fromEntries((system.parts ?? []).map((pf) => [pf.part.id, pf]));
  for (const pf of system.parts ?? []) calc[`part:${pf.part.id}`] = (boxVol(pf.size) / 1000) * DENSITY.pla;

  const posOf = (b) => {
    if (b.part && partPos[b.part]) return partPos[b.part].position;
    switch (b.component) {
      case 'oled': return oled.center;
      case 'driver': return driver.center;
      case 'ribbon': return oled.center.clone().lerp(driver.center, 0.5);
      case 'collimator': return collimator ? collimator.center : oled.center;
      case 'prism': return prism.center;
      case 'fold': return system.fold ? system.fold.center : prism.center;
      case 'housing': return glasses.housing.center;
      case 'arm': return arm ? arm.start.clone().lerp(arm.end, 0.5) : prism.center;
      case 'frame': return null; // symmetric: split evenly between sides, placed below
      default: return driver.center; // wiring etc. near the electronics
    }
  };
  const lines = params.bom.map((b) => {
    let grams = Number(b.weight) || 0;
    if (b.weightBasis === 'calc' && b.autoWeight !== false) {
      const key = b.part ? `part:${b.part}` : b.id;
      if (calc[key] != null) grams = Math.round(calc[key] * 100) / 100;
    }
    return { id: b.id, grams, total: grams * (Number(b.qty) || 0), pos: posOf(b), include: b.include };
  });
  // centre of mass and left/right split of everything worn
  let m = 0, mx = 0, my = 0, mz = 0, right = 0, left = 0;
  for (const l of lines) {
    if (!l.include || !l.total) continue;
    m += l.total;
    if (!l.pos) {
      // frame + lenses: on the centre line, roughly a third of the way back along the temples (assumed)
      right += l.total / 2; left += l.total / 2;
      my += l.total * glasses.hingeY; mz += l.total * (glasses.hingeZ - 0.3 * params.frame.templeLength);
      continue;
    }
    mx += l.total * l.pos.x; my += l.total * l.pos.y; mz += l.total * l.pos.z;
    if (l.pos.x < 0) right += l.total; else left += l.total;
  }
  return { lines, grams: m, right, left, com: m ? { x: mx / m, y: my / m, z: mz / m } : null };
}

// World transform of a part, following its attachment.
export function partFrame(part, system) {
  const q = quatFromEulerDeg(part.rot);
  const p = new Vector3(part.pos.x, part.pos.y, part.pos.z);
  let qw = q, pw = p;
  const host = part.attach === 'prism' ? system.prism : part.attach === 'oled' ? system.oled : null;
  if (host) {
    qw = host.quaternion.clone().multiply(q);
    pw = p.clone().applyQuaternion(host.quaternion).add(host.center);
  }
  const size = new Vector3(part.size.x, part.size.y, part.size.z);
  return { position: pw, quaternion: qw, size, matrix: new Matrix4().compose(pw, qw, new Vector3(1, 1, 1)), host };
}

export function hostFrameInverse(host) {
  const qi = host.quaternion.clone().invert();
  return (world) => world.clone().sub(host.center).applyQuaternion(qi);
}

export { Quaternion };

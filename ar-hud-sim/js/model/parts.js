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
    { id: 'charger', name: 'USB-C LiPo charger board', size: { x: 4, y: 18, z: 25 }, pos: { x: 71, y: 6, z: -82 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#2b2b33', blocksLight: true, custom: false },
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
};

// Bill of materials. `part` links to a generic part id, `component` to a
// built-in optical component.
export function defaultBom() {
  return [
    { id: 'oled', name: 'Micro-OLED 0.23″ 640×400 panel', component: 'oled', qty: 1, unit: 166, include: true, sourced: true,
      note: 'Average of three panel listings ($139 / $159 / $199). Kits that include an HDMI board run $275–$599.', sources: [S.dmPanel, S.bonanza, S.walmart, S.tindieKit, S.dmKit] },
    { id: 'driver', name: 'HDMI driver board', component: 'driver', qty: 1, unit: 199, include: true, sourced: true,
      note: 'Generic DisplayModule board; compatibility with your panel is not confirmed. Panel + board kits ($275) can be cheaper.', sources: [S.dmDriver, S.tindieKit] },
    { id: 'ribbon', name: 'FPC ribbon / adapter board', component: 'ribbon', qty: 1, unit: 5, include: true, sourced: false, note: 'Estimate. Often bundled with the panel kit.', sources: [] },
    { id: 'collimator', name: 'Collimating asphere f ≈ 12 mm', component: 'collimator', qty: 1, unit: 21.2, include: true, sourced: true,
      note: 'Average of uncoated and AR-coated ACL1512 (Ø15 mm, larger than the modelled 8 mm aperture). Prices are from an obsolete 2015 Thorlabs catalog page as reported by a web search; I could not open the PDF to verify them, and current prices are likely higher.', sources: [S.acl1512] },
    { id: 'prism', name: '10 mm N-BK7 right-angle prism', component: 'prism', qty: 1, unit: 63, include: true, sourced: true,
      note: 'Uncoated. Edmund UK lists a similar part at £74.80. Aluminium-hypotenuse versions exist (Newport BRAP13-AV) but no price was retrieved.', sources: [S.newportPrism, S.edmundPrism, S.newportAl] },
    { id: 'prismMount', name: 'Prism mount bracket (3D printed)', part: 'prismMount', qty: 1, unit: 2, include: true, sourced: false, note: 'Estimate: filament/resin cost only.', sources: [] },
    { id: 'housing', name: 'Temple display housing (3D printed)', component: 'housing', qty: 1, unit: 5, include: true, sourced: false, note: 'Estimate: material only.', sources: [] },
    { id: 'battery', name: 'LiPo battery 3.7 V 150 mAh (501230)', part: 'battery', qty: 1, unit: 6.15, include: true, sourced: true, note: '5 × 12 × 30 mm cell. Check runtime: the panel and driver draw far more than 150 mAh supports for long.', sources: [S.battery] },
    { id: 'charger', name: 'USB-C LiPo charger board', part: 'charger', qty: 1, unit: 5.95, include: true, sourced: true, note: 'Single-unit price. Board size in the model is an assumption.', sources: [S.charger] },
    { id: 'compute', name: 'Raspberry Pi Zero 2 W (HDMI source)', part: 'compute', qty: 1, unit: 15, include: true, sourced: true, note: '2021 launch MSRP; retail listings are often $20–$35. 65 × 30 mm board.', sources: [S.piZero] },
    { id: 'imu', name: 'IMU breakout (head tracking)', part: 'imu', qty: 1, unit: 10, include: false, sourced: false, note: 'Optional. Estimate; no price found.', sources: [] },
    { id: 'wiring', name: 'Mini-HDMI flat cable, wire, connectors', qty: 1, unit: 8, include: true, sourced: false, note: 'Estimate.', sources: [] },
  ];
}

export function bomTotals(bom) {
  let sourced = 0, estimated = 0, excluded = 0;
  for (const b of bom) {
    const sub = (Number(b.unit) || 0) * (Number(b.qty) || 0);
    if (!b.include) excluded += sub;
    else if (b.sourced) sourced += sub;
    else estimated += sub;
  }
  return { sourced, estimated, total: sourced + estimated, excluded };
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

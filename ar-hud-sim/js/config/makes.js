// "Makes": distinct design philosophies for the same HUD, each built only
// from parts that can be bought (catalog lenses, stock 45-45-90 prisms,
// listed displays and boards). A make defines the hardware and which design
// choices its search may vary; scripts/design-makes.mjs searches those
// choices and stores the best result in makes.tuned.js.

import { baseParams, alignChain } from './defaults.js';
import { computeCollimator, computeOled } from '../optics/OpticalComponents.js';
import { solveFocusDistance, solveFieldFocus } from '../optics/focus.js';
import { assessFocus } from '../optics/Vision.js';
import { TUNED } from './makes.tuned.js';
import { levelImage } from '../optics/orient.js';

const src = {
  yx: { label: 'YX Microdisplay 0.23″ 640×400 kit with HDMI board ($175)', url: 'https://www.yxmicrodisplay.com/products/0-23-inch-640x400-micro-oled-display-3000nits-hdmi-kit' },
  k9: { label: 'eBay K9 right-angle prisms, 2-pack ($9.39)', url: 'https://www.ebay.de/itm/254836009968' },
  k9w: { label: 'Walmart JZROCKER K9 prism ($8.49)', url: 'https://www.walmart.com/c/kp/right-angle-prisms' },
  acl: { label: 'Thorlabs ACL1512 2015 catalog ($16.20, unverified)', url: 'https://www.thorlabs.com/catalogpages/Obsolete/2015/ACL1210.pdf' },
  eo125: { label: 'Edmund 12 mm Ø × 12.5 mm FL molded asphere (NT$1,120 ≈ $35)', url: 'https://edmundoptics.com.tw/p/12mm-dia-x-12mm-fl-uncoated-molded-aspheric-condenser-lens/30545' },
  eo19: { label: 'Edmund 12 mm Ø × 19 mm FL asphere (price not retrieved)', url: 'https://www.edmundoptics.com/p/12mm-dia-x-19mm-fl-aspheric-condenser-lens/47189/' },
  ssd: { label: 'BuyDisplay 0.49″ 64×32 OLED, I2C ($2.65)', url: 'https://www.buydisplay.com/i2c-white-0-49-inch-oled-display-module-64x32-arduino-raspberry-pi' },
  esp: { label: 'PedalPCB ESP32-C3 Super Mini ($8.00)', url: 'https://www.pedalpcb.com/product/6-1-2/' },
  espW: { label: 'ESP32-C3 SuperMini, ≈2.2 g, 22.5 × 18 mm (listing)', url: 'https://sigmanortec.ro/en/esp32-c3-supermini-development-board-33v-wifi-bluetooth' },
  piW: { label: 'Kubii: Pi Zero 2 W, 16 g', url: 'https://kubii.com/en/nano-computers/3455-raspberry-pi-zero-2-w-wh.html' },
  pi: { label: 'Raspberry Pi Zero 2 W launch price ($15, 2021)', url: 'https://betanews.com/2021/10/28/raspberry-pi-zero-2-w' },
  bat: { label: 'eBay 501230 150 mAh LiPo ($6.15)', url: 'https://www.ebay.com/itm/174683669832' },
  chg: { label: 'Adafruit Micro-Lipo USB-C #4410 ($5.95)', url: 'https://www.adafruit.com/product/4410' },
  rb: { label: 'Ray-Ban Meta 48.6 g (SHI)', url: 'https://www.uk.shi.com/Product/47381750/Ray-Ban---Meta-Smart-glasses' },
  bs: { label: 'Edmund 25 mm 30R/70T plate beamsplitter, 1 mm ($61)', url: 'https://www.edmundoptics.com/p/25mm-diameter-30r70t-plate-beamsplitter/5238/' },
  noa: { label: 'Edmund NOA61 optical adhesive, 1 oz ($38)', url: 'https://www.edmundoptics.com/p/1-oz-application-bottle-of-noa-61/4209/' },
  noaT: { label: 'Thorlabs NOA61 ($40.70)', url: 'https://www.thorlabs.us/_QLPopup.cfm?PN=NOA61' },
  crystal: { label: 'Esslinger domed mineral watch crystal, 1.0 mm ($3.95)', url: 'https://www.esslinger.com/domed-watch-crystal-round-mineral-glass-crystal-1-00-mm-thick/' },
  curvedPR: { label: 'Alien Photonics custom curved partial reflectors (from €75)', url: 'https://findlight.net/uploads/products/datasheet/output-couplers-partial-reflectors-alien-photonics_1721050359.pdf' },
  lumus: { label: 'Lumus: reflective (geometric) waveguides, licensed to OEMs', url: 'https://lumusvision.com' },
};

// Catalog collimators (focal length, glass diameter). Only listed parts.
export const LENSES = [
  { id: 'acl1210', name: 'Thorlabs ACL1210 asphere, f 10.5 mm, Ø12', f: 10.5, dia: 12, unit: 16.2, sourced: false, sources: [src.acl], note: 'Price assumed equal to the ACL1512 (same series); not retrieved.' },
  { id: 'acl1512', name: 'Thorlabs ACL1512 asphere, f 12 mm, Ø15', f: 12, dia: 15, unit: 16.2, sourced: true, sources: [src.acl], note: '2015 catalog price reported by search; not verified, likely higher today.' },
  { id: 'eo125', name: 'Edmund molded asphere, f 12.5 mm, Ø12', f: 12.5, dia: 12, unit: 35, sourced: true, sources: [src.eo125], note: 'Converted from NT$1,120.' },
  { id: 'eo19', name: 'Edmund asphere, f 19 mm, Ø12', f: 19, dia: 12, unit: 35, sourced: false, sources: [src.eo19], note: 'Price assumed equal to the 12.5 mm part; not retrieved.' },
];
// Stock K9 45-45-90 prisms (leg = height).
export const PRISMS = [
  { size: 5, unit: 4.7, sourced: false }, { size: 6, unit: 4.7, sourced: false },
  { size: 8, unit: 4.7, sourced: true }, { size: 10, unit: 4.7, sourced: true }, { size: 12, unit: 4.7, sourced: false },
];

const FILAMENT_PER_G = 0.025; // ~$25/kg PLA (assumed, unsourced)

function line(o) { return { qty: 1, include: true, sources: [], note: '', ...o }; }

// Frame + lenses of your own glasses (weigh them!)
const frameLine = () => line({ id: 'frame', name: 'Your glasses frame and lenses (existing)', component: 'frame', unit: 0, sourced: true, weight: 25, weightBasis: 'measured', weightNote: 'Placeholder: weigh your glasses and enter it.', weightSources: [src.rb], note: 'Already owned.' });
const printed = (id, name, component, part) => line({ id, name, component, part, unit: 0, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, costPerGram: FILAMENT_PER_G, weightNote: 'Volume × 1.24 g/cm³ (PLA). Cost = grams × $0.025 (assumed filament price).' });

function yxKitLines() {
  return [
    line({ id: 'oled', name: 'YX 0.23″ 640×400 Micro-OLED + HDMI board kit', component: 'oled', unit: 175, sourced: true, sources: [src.yx], weight: 1.5, weightBasis: 'estimate', weightNote: 'Panel; no published weight.', note: 'Kit includes the HDMI driver board (priced here). Board size not published: the 22 × 10 mm board in the model is an assumption.' }),
    line({ id: 'driver', name: 'HDMI driver board (in kit)', component: 'driver', unit: 0, sourced: true, sources: [src.yx], weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'FR-4 board volume × 1.85 g/cm³ + 1.5 g components (estimate).' }),
  ];
}

function commonOptics(lens, prism) {
  return [
    line({ id: 'collimator', name: lens.name, component: 'collimator', unit: lens.unit, sourced: lens.sourced, sources: lens.sources, note: lens.note, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Full-diameter lens volume × 2.51 g/cm³.' }),
    line({ id: 'prism', name: `K9 right-angle prism ${prism.size} mm`, component: 'prism', unit: prism.unit, sourced: prism.sourced, sources: [src.k9, src.k9w], note: prism.sourced ? 'Half of a 2-pack.' : 'Size not in the retrieved listings; price assumed like the 8/10 mm parts.', weight: 0, weightBasis: 'calc', autoWeight: true }),
    printed('barrel', 'Lens barrel (printed)', 'collimator'),
    printed('arm', 'Optics arm to the prism (printed)', 'arm'),
    printed('housing', 'Temple housing (printed)', 'housing'),
    mountLine('prism'),
  ];
}


// Waveguide (Lumen) optics: a hand-made geometric waveguide. Its partial
// reflectors are slices of a stock 30R/70T beamsplitter plate bonded inside
// clear glass; no retail part exists, so the cutting/polishing is an estimate.
function waveguideOptics(lens) {
  return [
    line({ id: 'collimator', name: lens.name, component: 'collimator', unit: lens.unit, sourced: lens.sourced, sources: lens.sources, note: lens.note, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Full-diameter lens volume × 2.51 g/cm³.' }),
    line({ id: 'prism', name: 'Waveguide plate with embedded facets (hand-made)', component: 'prism', unit: 0, sourced: false, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Plate volume × 2.51 g/cm³ (BK7-like glass).', note: 'Assembled from the lines below. No hobby-scale waveguide is sold: Lumus-type waveguides are made by OEMs under licence.', sources: [src.lumus] }),
    line({ id: 'facetGlass', name: 'Partial reflector for the facets (30R/70T plate, sliced)', unit: 61, sourced: true, sources: [src.bs], weight: 0, weightBasis: 'calc', note: 'Its coating reflects ~30% at every angle (not angle-selective): the tracer models it that way, ghosts included.' }),
    line({ id: 'guideGlass', name: 'Clear glass for the plate body (slides / B270 offcuts)', unit: 10, sourced: false, weight: 0, weightBasis: 'calc', note: 'Estimate, not retrieved.' }),
    line({ id: 'adhesive', name: 'NOA61 UV optical adhesive (facet bonds only)', unit: 38, sourced: true, sources: [src.noa, src.noaT], weight: 0.1, weightBasis: 'estimate', note: 'Index 1.56 ≈ glass, so bonds inside the stack are invisible. Do NOT bond the plate faces to the lens: TIR needs the air gap.' }),
    line({ id: 'guideFab', name: 'Cut the bonded stack at the facet angle + polish', unit: 60, sourced: false, weight: 0, weightBasis: 'calc', note: 'Estimate for a local glass/lapidary shop, or your own lapping kit. Facet angle tolerance matters (≈ arcminutes for a sharp image at 640 px).' }),
    line({ id: 'guideClip', name: 'Rim clip holding the plate 0.4 mm behind the lens', component: 'prism', unit: 0.05, sourced: false, weight: 0.5, weightBasis: 'estimate', note: 'Printed; touches the plate only at its edges.' }),
    printed('barrel', 'Lens barrel (printed)', 'collimator'),
    printed('arm', 'Input tube to the waveguide (printed)', 'arm'),
    printed('housing', 'Temple housing (printed)', 'housing'),
  ];
}

// Mirage optics: a partially mirrored thin glass shell behind the lens.
// Standoff pins (Ø1.5 mm glass rod or printed pins) glued between the
// combiner and the back of the lens: the frame carries the optic.
const mountLine = (what) => line({ id: 'lensMount', name: `Standoff pins + UV glue bonding the ${what} to the lens`, component: 'prism', unit: 6, sourced: false, weight: 0.1, weightBasis: 'estimate', note: what === 'patch' ? 'Estimate. Pins on the half of the rim away from the display; glue only the pin ends so the air gap behind the coating stays clear.' : 'Estimate. Pins on the prism corners nearest the lens, clear of the beam.' });

function patchOptics(lens) {
  return [
    line({ id: 'collimator', name: lens.name, component: 'collimator', unit: lens.unit, sourced: lens.sourced, sources: lens.sources, note: lens.note, weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Full-diameter lens volume × 2.51 g/cm³.' }),
    line({ id: 'prism', name: 'Mirror patch: 1 mm glass shell (domed or flat watch crystal, cut down)', component: 'prism', unit: 3.95, sourced: true, sources: [src.crystal], weight: 0, weightBasis: 'calc', autoWeight: true, weightNote: 'Shell area × thickness × 2.5 g/cm³.', note: 'Dome radii are not published: measure the sag (R = d²/8s + s/2) and pick the crystal closest to the design radius.' }),
    line({ id: 'patchCoat', name: 'Partial-mirror coating on its concave face (R ≈ 30%)', unit: 40, sourced: false, sources: [src.curvedPR], weight: 0, weightBasis: 'calc', note: 'Estimate: a small-batch vacuum coating or a DIY partial silvering. A ready-made curved partial reflector costs from €75 (custom).' }),
    mountLine('patch'),
    printed('barrel', 'Lens barrel (printed)', 'collimator'),
    printed('housing', 'Temple housing (printed)', 'housing'),
  ];
}

// ---------------------------------------------------------------- makes

export const MAKES = [
  {
    id: 'atlas', name: 'Atlas', tagline: 'Tethered optics-first',
    idea: 'Puts the money into optics. A 10–12 mm prism and a wide lens give a large eye-box. No computer or battery is worn: the HUD plugs into your phone or PC over HDMI.',
    vars: { prism: [8, 10, 12], lens: ['acl1512', 'eo125', 'acl1210', 'eo19'], flip: [false, true], stop: [4, 12], az: [6, 44], el: [-28, 32], tilt: [0, 10], inset: [-8, 14] },
    electronics: () => ({ parts: [], bom: [line({ id: 'cable', name: 'HDMI cable to your phone/PC', unit: 8, sourced: false, weight: 3, weightBasis: 'estimate', weightNote: 'On-frame share of the cable.', note: 'Estimate. Your phone/PC is the HDMI source (not counted).' })] }),
    display: 'yx',
  },
  {
    id: 'solo', name: 'Solo', tagline: 'Standalone, nothing to plug in',
    idea: 'Everything is on the frame: a Raspberry Pi Zero 2 W behind the left ear as the HDMI source, with the battery and charger on the left temple to balance the optics on the right.',
    vars: { prism: [6, 8, 10], lens: ['acl1512', 'acl1210', 'eo125', 'eo19'], flip: [false, true], stop: [4, 12], az: [6, 44], el: [-28, 32], tilt: [0, 10], inset: [-8, 14] },
    electronics: () => ({
      parts: [
        { id: 'compute', name: 'Raspberry Pi Zero 2 W', size: { x: 5, y: 30, z: 65 }, pos: { x: 72, y: -4, z: -128 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#1f6b3a', blocksLight: true, custom: false },
        { id: 'battery', name: 'LiPo 150 mAh (501230)', size: { x: 5, y: 12, z: 30 }, pos: { x: 71, y: 6, z: -60 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#3c6fb0', blocksLight: true, custom: false },
        { id: 'charger', name: 'USB-C LiPo charger', size: { x: 7.2, y: 19, z: 24 }, pos: { x: 73, y: 6, z: -90 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#2b2b33', blocksLight: true, custom: false },
      ],
      bom: [
        line({ id: 'compute', name: 'Raspberry Pi Zero 2 W', part: 'compute', unit: 15, sourced: true, sources: [src.pi], weight: 16, weightBasis: 'spec', weightSources: [src.piW], note: 'Launch MSRP; retail often $20–35.' }),
        line({ id: 'battery', name: 'LiPo 150 mAh (501230)', part: 'battery', unit: 6.15, sourced: true, sources: [src.bat], weight: 3.5, weightBasis: 'estimate', note: 'Runtime is short with a Pi + display (well under an hour, estimate).' }),
        line({ id: 'charger', name: 'USB-C LiPo charger', part: 'charger', unit: 5.95, sourced: true, sources: [src.chg], weight: 1.5, weightBasis: 'estimate' }),
        line({ id: 'wiring', name: 'Mini-HDMI flex + power wiring', unit: 6, sourced: false, weight: 2, weightBasis: 'estimate' }),
      ],
    }),
    display: 'yx',
  },
  {
    id: 'kestrel', name: 'Kestrel', tagline: 'Value monochrome',
    idea: 'Swaps the $175 micro-OLED for a $2.65 0.49″ 64×32 I2C OLED driven by an ESP32-C3. You get a coarse, bright notification HUD instead of a 640×400 screen, and it is self-powered and very cheap.',
    vars: { prism: [8, 10, 12], lens: ['eo19', 'acl1512', 'eo125'], flip: [false, true], stop: [4, 12], az: [6, 44], el: [-28, 32], tilt: [0, 10], inset: [-8, 14] },
    electronics: () => ({
      parts: [
        { id: 'battery', name: 'LiPo 150 mAh (501230)', size: { x: 5, y: 12, z: 30 }, pos: { x: 71, y: 6, z: -60 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#3c6fb0', blocksLight: true, custom: false },
        { id: 'charger', name: 'USB-C LiPo charger', size: { x: 7.2, y: 19, z: 24 }, pos: { x: 73, y: 6, z: -90 }, rot: { yaw: 0, pitch: 0, roll: 0 }, attach: null, color: '#2b2b33', blocksLight: true, custom: false },
      ],
      bom: [
        line({ id: 'battery', name: 'LiPo 150 mAh (501230)', part: 'battery', unit: 6.15, sourced: true, sources: [src.bat], weight: 3.5, weightBasis: 'estimate', note: 'An ESP32-C3 + small OLED draw far less than a Pi: hours of runtime (estimate).' }),
        line({ id: 'charger', name: 'USB-C LiPo charger', part: 'charger', unit: 5.95, sourced: true, sources: [src.chg], weight: 1.5, weightBasis: 'estimate' }),
        line({ id: 'wiring', name: 'Wire + connectors', unit: 3, sourced: false, weight: 1, weightBasis: 'estimate' }),
      ],
    }),
    display: 'ssd0.49',
  },
  {
    id: 'wisp', name: 'Wisp', tagline: 'Featherweight, out of sight',
    idea: 'The smallest stock prism (5–6 mm) and a compact housing keep mass down and the line of sight clear. It trades eye-box size for that, and it is tethered over HDMI like Atlas.',
    vars: { prism: [5, 6, 8], lens: ['acl1210', 'eo125', 'acl1512', 'eo19'], flip: [false, true], stop: [3, 8], az: [6, 44], el: [-28, 32], tilt: [0, 10], inset: [-8, 14] },
    electronics: () => ({ parts: [], bom: [line({ id: 'cable', name: 'Thin HDMI cable to your phone/PC', unit: 8, sourced: false, weight: 2.5, weightBasis: 'estimate', note: 'Estimate. Your phone/PC is the HDMI source (not counted).' })] }),
    display: 'yx',
  },
  {
    id: 'mirage', name: 'Mirage', tagline: 'Mirror on the lens (Focals-style)', kind: 'patch',
    idea: 'The display and lens sit in the temple and shine across the inside of the lens onto a small, partly mirrored glass patch behind it, which reflects the image into your eye. Nothing sticks out and the frame keeps its normal shape. Focals did this with a laser scanner and a holographic film; this version uses parts you can get: the micro-OLED, a stock asphere and a coated watch-crystal patch.',
    vars: { lens: ['eo125', 'acl1512', 'acl1210', 'eo19'], flip: [false, true], stop: [4, 11], az: [6, 44], el: [-28, 32], fold: [70, 110], stilt: [-20, 20], radius: [80, 3000], throw: [18, 40], tx: [-20, 20], ty: [-20, 20], diam: [8, 16] },
    electronics: () => ({ parts: [], bom: [line({ id: 'cable', name: 'Thin HDMI cable to your phone/PC', unit: 8, sourced: false, weight: 2.5, weightBasis: 'estimate', note: 'Estimate. Your phone/PC is the HDMI source (not counted).' })] }),
    display: 'yx',
  },
  {
    id: 'lumen', name: 'Lumen', tagline: 'See-through waveguide (your reference)', kind: 'waveguide',
    idea: 'Modelled on your reference images: the projector sits in the temple, and a thin glass waveguide behind the lens carries the image inward by total internal reflection. Embedded partial mirrors then send it into your eye, so nothing hangs in front of the lens. Retail waveguides use a diffraction grating or factory-coated facets. Here the facets are cut from a stock beamsplitter, because a grating cannot be ray-traced or bought for a hobby build.',
    vars: { lens: ['acl1512', 'eo125', 'acl1210', 'eo19'], flip: [false, true], stop: [3, 10], az: [6, 44], el: [-28, 32], thick: [2.5, 4.5], guide: [50, 64], facets: [2, 5], spacing: [2.5, 6], height: [9, 16], margin: [-8, 0] },
    electronics: () => ({ parts: [], bom: [line({ id: 'cable', name: 'Thin HDMI cable to your phone/PC', unit: 8, sourced: false, weight: 2.5, weightBasis: 'estimate', note: 'Estimate. Your phone/PC is the HDMI source (not counted).' })] }),
    display: 'yx',
  },
];

// Build full parameters for a make and a vector of design choices.
export function buildMake(make, v, opts = {}) {
  let p = baseParams();
  const lens = LENSES.find((l) => l.id === v.lens) ?? LENSES[1];
  const prism = PRISMS.find((x) => x.size === v.prism) ?? PRISMS[3];
  p.prism = { ...p.prism, size: prism.size, height: prism.size, angle: 45, coating: 'none' };
  const guided = make.kind === 'waveguide', patched = make.kind === 'patch';
  if (patched) {
    p.patch = { ...p.patch, enabled: true, radius: v.radius, diameter: v.diam, foldDeg: v.fold, sourceTiltDeg: v.stilt, throw: v.throw, reflectance: 0.3 };
  }
  if (guided) {
    p.waveguide = { ...p.waveguide, enabled: true, coating: 'plain', facetR: 0.3, thickness: v.thick, guideAngle: v.guide, facets: Math.round(v.facets), facetSpacing: v.spacing, height: v.height, templeMargin: v.margin };
  }
  p.collimator = { ...p.collimator, enabled: true, mode: 'aspheric', conicK: -0.8, focalLength: lens.f, aperture: Math.min(v.stop, lens.dia), glassDiameter: lens.dia, edgeThickness: 0.8, flip: !!v.flip, tiltX: patched ? v.tx : 0, tiltY: patched ? v.ty : 0 };
  if (make.display === 'ssd0.49') {
    p.oled = { ...p.oled, diagonalIn: 0.49, resX: 64, resY: 32, housingMarginX: 3.8, housingMarginY: 6.4, housingDepth: 3, peakLuminance: 150 };
    p.driver = { ...p.driver, length: 22.5, height: 18, thickness: 1.0 }; // ESP32-C3 SuperMini as the display driver
  } else {
    p.oled = { ...p.oled, peakLuminance: 3000 };
  }
  p.frame = { ...p.frame, housingAuto: true };
  p.intent = { ...p.intent, azimuth: v.az, elevation: v.el, entryTiltDeg: v.tilt, oledInset: v.inset, prismClearance: 1 };
  p = alignChain(p);
  // focus: start at the paraxial front focal distance, then let the tracer
  // find the distance that gives the wearer's relaxed-eye vergence
  const c = computeCollimator(p.collimator, computeOled(p.oled), p.prism.n);
  if (c?.valid) p.collimator.distance = c.frontFocalDistance;
  if (opts.bestFocus !== false) {
    const target = assessFocus({ Vx: 0, Vy: 0 }, p.eye).targetVergence;
    const fz = solveFocusDistance(p, target, { tol: 0.05, maxIter: 5 });
    if (fz.distance != null && Number.isFinite(fz.distance)) p.collimator.distance = Math.round(fz.distance * 1000) / 1000;
    if (opts.fieldFocus !== false) {
      const ff = solveFieldFocus(p, { span: 1.5, iters: 9 });
      if (ff.ok) p.collimator.distance = Math.round(ff.distance * 1000) / 1000;
    }
  }
  // roll the display so the image reads level and unmirrored for the eye
  if (opts.level !== false) levelImage(p);
  const el = make.electronics();
  p.parts = [...el.parts];
  const displayLines = make.display === 'ssd0.49'
    ? [
      line({ id: 'oled', name: '0.49″ 64×32 I2C OLED module', component: 'oled', unit: 2.65, sourced: true, sources: [src.ssd], weight: 1, weightBasis: 'estimate', note: '11.18 × 5.58 mm active area, 15 × 12 mm board (listings).' }),
      line({ id: 'driver', name: 'ESP32-C3 Super Mini (drives the OLED)', component: 'driver', unit: 8, sourced: true, sources: [src.esp], weight: 2.2, weightBasis: 'spec', weightSources: [src.espW], note: 'Typical $3–8.' }),
    ]
    : yxKitLines();
  p.bom = [frameLine(), ...displayLines, ...(patched ? patchOptics(lens) : guided ? waveguideOptics(lens) : commonOptics(lens, prism)), ...el.bom];
  p.make = { id: make.id, name: make.name, vars: v };
  return p;
}

// Printed-part cost follows its calculated weight.
export function applyPrintedCosts(params) {
  for (const b of params.bom) if (b.costPerGram) b.unit = Math.round(b.costPerGram * (b.weight || 0) * 100) / 100;
}

export function tunedParams(makeId) {
  const make = MAKES.find((m) => m.id === makeId);
  const v = TUNED[makeId]?.vars;
  return make && v ? buildMake(make, v) : null;
}

export { TUNED };

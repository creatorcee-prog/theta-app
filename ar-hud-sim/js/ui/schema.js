// Control definitions. tag: spec (from the brief), assumed (adjustable
// assumption), design (placement chosen by the alignment helper or user).

const SECTION_LIST = [
  {
    id: 'optics', title: 'Optical parameters', open: true,
    controls: [
      { key: 'prism.angle', label: 'Prism angle', min: 20, max: 70, step: 0.1, unit: '°', tag: 'spec', help: 'Angle between entry face and hypotenuse (= hypotenuse incidence for a ray entering square to the entry face). 45° is the 45-45-90 prism; other values keep the right angle and change the fold.' },
      { key: 'oled.resX', label: 'OLED resolution (H)', min: 160, max: 1920, step: 2, unit: 'px', tag: 'spec' },
      { key: 'oled.resY', label: 'OLED resolution (V)', min: 100, max: 1200, step: 2, unit: 'px', tag: 'spec' },
      { key: 'oled.diagonalIn', label: 'OLED diagonal', min: 0.13, max: 0.7, step: 0.01, unit: 'in', tag: 'spec', help: 'Active area derived from diagonal and pixel aspect (square pixels assumed).' },
      { key: 'prism.size', label: 'Prism leg (entry face)', min: 2, max: 25, step: 0.1, unit: 'mm', tag: 'spec', help: 'Exit-face leg = leg × tan(prism angle).' },
      { key: 'prism.height', label: 'Prism height (extrusion)', min: 2, max: 25, step: 0.1, unit: 'mm', tag: 'spec' },
      { key: 'prism.n', label: 'BK7 refractive index', min: 1.4, max: 1.9, step: 0.001, unit: '', tag: 'spec', help: 'At 550 nm. Also used for the real collimator lens.' },
      { key: 'targets.hfov', label: 'Horizontal FOV target', min: 5, max: 70, step: 1, unit: '°', tag: 'spec' },
      { key: 'targets.vfov', label: 'Vertical FOV target', min: 5, max: 50, step: 1, unit: '°', tag: 'spec' },
      { key: 'oled.brightness', label: 'OLED brightness', min: 0, max: 100, step: 1, unit: '%', tag: 'spec' },
      { key: 'collimator.focalLength', label: 'Collimator focal length', min: 2, max: 50, step: 0.1, unit: 'mm', tag: 'spec', after: 'refocus' },
      { key: 'eye.eyeRelief', label: 'Eye relief', min: 8, max: 30, step: 0.5, unit: 'mm', tag: 'assumed', help: 'Lens back surface to corneal vertex.' },
    ],
  },
  {
    id: 'hud', title: 'Projected content',
    controls: [
      { key: 'hud.mode', label: 'Content', type: 'select', options: [['text', 'Text + arrow'], ['grid', 'Test pattern (grid + corners)'], ['image', 'Uploaded image']], tag: 'design' },
      { key: 'hud.line1', label: 'Large line', type: 'text', tag: 'design', showIf: (p) => p.hud.mode === 'text' },
      { key: 'hud.line2', label: 'Line 2', type: 'text', tag: 'design', showIf: (p) => p.hud.mode === 'text' },
      { key: 'hud.line3', label: 'Line 3', type: 'text', tag: 'design', showIf: (p) => p.hud.mode === 'text' },
      { key: 'hud.textSize', label: 'Text size', min: 30, max: 240, step: 1, unit: 'px', tag: 'design', showIf: (p) => p.hud.mode === 'text', help: 'At 640 px display width.' },
      { key: 'hud.arrow', label: 'Show turn arrow', type: 'toggle', tag: 'design', showIf: (p) => p.hud.mode === 'text' },
      { key: 'hud.border', label: 'Show border', type: 'toggle', tag: 'design', showIf: (p) => p.hud.mode === 'text' },
      { key: 'hud.image', label: 'Image', type: 'file', tag: 'design', showIf: (p) => p.hud.mode === 'image' },
      { key: 'hud.imageFit', label: 'Image fit', type: 'select', options: [['contain', 'Fit inside display'], ['cover', 'Fill display (crop)'], ['stretch', 'Stretch']], tag: 'design', showIf: (p) => p.hud.mode === 'image' },
      { key: 'hud.color', label: 'Colour', type: 'color', tag: 'design', showIf: (p) => p.hud.mode !== 'image' },
      { key: 'hud.background', label: 'Background (black = pixels off)', type: 'color', tag: 'design' },
      { key: 'hud.driverFlip', label: 'Driver mirrors image', type: 'toggle', tag: 'design', help: 'Pre-flips the frame buffer to undo the prism’s mirror image.' },
    ],
  },
  {
    id: 'driver', title: 'Driver board & cable',
    controls: [
      { key: 'driver.pos.x', label: 'Board X', min: -100, max: 20, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'driver.pos.y', label: 'Board Y', min: -40, max: 40, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'driver.pos.z', label: 'Board Z', min: -150, max: 20, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'driver.length', label: 'Board length', min: 5, max: 60, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'driver.height', label: 'Board height', min: 3, max: 40, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'driver.thickness', label: 'PCB thickness', min: 0.4, max: 4, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'driver.ribbonWidth', label: 'Ribbon cable width', min: 1, max: 10, step: 0.1, unit: 'mm', tag: 'assumed' },
    ],
  },
  {
    id: 'align', title: 'Alignment helper',
    controls: [
      { key: 'intent.prismClearance', label: 'Prism gap to lens', min: 0, max: 10, step: 0.1, unit: 'mm', tag: 'design', help: 'The helper aims the chain at the target azimuth/elevation (Coverage targets) and only sets positions; the tracer decides what works.' },
      { key: 'intent.oledInset', label: 'OLED inset from housing wall', min: 0, max: 8, step: 0.1, unit: 'mm', tag: 'design' },
    ],
  },
  {
    id: 'collimator', title: 'Collimating lens',
    controls: [
      { key: 'collimator.enabled', label: 'Lens installed', type: 'toggle', tag: 'design' },
      { key: 'collimator.mode', label: 'Lens model', type: 'select', options: [['thin', 'Ideal thin lens'], ['spherical', 'Plano-convex, spherical (real surfaces)'], ['aspheric', 'Plano-convex, conic asphere (real surfaces)']], tag: 'assumed' },
      { key: 'collimator.distance', label: 'Distance from OLED', min: 0.5, max: 50, step: 0.05, unit: 'mm', tag: 'design', after: 'refocus' },
      { key: 'collimator.aperture', label: 'Clear aperture', min: 1, max: 20, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'collimator.conicK', label: 'Conic constant k', min: -3, max: 1, step: 0.01, unit: '', tag: 'assumed', showIf: (p) => p.collimator.mode === 'aspheric' },
      { key: 'collimator.edgeThickness', label: 'Edge thickness', min: 0.3, max: 3, step: 0.1, unit: 'mm', tag: 'assumed', showIf: (p) => p.collimator.mode !== 'thin' },
      { key: 'collimator.flip', label: 'Convex side faces OLED', type: 'toggle', tag: 'design', showIf: (p) => p.collimator.mode !== 'thin' },
      { key: 'collimator.offsetX', label: 'Decentre X', min: -6, max: 6, step: 0.05, unit: 'mm', tag: 'design' },
      { key: 'collimator.offsetY', label: 'Decentre Y', min: -6, max: 6, step: 0.05, unit: 'mm', tag: 'design' },
      { key: 'collimator.tiltX', label: 'Tilt about X', min: -45, max: 45, step: 0.1, unit: '°', tag: 'design' },
      { key: 'collimator.tiltY', label: 'Tilt about Y', min: -45, max: 45, step: 0.1, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'prism', title: 'Prism placement',
    controls: [
      { key: 'prism.coating', label: 'Hypotenuse', type: 'select', options: [['none', 'Uncoated (TIR only)'], ['mirror', 'Aluminium mirror, R = 0.90']], tag: 'assumed' },
      { key: 'prism.pos.x', label: 'Position X', min: -100, max: 20, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.pos.y', label: 'Position Y', min: -40, max: 40, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.pos.z', label: 'Position Z', min: -60, max: 40, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.rot.yaw', label: 'Yaw', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'prism.rot.pitch', label: 'Pitch', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'prism.rot.roll', label: 'Roll', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'oled', title: 'Micro-OLED placement',
    controls: [
      { key: 'oled.pos.x', label: 'Position X', min: -100, max: 20, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.pos.y', label: 'Position Y', min: -40, max: 40, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.pos.z', label: 'Position Z', min: -80, max: 40, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.rot.yaw', label: 'Yaw', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.rot.pitch', label: 'Pitch', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.rot.roll', label: 'Roll', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.emissionHalfAngle', label: 'Emission half-angle', min: 1, max: 89, step: 1, unit: '°', tag: 'assumed', help: 'Lambertian emission sampled inside this cone.' },
      { key: 'oled.peakLuminance', label: 'Peak luminance', min: 100, max: 5000, step: 50, unit: 'cd/m²', tag: 'assumed' },
      { key: 'oled.housingMarginX', label: 'Housing margin (width)', min: 0, max: 10, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'oled.housingMarginY', label: 'Housing margin (height)', min: 0, max: 10, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'oled.housingDepth', label: 'Housing depth', min: 0.5, max: 10, step: 0.1, unit: 'mm', tag: 'assumed' },
    ],
  },
  {
    id: 'eye', title: 'Eye',
    controls: [
      { key: 'eye.ipd', label: 'Interpupillary distance', min: 54, max: 74, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'eye.dx', label: 'Right eye offset X (world)', min: -8, max: 8, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.dy', label: 'Right eye offset Y', min: -8, max: 8, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.eyeRelief', label: 'Eye relief', min: 8, max: 30, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'eye.constants.vertexToRotationCenter', label: 'Cornea → rotation centre', min: 10, max: 17, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.constants.entrancePupilDepth', label: 'Entrance pupil depth', min: 2, max: 4.5, step: 0.05, unit: 'mm', tag: 'assumed', help: 'Behind the corneal vertex.' },
      { key: 'eye.constants.eyeballRadius', label: 'Eyeball radius', min: 10, max: 14, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.constants.corneaRadius', label: 'Cornea radius', min: 6.5, max: 9, step: 0.05, unit: 'mm', tag: 'assumed' },
      { key: 'eye.pupilDiameter', label: 'Pupil diameter', min: 2, max: 8, step: 0.1, unit: 'mm', tag: 'assumed', help: '~2–3 mm in daylight, 4 mm indoors, up to 8 mm dark.' },
      { key: 'eye.gazeYaw', label: 'Gaze yaw (temporal +)', min: -45, max: 50, step: 0.5, unit: '°', tag: 'design', after: 'lookAtHud' },
      { key: 'eye.gazePitch', label: 'Gaze pitch (up +)', min: -45, max: 45, step: 0.5, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'frame', title: 'Frame dimensions',
    controls: [
      { key: 'frame.lensWidth', label: 'Lens width', min: 38, max: 64, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensHeight', label: 'Lens height', min: 26, max: 52, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensCorner', label: 'Lens corner radius', min: 2, max: 25, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensThickness', label: 'Lens thickness', min: 0.5, max: 6, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.specLensN', label: 'Spectacle lens index', min: 1.4, max: 1.8, step: 0.001, unit: '', tag: 'assumed', help: 'CR-39 1.498, polycarbonate 1.586.' },
      { key: 'frame.bridge', label: 'Bridge width', min: 12, max: 26, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.rimWidth', label: 'Rim width', min: 0.5, max: 8, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.rimDepth', label: 'Rim depth', min: 1, max: 10, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.endpiece', label: 'Endpiece (lens → hinge)', min: 2, max: 20, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.hingeY', label: 'Hinge height', min: -15, max: 18, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.templeThickness', label: 'Temple thickness', min: 2, max: 12, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.templeHeight', label: 'Temple height', min: 2, max: 20, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.templeSplayDeg', label: 'Temple splay', min: -5, max: 15, step: 0.5, unit: '°', tag: 'assumed' },
      { key: 'frame.templeLength', label: 'Temple length', min: 120, max: 160, step: 1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingLength', label: 'Housing length', min: 20, max: 70, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingDepth', label: 'Housing depth (inward)', min: 5, max: 25, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingHeight', label: 'Housing height', min: 6, max: 30, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingOffsetY', label: 'Housing vertical offset', min: -15, max: 15, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingWall', label: 'Housing wall', min: 0.3, max: 3, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensesPresent', label: 'Spectacle lenses fitted', type: 'toggle', tag: 'assumed' },
    ],
  },
  {
    id: 'targets', title: 'Coverage targets',
    controls: [
      { key: 'targets.azimuth', label: 'Peripheral position (azimuth)', min: 0, max: 45, step: 0.5, unit: '°', tag: 'spec' },
      { key: 'targets.elevation', label: 'Elevation', min: -20, max: 30, step: 0.5, unit: '°', tag: 'assumed' },
      { key: 'targets.coverageMin', label: 'Lens coverage min', min: 0, max: 100, step: 1, unit: '%', tag: 'spec' },
      { key: 'targets.coverageMax', label: 'Lens coverage max', min: 0, max: 100, step: 1, unit: '%', tag: 'spec' },
      { key: 'targets.centralClear', label: 'Central clear zone radius', min: 0, max: 25, step: 0.5, unit: '°', tag: 'assumed' },
    ],
  },
  {
    id: 'sim', title: 'Simulation',
    controls: [
      { key: 'sim.pixelsX', label: 'Pixel samples (H)', min: 2, max: 21, step: 1, unit: '', tag: 'assumed' },
      { key: 'sim.pixelsY', label: 'Pixel samples (V)', min: 2, max: 15, step: 1, unit: '', tag: 'assumed' },
      { key: 'sim.raysPerPixel', label: 'Rays per pixel', min: 4, max: 200, step: 1, unit: '', tag: 'assumed' },
      { key: 'sim.wavelengths', label: 'Wavelengths', type: 'select', options: [['mono', '550 nm only'], ['rgb', 'R/G/B 630/532/460 nm (BK7 dispersion)']], tag: 'assumed' },
      { key: 'sim.ghosts', label: 'Trace Fresnel ghost reflections', type: 'toggle', tag: 'assumed' },
      { key: 'sim.ghostMin', label: 'Ghost ray cut-off', min: 0.0005, max: 0.05, step: 0.0005, unit: '', tag: 'assumed', showIf: (p) => p.sim.ghosts, help: 'Fraction of a ray’s power below which ghost branches stop.' },
      { key: 'sim.drawRays', label: 'Rays drawn', min: 50, max: 4000, step: 50, unit: '', tag: 'assumed' },
      { key: 'sim.raySpeed', label: 'Light animation speed', min: 0, max: 120, step: 1, unit: 'mm/s', tag: 'design' },
    ],
  },
];

const ORDER = ['optics', 'hud', 'collimator', 'prism', 'oled', 'driver', 'eye', 'frame', 'targets', 'align', 'sim'];
export const SECTIONS = ORDER.map((id) => SECTION_LIST.find((s) => s.id === id));

export const VISIBILITY = [
  ['frame', 'Front frame'], ['lensR', 'Right lens'], ['lensL', 'Left lens'], ['templeR', 'Right temple'], ['templeL', 'Left temple'],
  ['hingeR', 'Right hinge'], ['hingeL', 'Left hinge'], ['housing', 'Temple housing + cavity'], ['eyeR', 'Right eye'], ['eyeL', 'Left eye'],
  ['oled', 'Micro-OLED'], ['driver', 'HDMI driver'], ['ribbon', 'Ribbon cable'], ['collimator', 'Collimator'], ['prism', 'Prism'],
  ['rays', 'Light rays'], ['coverage', 'Coverage overlay'], ['labels', 'Labels'], ['grid', 'Grid'],
];

export const COMPONENT_NAMES = Object.fromEntries(VISIBILITY);

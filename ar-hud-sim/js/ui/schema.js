// Control definitions. tag: spec (from the brief), assumed (adjustable
// assumption), design (placement chosen by the alignment helper or user).

export const SECTIONS = [
  {
    id: 'optics', title: 'Optical parameters', open: true,
    controls: [
      { key: 'prism.angle', label: 'Prism angle', min: 35, max: 55, step: 0.1, unit: '°', tag: 'spec', help: 'Angle between entry face and hypotenuse; 45° is the 45-45-90 prism.' },
      { key: 'oled.resX', label: 'OLED resolution (H)', min: 160, max: 1920, step: 2, unit: 'px', tag: 'spec' },
      { key: 'oled.resY', label: 'OLED resolution (V)', min: 100, max: 1200, step: 2, unit: 'px', tag: 'spec' },
      { key: 'oled.diagonalIn', label: 'OLED diagonal', min: 0.13, max: 0.7, step: 0.01, unit: 'in', tag: 'spec', help: 'Active area derived from diagonal and pixel aspect (square pixels assumed).' },
      { key: 'prism.size', label: 'Prism dimensions', min: 4, max: 16, step: 0.5, unit: 'mm', tag: 'spec' },
      { key: 'prism.n', label: 'BK7 refractive index', min: 1.4, max: 1.9, step: 0.001, unit: '', tag: 'spec', help: 'At 550 nm. Also used for the real collimator lens.' },
      { key: 'targets.hfov', label: 'Horizontal FOV target', min: 5, max: 70, step: 1, unit: '°', tag: 'spec' },
      { key: 'targets.vfov', label: 'Vertical FOV target', min: 5, max: 50, step: 1, unit: '°', tag: 'spec' },
      { key: 'oled.brightness', label: 'OLED brightness', min: 0, max: 100, step: 1, unit: '%', tag: 'spec' },
      { key: 'collimator.focalLength', label: 'Collimator focal length', min: 4, max: 30, step: 0.1, unit: 'mm', tag: 'spec', after: 'refocus' },
      { key: 'eye.eyeRelief', label: 'Eye relief', min: 8, max: 30, step: 0.5, unit: 'mm', tag: 'assumed', help: 'Lens back surface to corneal vertex.' },
    ],
  },
  {
    id: 'collimator', title: 'Collimating lens',
    controls: [
      { key: 'collimator.enabled', label: 'Lens installed', type: 'toggle', tag: 'design' },
      { key: 'collimator.mode', label: 'Lens model', type: 'select', options: [['thin', 'Ideal thin lens'], ['spherical', 'Plano-convex, spherical (real surfaces)'], ['aspheric', 'Plano-convex, conic asphere (real surfaces)']], tag: 'assumed' },
      { key: 'collimator.distance', label: 'Distance from OLED', min: 1, max: 30, step: 0.05, unit: 'mm', tag: 'design', after: 'refocus' },
      { key: 'collimator.aperture', label: 'Clear aperture', min: 2, max: 12, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'collimator.conicK', label: 'Conic constant k', min: -3, max: 1, step: 0.01, unit: '', tag: 'assumed', showIf: (p) => p.collimator.mode === 'aspheric' },
      { key: 'collimator.edgeThickness', label: 'Edge thickness', min: 0.3, max: 3, step: 0.1, unit: 'mm', tag: 'assumed', showIf: (p) => p.collimator.mode !== 'thin' },
      { key: 'collimator.flip', label: 'Convex side faces OLED', type: 'toggle', tag: 'design', showIf: (p) => p.collimator.mode !== 'thin' },
      { key: 'collimator.offsetX', label: 'Decentre X', min: -3, max: 3, step: 0.05, unit: 'mm', tag: 'design' },
      { key: 'collimator.offsetY', label: 'Decentre Y', min: -3, max: 3, step: 0.05, unit: 'mm', tag: 'design' },
      { key: 'collimator.tiltX', label: 'Tilt about X', min: -20, max: 20, step: 0.1, unit: '°', tag: 'design' },
      { key: 'collimator.tiltY', label: 'Tilt about Y', min: -20, max: 20, step: 0.1, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'prism', title: 'Prism placement',
    controls: [
      { key: 'prism.coating', label: 'Hypotenuse', type: 'select', options: [['none', 'Uncoated (TIR only)'], ['mirror', 'Aluminium mirror, R = 0.90']], tag: 'assumed' },
      { key: 'prism.pos.x', label: 'Position X', min: -70, max: -10, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.pos.y', label: 'Position Y', min: -20, max: 25, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.pos.z', label: 'Position Z', min: -30, max: 15, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'prism.rot.yaw', label: 'Yaw', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'prism.rot.pitch', label: 'Pitch', min: -90, max: 90, step: 0.1, unit: '°', tag: 'design' },
      { key: 'prism.rot.roll', label: 'Roll', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'oled', title: 'Micro-OLED placement',
    controls: [
      { key: 'oled.pos.x', label: 'Position X', min: -75, max: -30, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.pos.y', label: 'Position Y', min: -15, max: 20, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.pos.z', label: 'Position Z', min: -50, max: 5, step: 0.1, unit: 'mm', tag: 'design' },
      { key: 'oled.rot.yaw', label: 'Yaw', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.rot.pitch', label: 'Pitch', min: -90, max: 90, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.rot.roll', label: 'Roll', min: -180, max: 180, step: 0.1, unit: '°', tag: 'design' },
      { key: 'oled.emissionHalfAngle', label: 'Emission half-angle', min: 2, max: 60, step: 1, unit: '°', tag: 'assumed', help: 'Lambertian emission sampled inside this cone.' },
      { key: 'oled.peakLuminance', label: 'Peak luminance', min: 100, max: 5000, step: 50, unit: 'cd/m²', tag: 'assumed' },
      { key: 'driver.pos.z', label: 'Driver board Z', min: -60, max: 0, step: 0.5, unit: 'mm', tag: 'design' },
    ],
  },
  {
    id: 'eye', title: 'Eye',
    controls: [
      { key: 'eye.ipd', label: 'Interpupillary distance', min: 54, max: 74, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'eye.dx', label: 'Right eye offset X (world)', min: -8, max: 8, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.dy', label: 'Right eye offset Y', min: -8, max: 8, step: 0.1, unit: 'mm', tag: 'assumed' },
      { key: 'eye.eyeRelief', label: 'Eye relief', min: 8, max: 30, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'eye.pupilDiameter', label: 'Pupil diameter', min: 2, max: 8, step: 0.1, unit: 'mm', tag: 'assumed', help: '~2–3 mm in daylight, 4 mm indoors, up to 8 mm dark.' },
      { key: 'eye.gazeYaw', label: 'Gaze yaw (temporal +)', min: -35, max: 45, step: 0.5, unit: '°', tag: 'design', after: 'lookAtHud' },
      { key: 'eye.gazePitch', label: 'Gaze pitch (up +)', min: -30, max: 35, step: 0.5, unit: '°', tag: 'design' },
    ],
  },
  {
    id: 'frame', title: 'Frame dimensions',
    controls: [
      { key: 'frame.lensWidth', label: 'Lens width', min: 38, max: 64, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensHeight', label: 'Lens height', min: 26, max: 52, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.lensCorner', label: 'Lens corner radius', min: 2, max: 25, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.bridge', label: 'Bridge width', min: 12, max: 26, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.templeLength', label: 'Temple length', min: 120, max: 160, step: 1, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingLength', label: 'Housing length', min: 20, max: 70, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingDepth', label: 'Housing depth (inward)', min: 5, max: 25, step: 0.5, unit: 'mm', tag: 'assumed' },
      { key: 'frame.housingHeight', label: 'Housing height', min: 6, max: 26, step: 0.5, unit: 'mm', tag: 'assumed' },
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
      { key: 'sim.drawRays', label: 'Rays drawn', min: 50, max: 4000, step: 50, unit: '', tag: 'assumed' },
    ],
  },
];

export const VISIBILITY = [
  ['frame', 'Front frame'], ['lensR', 'Right lens'], ['lensL', 'Left lens'], ['templeR', 'Right temple'], ['templeL', 'Left temple'],
  ['hingeR', 'Right hinge'], ['hingeL', 'Left hinge'], ['housing', 'Temple housing + cavity'], ['eyeR', 'Right eye'], ['eyeL', 'Left eye'],
  ['oled', 'Micro-OLED'], ['driver', 'HDMI driver'], ['ribbon', 'Ribbon cable'], ['collimator', 'Collimator'], ['prism', 'Prism'],
  ['rays', 'Light rays'], ['coverage', 'Coverage overlay'], ['labels', 'Labels'], ['grid', 'Grid'],
];

export const COMPONENT_NAMES = Object.fromEntries(VISIBILITY);

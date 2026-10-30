// Optical materials and interface physics. Pure functions, no rendering.
// Units: wavelengths in nanometres, angles in radians unless a name says Deg.

// SCHOTT N-BK7 Sellmeier coefficients (SCHOTT optical glass datasheet,
// also tabulated at refractiveindex.info). Lambda in micrometres.
const BK7_SELLMEIER = {
  B: [1.03961212, 0.231792344, 1.01046945],
  C: [0.00600069867, 0.0200179144, 103.560653],
};

export function sellmeierBK7(lambdaNm) {
  const l2 = (lambdaNm / 1000) ** 2;
  let n2 = 1;
  for (let i = 0; i < 3; i++) n2 += (BK7_SELLMEIER.B[i] * l2) / (l2 - BK7_SELLMEIER.C[i]);
  return Math.sqrt(n2);
}

export const REFERENCE_WAVELENGTH_NM = 550;

// The user sets n at 550 nm (default 1.517). Dispersion is added as the
// Sellmeier difference from 550 nm, so the slider stays the single source of
// truth for the base index while R/G/B rays still separate realistically.
export function makeGlass(name, n550, { dispersive = true } = {}) {
  const ref = sellmeierBK7(REFERENCE_WAVELENGTH_NM);
  return {
    name,
    n550,
    indexAt(lambdaNm) {
      if (!dispersive || !lambdaNm) return n550;
      return n550 + (sellmeierBK7(lambdaNm) - ref);
    },
  };
}

export const AIR = { name: 'air', n550: 1.000293, indexAt: () => 1.000293 };

// Critical angle for light going from n1 (dense) into n2. null if n1 <= n2.
export function criticalAngle(n1, n2) {
  if (n1 <= n2) return null;
  return Math.asin(n2 / n1);
}

// Fresnel power coefficients for unpolarised light.
// cosI: cosine of incidence angle (>= 0). Returns {R, T, Rs, Rp, tir, cosT}.
export function fresnel(n1, n2, cosI) {
  const sinI2 = Math.max(0, 1 - cosI * cosI);
  const sinT2 = (n1 / n2) ** 2 * sinI2;
  if (sinT2 >= 1) return { R: 1, T: 0, Rs: 1, Rp: 1, tir: true, cosT: 0 };
  const cosT = Math.sqrt(1 - sinT2);
  const rs = (n1 * cosI - n2 * cosT) / (n1 * cosI + n2 * cosT);
  const rp = (n2 * cosI - n1 * cosT) / (n2 * cosI + n1 * cosT);
  const Rs = rs * rs;
  const Rp = rp * rp;
  const R = 0.5 * (Rs + Rp);
  return { R, T: 1 - R, Rs, Rp, tir: false, cosT };
}

// Wavelengths used when wavelength visualisation is on (nm) and their
// display colours. Off: a single 550 nm channel.
export const WAVELENGTHS = {
  mono: [{ nm: 550, color: 0xfff1b8, label: '550 nm' }],
  rgb: [
    { nm: 630, color: 0xff4a3d, label: '630 nm' },
    { nm: 532, color: 0x3dff6a, label: '532 nm' },
    { nm: 460, color: 0x4a7dff, label: '460 nm' },
  ],
};

export const deg = (r) => (r * 180) / Math.PI;
export const rad = (d) => (d * Math.PI) / 180;

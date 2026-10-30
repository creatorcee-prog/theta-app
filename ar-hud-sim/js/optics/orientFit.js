// Affine fit of apparent angle vs display coordinate (shared by the leveller,
// the diagnostics and the keystone pre-correction).
function solve3(M, r) {
  const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const D = det(M);
  if (Math.abs(D) < 1e-12) return [NaN, NaN, NaN];
  return [0, 1, 2].map((k) => det(M.map((row, i) => row.map((x, j) => (j === k ? r[i] : x)))) / D);
}
export function fitOrientation(pixelResults) {
  const pts = pixelResults.filter((p) => p.availableAngles);
  if (pts.length < 3) return null;
  const fit = (get) => {
    const M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], r = [0, 0, 0];
    for (const p of pts) { const x = [p.u, p.v, 1], y = get(p); for (let i = 0; i < 3; i++) { r[i] += x[i] * y; for (let j = 0; j < 3; j++) M[i][j] += x[i] * x[j]; } }
    return solve3(M, r);
  };
  const [a, b] = fit((p) => p.availableAngles.h);
  const [d, e] = fit((p) => p.availableAngles.v);
  if (![a, b, d, e].every(Number.isFinite)) return null;
  return { a, b, d, e, det: a * e - b * d, rollDeg: (Math.atan2(d, a) * 180) / Math.PI };
}
/**
 * Horizontal slant b/a in display coordinates. The driver's correction is
 * applied to the finished frame (after any left-right flip), so it uses the
 * display's own axes: a vertical line drawn with slope du/dv = -b/a lands at
 * one viewing angle h = a u + b v.
 */
export function shearOf(pixelResults) {
  const m = fitOrientation(pixelResults);
  return m && Math.abs(m.a) > 1e-6 ? m.b / m.a : 0;
}

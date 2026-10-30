// The wearer's eye as a focusing system: prescription, accommodation and
// whether the HUD's measured vergence lands in focus. Diopters throughout.
//
// The HUD light reaches the eye without passing through the spectacle lens
// (the prism sits behind it), so the eye's uncorrected refraction applies.

// Spectacle-plane power -> corneal-plane power for vertex distance d (mm).
export function cornealPower(F, vertexMm) {
  const d = vertexMm / 1000;
  return F / (1 - d * F);
}

// Power in the horizontal and vertical meridians of a sphero-cylinder.
// Power in meridian theta: S + C sin^2(theta - axis). Oblique axes also have
// a torsional component this two-meridian view leaves out.
export function meridianPowers(rx) {
  const a = ((rx.axis ?? 0) * Math.PI) / 180;
  return { h: rx.sphere + rx.cyl * Math.sin(a) ** 2, v: rx.sphere + rx.cyl * Math.cos(a) ** 2 };
}

// Average amplitude of accommodation by age (Hofstetter 1950): 18.5 - 0.3 age.
export function amplitudeFor(eyeParams) {
  if (eyeParams.ampMode === 'manual') return Math.max(0, eyeParams.amplitude);
  return Math.max(0, 18.5 - 0.3 * eyeParams.age);
}

/**
 * vergence: { Vx, Vy } measured at the pupil (Vx: horizontal fan).
 * Eye in focus for meridian m when V_m = Fc_m - A, 0 <= A <= amplitude.
 * Returns the best single accommodation and the residual defocus.
 */
export function assessFocus(vergence, eyeParams) {
  const m = meridianPowers(eyeParams.rx);
  const Fh = cornealPower(m.h, eyeParams.eyeRelief), Fv = cornealPower(m.v, eyeParams.eyeRelief);
  const amp = amplitudeFor(eyeParams);
  const needH = Fh - vergence.Vx, needV = Fv - vergence.Vy; // accommodation each meridian asks for
  const A = Math.min(amp, Math.max(0, (needH + needV) / 2));
  const residual = Math.max(Math.abs(needH - A), Math.abs(needV - A));
  const blurRad = (eyeParams.pupilDiameter * residual) / 1000;
  return {
    Fh, Fv, amp, needH, needV, accommodation: A, residual, blurRad,
    tooConverging: Math.min(needH, needV) < -0.25, tooDiverging: Math.max(needH, needV) > amp + 0.25,
    targetVergence: (Fh + Fv) / 2, // relaxed-eye sphere equivalent
  };
}

/**
 * Whole-field focus: the eye holds one accommodation for the whole HUD.
 * vergences: per-pixel { Vx, Vy }. Picks the accommodation that minimises
 * the 90th-percentile residual and reports that percentile and the worst.
 */
export function assessFieldFocus(vergences, eyeParams) {
  const m = meridianPowers(eyeParams.rx);
  const Fh = cornealPower(m.h, eyeParams.eyeRelief), Fv = cornealPower(m.v, eyeParams.eyeRelief);
  const amp = amplitudeFor(eyeParams);
  const needs = vergences.map((v) => [Fh - v.Vx, Fv - v.Vy]);
  const residualsFor = (A) => needs.map(([h, v]) => Math.max(Math.abs(h - A), Math.abs(v - A))).sort((a, b) => a - b);
  const p90 = (arr) => arr[Math.min(arr.length - 1, Math.floor(0.9 * (arr.length - 1)))];
  let best = { A: 0, p: Infinity };
  for (let i = 0; i <= 160; i++) {
    const A = (amp * i) / 160;
    const r = residualsFor(A), p = p90(r);
    if (p < best.p) best = { A, p, worst: r[r.length - 1], median: r[Math.floor(r.length / 2)] };
  }
  return { Fh, Fv, amp, accommodation: best.A, p90: best.p, worst: best.worst, median: best.median, blurRad: (eyeParams.pupilDiameter * best.p) / 1000, targetVergence: (Fh + Fv) / 2 };
}

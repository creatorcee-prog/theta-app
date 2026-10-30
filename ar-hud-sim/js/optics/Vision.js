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

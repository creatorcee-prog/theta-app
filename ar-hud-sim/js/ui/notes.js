// "Model notes" tab: what is given, assumed and calculated, and the
// limitations of the model. Kept next to the UI so it ships with the page.

export const NOTES_HTML = `
<section class="res-block">
  <h3>What the numbers are</h3>
  <ul class="notes">
    <li><span class="tag tag-spec">spec</span> Values from the project brief: 0.23″ 640×400 Micro-OLED, 10 mm BK7 45-45-90 prism, n = 1.517 at 550 nm, 12 mm collimator, 35°×20° FOV target, 25° peripheral target, 40–50% lens-coverage target, 75% brightness.</li>
    <li><span class="tag tag-assumed">assumed</span> Unknown for the real glasses and exposed as adjustable inputs: frame and lens dimensions, hinge height, temple cavity size, eye relief (14 mm), IPD (63 mm), pupil diameter (4 mm), OLED emission cone (±20°, Lambertian), OLED housing size, collimator aperture (8 mm), driver board size, spectacle lens index (CR-39, 1.498), peak luminance (1000 cd/m²).</li>
    <li><span class="tag tag-design">design</span> Component positions and orientations. The defaults come from an alignment helper that places the prism on the line from the pupil toward the 25°/10° target direction, as far forward as the lens allows, and puts the OLED and collimator on its input axis inside the temple. The helper only sets inputs; it does not decide whether light reaches the eye.</li>
    <li><span class="tag tag-calc">calculated</span> Everything in Results and Diagnostics is computed from the traced rays and the geometry above.</li>
    <li>No values are measured. No physical glasses were measured for this model.</li>
  </ul>
</section>
<section class="res-block">
  <h3>How light is traced</h3>
  <ul class="notes">
    <li>Each run emits rays from a grid of pixel positions spread over the finite 4.95 × 3.10 mm active area (edges included), sampled uniformly in solid angle inside the emission cone and weighted by cos θ (Lambertian).</li>
    <li>Ray–surface intersections use three.js's geometric ray library (Ray, Triangle, Sphere, Box3) against the actual faces: five prism faces, plano and conic lens surfaces, the spectacle lens slabs, the lens barrel, housings, temples and both eyes.</li>
    <li>At every dielectric surface the tracer computes the incidence angle from the real surface normal, then applies Snell's law in vector form and the unpolarised Fresnel equations. Total internal reflection happens only when sin θt &gt; 1 at that hit. Nothing assumes a 45° fold works.</li>
    <li>Reflections use R = I − 2(I·N)N. With the Fresnel ghost option on, reflected branches are traced too.</li>
    <li>The collimator is either an ideal thin lens (exact for the paraxial model: slope change −h/f) or a real plano-convex BK7 lens with spherical or conic surfaces solved as a quadric and refracted at both faces.</li>
    <li>Rays count as reaching the pupil only if they cross the entrance-pupil disc (3.05 mm behind the corneal vertex, diameter as set) from the front. Rays that hit the eyeball or cornea elsewhere count as misses (red).</li>
    <li>Vergence is measured from the traced bundles at the pupil plane (slope vs. position fit). The page reports a focused virtual image only when the measured bundles are near-collimated and their aberration spread is under about two pixels.</li>
  </ul>
</section>
<section class="res-block">
  <h3>Limitations</h3>
  <ul class="notes">
    <li>Geometric optics only: no diffraction, polarisation tracking through multiple surfaces (each Fresnel step is the unpolarised average), coatings other than the optional aluminium hypotenuse, scattering or absorption in the glass.</li>
    <li>The temple housing walls are a containment check, not traced surfaces; the housing is treated as having a window toward the prism. Real walls would add vignetting and stray light.</li>
    <li>Eyelids, lashes, brow and nose are not modelled as occluders. The eye-box sweep reuses the traced rays and ignores occlusion changes caused by moving the eye.</li>
    <li>Lens coverage is an apparent footprint: the region of the lens the HUD overlays when seen from the pupil centre. It is not light physically passing through the lens.</li>
    <li>The first-person view is drawn in linear angular coordinates. HUD brightness and blur are indicative; blur combines measured vergence (eye focused at infinity) and residual aberration.</li>
    <li>Peripheral acuity is far below foveal acuity. A HUD at 25° is readable only by looking at it, and the Diagnostics show how rotating the eye moves the pupil relative to the eye-box.</li>
    <li>The 40–50% lens-coverage target and the 35°×20° FOV target are not compatible for a spectacle lens 15–20 mm from the eye. The Diagnostics report the coverage that meeting the FOV target would actually give.</li>
  </ul>
</section>
<section class="res-block">
  <h3>Sources</h3>
  <ul class="notes">
    <li>N-BK7 Sellmeier coefficients: SCHOTT optical glass datasheet (also listed at refractiveindex.info, "SCHOTT N-BK7").</li>
    <li>Fresnel equations, Snell's law and the critical angle follow Hecht, <i>Optics</i>, 5th ed., ch. 4.</li>
    <li>Schematic-eye distances (corneal radius 7.8 mm, centre of rotation ≈13.5 mm behind the cornea, entrance pupil ≈3 mm behind the vertex): Atchison &amp; Smith, <i>Optics of the Human Eye</i>.</li>
    <li>Plano-convex focal length f = R/(n − 1) and front focal distance f − t/n: standard thick-lens relations (Hecht ch. 6).</li>
  </ul>
</section>`;

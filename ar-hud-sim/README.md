# Temple HUD Optical Bench

An interactive 3D geometric ray-tracing simulation of a monocular AR HUD
built into a pair of glasses:

- a 0.23″ 640×400 Micro-OLED in the right temple near the hinge
- an optional collimating lens
- a 10 mm BK7 45-45-90 prism folding the light toward the right eye

The optics are computed first. The 3D view, first-person view and
diagnostics only display what the tracer produced. All units are millimetres.

## Run it

```bash
cd ar-hud-sim
npm install          # three.js (for tests) and esbuild (for the single-file build)
npm run serve        # http://localhost:8080 (any static server works)
npm test             # physics unit tests (node --test)
node scripts/smoke.mjs        # headless run of the default design, prints every check
node scripts/lens-check.mjs   # ideal vs real (spherical / conic) collimator comparison
npm run build:single          # dist/hud-optics.html: one self-contained page body
```

The browser loads three.js 0.160.0 from jsDelivr through an import map, so
the page needs network access to `cdn.jsdelivr.net`.

## Architecture

Optical code never imports rendering code. It runs in Node for the tests.

| Module | Role |
|---|---|
| `js/optics/materials.js` | BK7 (Sellmeier dispersion around the user's n at 550 nm), air, Fresnel equations, critical angle |
| `js/optics/RayTracer.js` | **RayTracer**: surface primitives, vector Snell/reflection, Fresnel branching, TIR, ideal thin lens, conic surfaces, absorbers, eye detector |
| `js/optics/OpticalComponents.js` | **OpticalComponents**: OLED, prism, collimator and driver geometry, plus their conversion into tracer objects |
| `js/optics/Simulation.js` | Builds the system from parameters, emits Lambertian rays from the OLED pixel grid, traces, reduces per pixel, measures bundle vergence |
| `js/optics/CoverageAnalyzer.js` | **CoverageAnalyzer**: lens footprint, visual field, hardware occlusion, eye-box sweep, gaze check |
| `js/optics/Diagnostics.js` | **Diagnostics**: pass / adjust / fail checks with explanations |
| `js/model/glassesGeometry.js` | Frame, lens outline, hinges, temples, temple housing and cavity (pure geometry) |
| `js/model/eye.js` | **EyeModel** geometry: rotation centre, cornea, entrance pupil, gaze |
| `js/config/defaults.js` | Default parameters, provenance tags, and the alignment helper |
| `js/render/SceneManager.js` | **SceneManager**: renderer, orbit/zoom/pan (mouse and touch), camera presets, picking, drag gizmo, section clipping |
| `js/render/GlassesModel.js` | **GlassesModel** meshes and the green lens-coverage overlay |
| `js/render/EyeModel.js`, `OpticalMeshes.js`, `RayRenderer.js`, `FirstPersonView.js` | Eye, component, animated-ray and first-person rendering |
| `js/ui/UIController.js`, `schema.js`, `notes.js` | **UIController**: controls, results, diagnostics and model notes |

### On "use a ray tracing library"

Ray–geometry intersection uses three.js's math library (`Ray.intersectTriangle`,
`intersectSphere`, `intersectBox`, `Plane`). It is a maintained, renderer-independent
geometric ray library that runs in the browser and in Node.

I found no maintained JavaScript library that does physical optics on top of
that: Snell refraction, Fresnel splitting, TIR decisions, conic lens surfaces.
Python has one (`rayoptics`), but a browser app can't use it directly. So the
optical physics is implemented here and checked against closed-form results in
`tests/optics.test.mjs`:
- Snell refraction angle
- TIR threshold and the BK7 critical angle
- normal-incidence Fresnel reflectance and Brewster's angle
- N-BK7 index at the d-line (587.6 nm)
- the 90° fold and (1−R)² throughput of a 45-45-90 prism, and its TIR breaking for a 6° ray
- equilateral-prism minimum deviation
- ideal-lens collimation
- the plano-convex back focal distance
- measured vergence matching the thin-lens equation

## Coordinate frame

Right-handed: **+z forward** (viewing direction), **+y up**, so the
**wearer's right is −x**. The right eye, right lens and display temple are at
x < 0. The origin is the centre of the nose bridge, in the lens mid-plane.

A regression test checks that one fold mirror reports a mirrored image. If the
frame were left-handed, the model would silently become a mirrored left-eye
design.

## Provenance of every value

- **spec** (from the brief): 0.23″ 640×400 OLED, 10 mm BK7 prism, 45°, n = 1.517 at 550 nm, 12 mm collimator focal length, 35°×20° FOV target, 25° peripheral target, 40–50% lens-coverage target, 75% brightness.
- **assumed** (unknown for the real glasses, adjustable):
  - frame: lens 50×38 mm (r = 12), bridge 18 mm, hinge height 6 mm, temple housing 40×13×16 mm with 1 mm walls
  - eye: eye relief 14 mm, IPD 63 mm, pupil 4 mm
  - OLED: emission ±20° Lambertian, housing margins, peak luminance 1000 cd/m²
  - collimator: 8 mm aperture
  - other: spectacle lens CR-39 (n = 1.498), 22×10 mm driver board, schematic-eye constants (13.5 mm vertex to rotation centre, entrance pupil 3.05 mm behind the vertex)
- **design**: component positions and orientations. Defaults come from `alignChain()`, which only sets inputs:
  - The prism goes on the line from the pupil toward the 25° temporal / 10° up direction, as far forward as the lens back surface allows (1 mm clearance).
  - It is oriented so the axial ray leaves the exit face toward the pupil centre.
  - The OLED and collimator go on the prism's input axis, inside the temple cavity.
- **calculated**: everything in Results and Diagnostics.
- **measured**: none. No physical glasses were measured.

## What the default design actually does

From `node scripts/smoke.mjs`; nothing below is tuned to look good.

- The chief ray meets the hypotenuse at exactly 45.00°, 3.7° above BK7's 41.25° critical angle, and reaches the pupil centre. The chief-path Fresnel throughput with uncoated faces is 91.8%.
- **TIR fails for part of the field.** The collimated field spans ±11.6° in air, which is ±7.7° in the glass. Hypotenuse incidences therefore run from 37.4° to 52.8°, and 27% of hits are below critical and leak. About a third of the sampled pixels never reach the pupil. A mirror-coated hypotenuse fixes this; try the Prism → Hypotenuse control.
- **FOV 18.6° × 15.7° visible.** The geometric limit is 2·atan(W/2f) = 23.3° × 14.7° at f = 12 mm. The 35° target needs f ≈ 7.9 mm.
- **Placement is about right:** the HUD centre sits 27.9° temporal and 9.8° up, and the nearest HUD edge is 18.8° from the line of sight.
- **The prism blocks the line of sight.** A 10 mm prism about 14 mm from the pupil subtends roughly 40°. Its exit face reaches across the straight-ahead axis and covers 38% of the lens's angular area.
- **Lens coverage is 2.1%**, against the 40–50% target. Meeting the 35°×20° FOV target exactly would still cover only 6.2%. From this pupil the whole lens spans about 108°×85°, so 40–50% coverage would need a HUD field of roughly 65–85° on a side. The coverage target and the FOV target contradict each other; the page reports both rather than forcing either.
- **No eye-box sees the full display**, because the leaking half is gone wherever the eye is. A pupil sees ≥50% of the display over about 7.5 × 5 mm. Turning the eye 28° to look at the HUD moves the pupil 5.3 mm, and only 20% of the display stays visible.
- With the ideal lens at its focal plane, bundles are collimated (vergence 0.00 D), so a focused virtual image at infinity is supported. With real singlets (spherical or conic plano-convex, f/1.5) the measured vergence is off by several diopters and astigmatism is large. That's what a single fast element does; the page reports it and doesn't claim a focused image.
- One reflection mirrors the image left–right, so the driver must flip it. The left pupil receives no rays, but leaked light lands on the left eye area.

## Your measurements and vision

The **Your measurements** and **Vision** sections replace the typical-adult
defaults (tagged <code>measured</code>) with your own numbers.

**Frame and lens:**
- the frame size code (e.g. `52□18-145` sets lens width, bridge and temple length)
- lens height
- lens outline: rounded rectangle, superellipse, or your own traced `x,y` points. A non-convex trace is replaced by its convex hull, with a warning.
- pantoscopic tilt and frame wrap. Both are traced: the lens solids, the coverage projection, the prism-to-lens clearance and the alignment helper all use the tilted lens plane.

**Eyes and head:**
- right and left monocular PD and pupil heights
- vertex distance, pupil diameter, eyelash length (used as the prism's required clearance)
- temple-to-head gaps at the hinge and 20 mm behind it. These form a head surface checked against the housing and any part beside the temple.
- outer-eye-corner-to-temple, cross-checked against the model

**Vision:**
- right sphere, cylinder and axis, reading add
- age (accommodation from Hofstetter's average 18.5 − 0.3 × age) or a measured amplitude
- dominant eye, right-eye condition

The HUD light bypasses your spectacle lens, so the page converts the
prescription to the corneal plane. It then checks whether the traced HUD
vergence, per horizontal and vertical meridian, falls within your focusing
range. "Focus HUD for my eye" moves the OLED with the real tracer until the
vergence matches your relaxed eye. Astigmatism can't be fixed by refocusing,
and the page says so.

## Parts, placement and cost

Every hardware part can be selected in 3D, then dragged or rotated with the
gizmo:
- the OLED, prism, collimator and driver board
- the temple housing, which moves along the temple and up/down
- the eye
- generic parts: prism mount bracket, LiPo battery, USB-C charger, Raspberry Pi Zero 2 W, IMU, and any custom parts you add

Generic parts can be attached to the prism or the OLED so they move with it.
They are traced as light absorbers, so a part left in the beam shows up as
blocked rays. Each has editable size, position, rotation and colour.

The **Parts & cost** tab lists every part with quantity, unit price and
sources, and keeps a live grand total split into sourced prices and
estimates. Prices are single-unit retail snapshots (October 2026), excluding
shipping and tax:

| Part | Default | Basis |
|---|---|---|
| 0.23″ 640×400 Micro-OLED panel | $166 | average of [DisplayModule $139](https://displaymodule.com/products/0-23-inch-micro-oled-display-640x400), [Bonanza $159](https://www.bonanza.com/items/like/1730698481), [Walmart $199](https://www.walmart.com/c/kp/micro-oled). Kits with an HDMI board: [Tindie $275](https://www.tindie.com/products/oled-modules/microdisplay-023-inch-micro-oled-display-640x400/), [DisplayModule $599](https://displaymodule.com/products/0-23-inch-micro-oled-display) |
| HDMI driver board | $199 | [DisplayModule DMRXHMB](https://www.displaymodule.com/products/dmrxhmb-hdmi-micro-driver-board-typec-oled-amoled-evaluation-demo); compatibility not confirmed |
| 10 mm N-BK7 right-angle prism | $63 | [Newport ValuMax BRP-10](https://np.s2.mks.com/f/valumax-right-angle-prisms); [Edmund £74.80](https://www.edmundoptics.co.uk/p/10mm-uncoated-n-bk7-high-tolerance-ra-prism/2409/) |
| f ≈ 12 mm asphere | $21.20 | Thorlabs ACL1512, $16.20 uncoated / $26.20 AR in a 2015 catalog as reported by search. Not verified, likely outdated. |
| LiPo 150 mAh (501230) | $6.15 | [eBay listing](https://www.ebay.com/itm/174683669832) |
| USB-C LiPo charger | $5.95 | [Adafruit #4410](https://www.adafruit.com/product/4410) |
| Raspberry Pi Zero 2 W | $15 | [2021 launch MSRP](https://betanews.com/2021/10/28/raspberry-pi-zero-2-w); retail often higher |
| FPC, housing, bracket, wiring, IMU | estimates | no source found; enter your quotes |

### Weight

Every line also has a weight, a total worn weight, a right/left split and a
centre of mass (shown as an orange marker in 3D). The left/right balance check
uses 60% / 70% thresholds, which are modelling assumptions.

| Basis | Lines | How |
|---|---|---|
| calculated | prism, collimator, barrel, housing, bracket, driver PCB | Modelled volume × density, updated live: N-BK7 2.51 g/cm³ ([PGO](https://www.pgo-online.com/intl/BK7.html)), PLA 1.24 g/cm³ and FR-4 1.85 g/cm³ (typical values). Typing a value overrides it. |
| spec | Raspberry Pi Zero 2 W, 16 g | [Kubii listing](https://kubii.com/en/nano-computers/3455-raspberry-pi-zero-2-w-wh.html); other retailers list 9–25 g |
| measured | your existing glasses (25 g placeholder) | weigh them and enter it |
| estimate | OLED panel, FPC, battery, charger, IMU, wiring | no published weight found |

Default build: **58.1 g** worn, 9.9 g of it estimated, with 70% on the right
side. For comparison, Ray-Ban Meta glasses weigh about
[48.6 g](https://www.uk.shi.com/Product/47381750/Ray-Ban---Meta-Smart-glasses)
and the Meta Ray-Ban Display about
[69 g](https://www.tomsguide.com/computing/smart-glasses/meta-ray-ban-display-glasses-features-neural-link-price-and-availability).


## What you can adjust

Every input is a control in the Adjust tab. Each has a provenance tag, and
typed values are clamped to the control's range.
- **Optics:**
  - prism angle (20–70°), entry-face leg, height, BK7 index and hypotenuse coating
  - OLED resolution, diagonal, brightness, emission cone and peak luminance
  - collimator: installed or not, lens model, focal length, aperture, conic constant, edge thickness, orientation, distance, decentre and tilt
- **Placement:**
  - position and yaw/pitch/roll of the prism and OLED (sliders or the drag gizmo)
  - OLED housing size
  - driver board position and size, ribbon width
  - eye: IPD, offset, eye relief, pupil size and gaze
  - schematic-eye constants
- **Frame:** lens size, corner radius, thickness and index; bridge, rim, endpiece, hinge height; temple thickness, height and splay; housing length, depth, height, vertical offset and wall.
- **Projected content:**
  - text mode: three text lines, text size, arrow, border
  - a grid test pattern with corner tags
  - an uploaded image (fit, fill or stretch)
  - colour and background, and the driver's mirror flip

  Content is visual only: the tracer works on pixel positions, so changing it re-draws without re-tracing.
- **Targets, alignment helper and simulation:**
  - FOV, position and coverage targets, central clear zone
  - helper settings: prism gap to lens, OLED inset
  - pixel and ray sampling, wavelengths, ghost reflections and cut-off, rays drawn, animation speed

**Re-align chain** traces the axial ray through the prism as currently shaped,
so it also works for prism angles other than 45°. With an uncoated prism, the
result at each angle is:

| Prism angle | Hypotenuse TIR | Rays reaching pupil (of 1800) |
|---|---|---|
| 42° | 57% | 105 |
| 45° | 73% | 165 |
| 48° | 91% | 228 |
| 52° | 100% | 269 |
| 56° | 100% | 296 |

At 52° the whole sampled display is visible with no leakage. The cost is a
12.8 mm exit leg and only 2.9 mm of clearance between prism and cornea. The
45° default stays because it is the part in the brief.

## Limitations

- Geometric optics only. No diffraction, multi-surface polarisation tracking (each Fresnel step is the unpolarised average), AR coatings, scattering or bulk absorption.
- The temple housing walls are a containment check, not traced surfaces.
- Eyelids, lashes, brow and nose are not occluders. The eye-box sweep reuses traced rays and ignores occlusion changes caused by moving the eye.
- Lens coverage is the apparent footprint: the region of the lens the HUD overlays as seen from the pupil centre. It is not light passing through the lens, because the prism sits behind it.
- The first-person view uses linear angular coordinates. Its blur combines measured vergence (eye focused at infinity) and residual aberration.
- Peripheral acuity at 25° is far below foveal acuity. Reading the HUD means turning the eye, and the gaze check above shows what that costs.

## Sources

- SCHOTT N-BK7 datasheet, Sellmeier coefficients (also at refractiveindex.info → SCHOTT → N-BK7).
- E. Hecht, *Optics*, 5th ed.: Snell's law, Fresnel equations, TIR (ch. 4), thick lenses (ch. 6).
- D. Atchison & G. Smith, *Optics of the Human Eye*: schematic-eye distances.

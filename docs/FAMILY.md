# The family: IR next, then PXRD

Written 2026-09-29, when DSC-Panel reached 1.0. How the stacked-trace
plotters continue after it: first an INFRARED version, then a PXRD
version, on the handling DSC-Panel built. Read `docs/HANDOFF.md` and
`CLAUDE.md` first; this is the plan, not the rules.

## 1. What was decided

- **Separate apps on one shared core, not one app with presets.**
  Christian is "generally not a fan of all-in-one packages", and each data
  type wants different analyses, units, defaults and decorators - an
  all-in-one would make each of them a little worse for the others' sake.
  DSC and TGA share an app because they arrive in the same file; DSC next
  to PXRD in one figure is not something he needs.
- **Each app is its own package** (own name, command, Start Menu entry,
  session file type, settings folder) and depends on the core. Installed
  into one Python they share one PySide6 and one core.
- **PySide6-Essentials, not PySide6**: about 215 MB installed instead of
  675 MB. Everything the panel uses (QtCore, QtGui, QtWidgets, QtSvg;
  QtTest in the tests) is in Essentials. Keep it that way: an app that
  needs an Addons module (Charts, 3D, WebEngine) should say why first.
- **Not on PyPI for now** (Christian, 2026-09-29): `pip install` from
  GitHub is enough. The name question below is therefore not urgent, but
  it should be settled before the core is split out, because the core's
  package name is the one that is hard to change later.
- **What differs per data type lives in one module** (`core/profile.py`,
  started with `FIT_STAGED`): a sibling changes that, not the handling.

## 2. Open for Christian

- **The family's name.** Checked free on PyPI on 2026-09-29: Stackline,
  Tiers, Offsetplot, Ladderplot (bare and `-dsc`); Stackplot too, though
  PyPI may refuse it as too close to an existing name. Suggested:
  `stackline` for the core, `stackline-dsc`, `stackline-ir`,
  `stackline-pxrd`. A rename of DSC-Panel is `branding.py`, the two entry
  points and the project name in `pyproject.toml`, and `LEGACY_NAMES`
  (`register --clean-legacy` removes what the old name registered).
- **One repo or several.** One repo with the core and each app as its own
  package (a monorepo, released together) is easiest while the core's API
  still moves; separate repos once it is stable. Suggested: one repo until
  PXRD works, then decide.
- **IR file formats beyond OMNIC `.SPA`**: JCAMP-DX (`.dx`, `.jdx`)?
  Bruker OPUS? CSV exports? Real files first (the rule is: never write a
  reader from memory).
- **Which of the IR ergonomics matter most** (section 4): the broken x
  axis, absorbance/transmittance switching, per-spectrum normalisation,
  temperature colouring for VT series.

## 3. Step 0: the core (done WHILE building IR, not before)

The seam is not clean yet: `ui/plot.py` (about 7000 lines) knows about
analyses, mass curves, DTG and the exotherm arrow. Pulling the core out in
the abstract would guess where the line goes; building the second app shows
it. So: copy nothing, start the IR app against DSC-Panel's code, and move
each piece into the core the moment the IR app needs it unchanged.

What should end up in the core (it is data-type free already, or nearly):

| Core | Stays with the data type |
| :-- | :-- |
| the plot widget's view, gestures, picking, zoom/pan/fit, page | readers (`trios_io`, `trios_analysis`) |
| undo, the operator registry and F3, shortcuts | units (W/g, W/mol; cm-1, %T, A; 2-theta, d) |
| sessions (the format, versioning, `rehome`) | analyses (`measure.py`) and their labels |
| figure size, house style, presets, themes | the decorators a figure starts with (exo arrow) |
| decorators: labels, notes, marker lines, legend, pictures, structures | defaults (`profile.py`) |
| the outliner (files, rows, drag order, boxes) | what a "segment" is (DSC's step; an IR file's single spectrum) |
| colour picker, number boxes, gradients | the missing-value rules (molar mass, sample mass) |
| exports (PNG, SVG, CSV), the log, registration | the driver export (DSC's, frozen) |

The model's `Scan` is the hardest part: it mixes a generic trace (x, y,
offset, keep, colour, label) with DSC's heat flow, mass, DTG and exotherm
direction. The core wants a `Trace` with an x and a y array and a
per-app `signal` vocabulary; DSC's `Scan` becomes a subclass.

## 4. The IR version

What his figures and scripts already do (`ACH-IR-Plotter`,
`ACH-VT-IR-Plotter`, the stacked IR figure he showed on 2026-09-29):

- **Reading**: Thermo OMNIC `.SPA` natively (the VT-IR plotter reads it),
  absorbance vs transmittance detected from the data. Others after real
  files (section 2).
- **The x axis runs backwards** (4000 to 400 cm-1, wavenumber tilde-nu) and
  is often **broken** (4000-2200 | 1800-400, with the break drawn). The
  break is new: two x ranges on one axis, the curves drawn in both, the
  ticks per piece. It belongs in the core (a PXRD figure can use it too).
- **Normalisation is allowed here** (the DSC rule "never normalise per
  scan" is about DSC baselines; for IR it is defensible - Christian,
  2026-09-22). Per spectrum: none, max to 1, or a chosen band to 1; said
  on the axis ("normalised") so a figure never hides it.
- **%T or A**, switchable, converted honestly (A = -log10 T).
- **Band markers**: the marker lines DSC-Panel has (dashed, rotated
  label, moved sideways), with assignment labels in markup
  (`nu(C=O)`, `nu_{a}(COO^{-})`).
- **Colours**: the gradient DSC-Panel just got (one hue per series, dark
  to light) and, for a VT series, colour by temperature with a colour bar.
- **Stacking**: S, Stack evenly, the outliner's order - all as in DSC.
- **Analyses**: a peak position in an interval (the maximum of A or the
  minimum of %T), maybe a band area; an interval dragged on a curve works
  as in DSC. No enthalpies, no onsets.
- **Defaults** (`profile.py`): F staged (x first, then y, as in MoloM's
  PXRD window - the x range is the question for spectra), no exo arrow,
  the x axis reversed.

Suggested rounds: (1) a reader for his `.SPA` files and a figure with the
reversed x axis, stacked, exported; (2) %T/A and normalisation; (3) band
markers and labels, gradients; (4) the broken axis; (5) peak positions;
(6) VT colouring. Each round with real files from him, and the core
growing as each piece is shared.

## 5. The PXRD version

What exists: `ACH-PXRD-Quickplot` (one-shot stacks) and the
`ACH-Diffraction-Analysis-Suite` (Pawley setup, prefit, plotting, quick
comparison, conversion), and MoloM's PXRD window, whose ergonomics
DSC-Panel took over.

- **Reading**: the formats Quickplot reads - Bruker `.brml`, Riet7 `.dat`,
  `.xy` / `.txt` / `.csv`, TOPAS-convertible `.raw`, simulated patterns
  from `.cif`, ICDD PDF cards (`.xml`) - reusing the suite's readers
  rather than writing new ones. pymatgen is heavy: an optional extra for
  CIF simulation, not a dependency.
- **Axes**: 2-theta, with d and Q as views (they need the wavelength,
  which is never assumed - the same rule as DSC's molar mass: missing is
  said where it is used).
- **Normalisation** per pattern, as for IR, said on the axis.
- **Highlight bands**: Quickplot's `--highlights` - a 2-theta region
  magnified by a factor on every trace, shaded, the factor written.
- **Reflection ticks**: a CIF's or a card's strongest reflections as fine
  dotted lines or tick rows under the patterns, colour-coded per phase.
- **Analyses**: an interval dragged on a curve gives a peak position,
  its d-spacing and its FWHM - never an integral (Christian: "there is
  never a need to integrate a PXRD peak as far as I know").
- **Defaults**: F staged, no exo arrow.

Suggested rounds after IR: (1) readers through the suite's code and a
stacked, exported figure; (2) normalisation and the 2-theta/d/Q axis with
the wavelength; (3) reflection ticks from CIFs and cards; (4) highlight
bands; (5) peak position, d and FWHM.

## 6. How the work is done (carried over)

- Rounds, each with Christian's requests written into `docs/NEXT.md` as
  they come and logged in `PLAN.md` when done.
- Design choices are put to him first; no agent fleets.
- Real files before any reader or fixture; readers are the app's own and
  tested against real exports.
- Python 3.10.0, ASCII source, no em-dashes, no commit unless asked.

# Plan

Where this came from, what is built, what is next, and what is still
undecided. Started 2026-09-23 from two existing programs: the PXRD window in
ACH-MoloM (`molom/ui/pxrd_panel.py`) for the handling, and ACH-DSC-Plotter
for the reader and the figures.

## Decisions taken (Christian, 2026-09-22 and 2026-09-23)

| Decision | Why it matters |
| :-- | :-- |
| Its own repo, `ACH-DSC-Panel`; the app is `DSC-Panel`, the command `dsc-panel` | standalone, not a panel inside MoloM |
| Started from the CLI or from Start search, like MoloM | `dsc-panel` is on PATH once installed; `dsc-panel register` adds the Start Menu entry |
| A rename is expected | the name is in `branding.py` alone, registration writes a manifest, `LEGACY_NAMES` + `--clean-legacy` deregisters the old one, `dsc-panel alias <name>` gives the user their own |
| The reader is VENDORED from ACH-DSC-Plotter | that repo is private; `tools/vendor.py --check` is the drift alarm |
| Y data is NEVER normalised per scan | a DSC baseline is part of the measurement; the axis carries real units |
| Default W/g; mW and W/mol as well | W/mol is power per mole, which is what the trace is. Enthalpies from integrations are the per-mole quantity in kJ/mol |
| M is explicit, never assumed | a scan with no M is a blinking placeholder, and every export says so |
| Stacking is continuous, with offset arrows | not slots, not swaps: scans sit where they are put and say where that is |
| Objects, selection, `G` transforms, `F3` search | MoloM's Blender handling, in a plot |
| The arrow is an object; exo/endo labels both exist | the label decides the orientation, so the two cannot contradict each other |
| Exo down is the default | and the file's own convention is read where it is stated |
| Phase 1 carries undo, sessions, background loading and the driver export | each is painful to retrofit |
| The standalone PXRD plotter waits | DSC first |

## Built (0.1.0)

* The reader vendored, with `--check`, and `Sample` / `Scan` / `Document`
  over it. Segments become scans; a file opens with its first heating scan
  and every other segment is one tick away in the outliner.
* The painted plot: the PXRD keys, the pixmap cache, per-column decimation
  rewritten for non-monotonic x, picking against what was actually drawn.
* Continuous dragging, `G` with typed numbers, `Shift` precision, `Ctrl`
  snap, `Esc` cancel. Offset arrows for the selection.
* Units with enforcement: mW, W/g, W/mol; placeholder plus double-blink for a
  scan missing its molar mass; `NO MOLAR MASS` stamped on exports and printed.
* The heat-flow arrow as a draggable object, with the four labels.
* Outliner dock, `F3` palette, per-object settings dialogs with live apply.
* Operator registry with per-selection predicates; menus, shortcuts and F3
  all read from it.
* Undo over every property change, one step per gesture.
* Sessions (`.dscpanel`), CSV export, PNG/SVG export in the light palette,
  and the `DSC_Plotter.py` driver bridge (a full runnable template when
  `achdsc` is importable).
* Background loading on a thread pool (measured: 1.09 s for a 16 MB file).
* `dsc-panel register` / `alias`, with a manifest and `--clean-legacy`.
* 41 tests, four of them against real `.tri` files when they are on disk.

## Round 2 (2026-09-23, from testing the first build)

Christian's report after the first run, and what each became:

* **Only the first file's segments were reachable.** Now the outliner lists
  EVERY segment of every open file, ticked or not, and ticking one puts it on
  the plot (undoably). Comparing the second and third up-scans of several
  samples is the whole job, so this was a bug and not a gap.
* **A file now opens with its first heating scan alone**, whether it is the
  first file or the fifth. The template's "one file shows everything" rule is
  right for a quick look and wrong for a stacked figure.
* **The heat-flow arrow is the template's arrow**: one filled shape in the
  proportions of `add_exo_arrow` (4.5 pt shaft, 13 pt head, 9 pt head length,
  tail 0.9 of the head), with the label above the tail.
* **Two themes**, `blender-default` and `light`. The arrow's colour defaults
  to "auto", which is the theme's ink, so the same figure reads in both.
  Exports stay light.
* **Artists move in x, data does not.** `PlotWidget.is_artist` is the line
  between them: the arrow goes wherever it is dragged, a scan only up and
  down. The arrow's drag was also inverted (its y is measured from the top of
  the plot) and is not any more.
* **Controls follow the trackpad**: a two-finger swipe pans, Shift swaps the
  axes, and a pinch (which Windows sends as Ctrl+wheel) zooms about the
  cursor. A mouse wheel still zooms y.
* **Box select is the resting tool.** A drag on empty space selects what it
  covers; Esc always comes back to it. The pick radius went from 60 px to 14,
  because 60 grabbed a neighbour.
* **Removing is undoable.** The command holds the scans, so Ctrl+Z puts the
  same objects back with their offsets and colours. Removing a file leaves
  the file OPEN (its segments stay listed) unless it is closed.
* `Ctrl+A` selects everything (A is free again) and `R` resets the selected
  offsets to zero, or all of them when nothing is selected.

### Round 2b, the same day

* **The trackpad mapping, settled:** a plain two-finger swipe scales the y
  axis about the cursor (the gesture used constantly on a stack), `Shift` +
  swipe is an omnidirectional pan that keeps both spans, and Ctrl + swipe -
  which is how Windows delivers a pinch - zooms both axes. The bug underneath
  all three was reading "no pixel delta" as "a mouse wheel": this touchpad
  reports notches, so every swipe took the wheel path.
* **`y_scale` is gone from a line's settings**, and from the model with it.
  The same figure comes out of the offsets and the axis limits, so a knob
  that quietly multiplies one curve had no reason to exist. The export
  warning and the `x2` label went with it. (Scaling the y AXIS is a view
  gesture and is untouched.)
* **Analyses are objects** (`core/model.Analysis`), off until ticked, listed
  under their scan in the outliner and in the scan's settings, each with its
  own colour, label and dialog. `source` says whether it came from the file
  or (later) from the panel; `attribution` says how sure the attachment is,
  and an uncertain one is drawn dashed with a question mark and can be moved
  to another scan of the same sample.
* **A crash when a "not shown" segment row was clicked.** Those rows carry a
  three-part key and `_object` unpacked it into two - a ValueError inside a
  Qt slot, which PySide6 turns into an abort with no traceback. Fixed, and
  the outliner's signals are now deferred by a zero timer so a rebuild can
  never delete the row the click is still inside.

### Round 3, the figure itself

* **The plot is the template's figure now**: no grid, ticks pointing in with
  minor ticks between them, and the captions `T / degC` and
  `Heat Flow / W/g`, which is `style()` from DSC_Plotter.
* **Axes are objects.** Double-click a caption or the numbers for its
  settings (text, sizes, grid, minor ticks, tick direction). The caption can
  be dragged, and `axis_label_rect` clamps it into the margin, so it can
  never land on the data.
* **Captions are objects.** `Ctrl+T` adds one where the cursor is; it is
  dragged, edited, selected and saved like anything else. The names that
  appear beside a curve are now a READOUT - hover or selection only - rather
  than part of the figure.
* **Integrations are shaded**, between the curve and the straight baseline
  joining the stored cursors, as `add_integral_trios` does.
* **An analysis label hangs from a leader arrow** and is dragged VERTICALLY
  only: the arrow stretches to match, so the label always points at its own
  feature. Double-click opens its settings; double-click and drag moves it.
* **Typing a number moves the selection.** G is still there, but it is no
  longer the only way in - a selected scan is already the active one.
* **The right-click menu on a curve is two entries**, Settings and Set the
  molar mass.

### Round 4: analyses made here, and the figure's details

* **Measuring, TRIOS style.** Select one scan, click a point on it for the
  first crosshair, click again for the second (type a temperature at either,
  in whatever unit the axis is showing), then Enter for a quick-select list
  in the shape of F3. Esc walks back one step at a time: the typed number,
  then a cursor, then the other, then the gesture. Double-click an analysis
  made here and its cursors come back for adjustment; confirming replaces it
  and keeps its styling. `core/measure.py` computes through the SAME
  `trios_analysis` the reader uses, so a panel onset and a TRIOS onset are
  the same kind of object - checked against a stored integration, 13.3 J/g
  against the file's 13.2611.
* **Kelvin and Fahrenheit** for the x axis, as a display conversion: the
  data, the stored cursors and anything measured here stay in the file's
  Celsius, so switching back and forth cannot drift.
* The x caption sets `T` in ITALIC (`*` marks italic in a caption), the
  margins grow with the tick and caption fonts instead of letting big numbers
  run off the window, analyses have their own label size, the y caption
  dragged the wrong way horizontally, and a downward peak now labels from
  below so its leader arrow never crosses the shading.

### Round 5, from the second round of testing

* **Enter was double-booked.** `object.settings` held a window-level QAction
  on Return, and a window shortcut fires BEFORE the focused widget sees the
  key - so confirming a measurement opened the scan's settings instead.
  Return is now unbound; double-click is the way into a settings dialog, and
  a test asserts no operator claims Return or Enter.
* **Tick numbers were drawn into fixed 13 and 16 pixel boxes**, so raising
  the tick size clipped them. Both are measured from the font now, and the
  margins grow with them.
* **The axis splits in two targets.** Double-clicking the SPINE (the line and
  its numbers) opens the axis - ticks, grid, sizes; double-clicking the
  CAPTION opens the caption alone. The spine bands sit strictly outside the
  plot, which also stopped them swallowing a box select started in the
  corner.
* **Nothing is drawn outside the axes.** The curves, the shading and the
  analyses are clipped to the plot rect; zooming in used to paint them over
  the margins and the caption.
* **The quick-select list shows short names** - Onset, Integration, Glass
  transition - with the TRIOS model string kept underneath as the id.
* **A measured analysis arrives labelled**: `\Delta*H* = 13.247 J/g`,
  `*T*_{g} = 78.9 degC`. The label markup now carries subscripts (`_{g}`) and
  the Greek letters a DSC caption needs, beside the italic that was already
  there, and the same markup works in an axis caption.
* **F3 can finish a measurement**: "Analyse the interval..." lights up once
  both cursors are down, and "Stop measuring" beside it.

### Round 6: artists get a transform, and measuring gets its handles

* **`core.model.Artist` is the base class** every non-data object derives
  from: a POSITION, an ANCHOR (which of its nine points sits on that
  position), a colour, and two class flags - `can_rotate`, `can_scale` -
  that say what else the kind allows. The arrow declares neither (its length
  is a setting, and an arrow that says "exo down" cannot be rotated without
  lying); a caption declares `can_scale`, because its point size IS its
  scale. A new artist sets the flags and the dialogs give it the right
  fields.
* **Position in either space.** `relative` is a fraction of the plot, which
  keeps an artist in its corner whatever the view does; `data` pins it to a
  temperature and a heat flow, which is what a note about a peak wants. The
  settings offer both and CONVERT when the choice changes, so switching
  never moves anything.
* **Measure cursors are handles.** Press one and drag it - on its circle or
  anywhere along its dashed line - instead of clicking again to replace it.
* **Adjusting an existing analysis** shows its cursors AND opens its
  settings, and confirming keeps the model it already has rather than asking
  again.
* **Delete removes an analysis or a caption** without touching the scan it
  sits on. Undoable, like everything else.
* **Interval markers**: dashed verticals at an analysis's two cursors, the
  markers the template draws, with a tickbox to hide them where two overlap.
* **The plain cursor is a reticle** - a ring with four ticks and a small
  cross - rather than a dashed line down the plot. The dashed line came from
  the PXRD window, where x is the whole question; on a stack it is in the
  way. The dashed SPAN while measuring stays.

### Round 7: labels per line, and getting out of the way

* **A label can belong to a line.** Right-click a curve, "Add a label...",
  and the caption is that scan's: it wears the line's colour while its own is
  automatic, is listed under it in the outliner, and goes with it when the
  scan is removed (an undo brings both back). It is still positioned freely,
  like any artist.
* **The settings dialogs are not modal any more.** They apply as they are
  touched and are meant to be worked BESIDE the plot - a modal one blocks the
  measurement cursors it is describing. The undo step is built when the
  dialog finishes rather than when it is opened.
* **The interval marker is a bracket ON the curve**, with a short tick at
  each end, rather than two dashed verticals running down to the axis. The
  verticals said something much louder than "this stretch was analysed".
* **The system pointer is hidden** inside the axes, where the reticle is
  standing in for it. It comes back in a zoom or pan mode, and outside the
  plot.

* **The legend is an artist** (`Ctrl+L`, or the outliner's tick): a colour
  sample and a name per DRAWN scan, using each scan's own label, with a box
  behind it, a text size, a sample length and a line spacing. It is dragged,
  anchored and saved like the arrow, and it starts off - a stack of three is
  often clearer without one.
* `PlotWidget.is_artist` now asks `isinstance(obj, Artist)` rather than
  listing the kinds, which is how the legend arrived unable to move: a new
  artist should be draggable because it IS one.

**Standing note from Christian, 2026-09-24:** the interactions are expected
to change fundamentally as the program is used. Nothing in the input handling
should be treated as settled, and it is better to make a gesture easy to
move than to defend the current one.

### Round 8 (2026-09-25): one press selects, two act

Christian: "there are too many competing gestures", and the worst was that a
double-click-drag on a scan MOVED it. Marking an interval for analysis should
be the trivial, obvious gesture, and it was the piece missing. So:

* **A single press never moves anything.** Released where it was pressed it
  is a click (select; `Shift` toggles; a click inside a selection makes that
  object the only one). Dragged, it is a box select, wherever it started -
  on a curve, on the arrow, on nothing. The Blender Select Box tool.
* **A double-click-drag on a curve marks an interval.** The span and both
  crosshairs draw as it goes; letting go opens the analysis list under the
  pointer (one click, or type and Enter), and the analysis is computed,
  drawn and on the undo stack before the list has closed. `Esc` mid-drag, or
  on the list, drops it. A double-click that does not move still opens the
  scan's settings.
* **A double-click-drag on anything drawn ON the figure moves it**: the
  arrow, the legend, a label, an analysis label, an axis caption. That now
  includes the labels of analyses made here, which used to jump into
  re-editing on the press and could not be moved at all.
* **A scan moves with `G` or a typed number, and nothing else.** Clicking a
  selected curve no longer starts a measurement; `C` is the typed route.
* **The house style** (`core/style.py`, `ui/settings.py`, `Ctrl+,`): sizes
  (analysis labels, captions, numbers, legend, labels, curve width) and the
  label alignment resolve object -> figure -> the user's default -> built-in.
  The default persists on the machine (`preferences.json` beside the
  registration manifest), the figure's column is saved in the session, and a
  size set on one object wins over both and can be handed back. Session
  version 2; a version-1 file's sizes that equal the built-ins are read as
  "not chosen" so old figures follow the new defaults.
* **`flush` from DSC_Plotter** for analysis labels: which edge of the text
  sits on the leader arrow. `auto` is the template's own per-artist choice -
  tangent constructions left, integrals centred.
* Found on the way and fixed: an analysis made in the panel was **not saved**
  in the session (now stored as model + cursors and recomputed on load); a
  data-space artist was clamped into 0..1 the moment it was dragged; every
  artist move was recorded in the undo history as "move arrow".

Chosen here and cheap to reverse if it is wrong: a single drag that starts on
an ARTIST is a box select too, not a move. Christian named double-click-drag
as the artist gesture; one meaning per press was the point. (Reversed in
round 9, below.)

### Round 9 (2026-09-25): a drag acts on what it starts near

* **"Double-click-drag doesn't work at all, it always does a box."** Most
  likely his touchpad: Windows delivers tap-then-drag as ONE press and a
  drag, never as a double-click, so round 8's grammar could not be reached
  from his hands. (A real mouse double-click-drag worked; checked through
  Qt's own input pipeline.) His fix, as asked: **a box starts only when the
  press is NOT within N pixels of anything.** Near a curve, a drag marks the
  interval and asks for the analysis; near the arrow, the legend, a label,
  an analysis label or an axis caption, it moves it; `Shift` always boxes.
  A scan still moves with `G` only. A double-click-drag does the same.
* **N is a setting**: Edit > Settings > Handling > Pick distance (14 px
  built in), user-only - it describes a hand, not a figure. Picking is now
  "nearest object within N", so a label is as easy to hit as a curve.
* **Zoom, pan and fit are on the undo stack**, one gesture per step (a
  wheel or pinch burst ends after 450 ms still). Zooming in three times,
  three Ctrl+Z come back out. Reverses the round-1 decision below ("undo is
  for the document").
* **The windows follow the plot's theme**: MoloM's dark Fusion palette with
  `blender-default`, a light one with `light` (`ui/appearance.py`).
* **Menu bar: File, Edit, Search, Help.** Object, Transform, View and Arrow
  are gone - F3 has all of it, filtered by the selection. Search is a button
  on the bar; Help has About (version, reader origin, Python/Qt).
* **Saving flashes "Saved ..."** over the plot, as MoloM does (exports too).
* **CN-119 read 3 segments of 7.** Not an old-TRIOS problem: a step name is
  a length-prefixed string and the reader only stripped length bytes ' '
  and '!' - names of exactly 32 or 33 bytes, which every file it had been
  tested on happened to have. "Ramp 10.00 degC/min to 210.0000 degC" is 34.
  Fixed in ACH-DSC-Plotter (`_step_name`, TRI-FORMAT.md section 4), checked
  against all three CN-119 exports, re-vendored. The `.tri`'s EMPTY analyses
  are correct: its audit trail shows all five deleted after the export.
* **Tests can no longer hang on a modal dialog** (conftest `no_modal_loops`).

### Round 10 (2026-09-25): committed, then details

* **Both repos committed** at Christian's request: the panel's initial
  commit (`f261ce5`, on `master`) and the reader changes in ACH-DSC-Plotter
  (`d743702`, on `main`). Not pushed. Before the panel's commit,
  `tests/test_data_cases.py` had a home folder and a student's name written
  into it; the tests now find real files by NAME through the uncommitted
  `tests/local_testdata.txt` (`conftest.local_file`).
* `Z` cycles **box, horizontal, vertical**: on a DSC stack the feature is a
  region, not a range of peaks.
* `Ctrl+L` / `Ctrl+R` / `Ctrl+M` align analysis labels left / right /
  centred (the selected ones, else all shown on the selected scans).
  `Ctrl+L` no longer toggles the legend; the outliner tick and F3 do.
* **Interval marks redrawn** (his screenshots): no copy of the curve lifted
  above it any more. Dashes at the bounds on the trace, in the axis colour;
  for onset, endset and Tg, straight lines bound -> point -> bound.
* **`Ctrl+W` closes the pop-up in front** (the active one, else the one
  opened last) and the window only when no pop-up is open. It used to close
  the whole program from inside a settings dialog - the window's shortcut
  reaches it there. Closing a pop-up this way is what its X does.
* **Clicking off an object now clears its orange**: the render cache did not
  key on the selection of artists.
* **Adjusting an analysis**: its settings open BESIDE its gizmos; letting go
  of a gizmo recomputes the analysis in place; closing the settings, any
  way, confirms and removes the gizmos. The label follows the new number.

### Round 11 (2026-09-25): parametric curves, and nothing lost by accident

* **x_truncate**, the template's: hide the first / last N % of a scan's
  POINTS (Scan settings > Hide). Never by temperature - a DSC curve is a
  parametric curve that doubles back at its start and runs backwards when
  cooling. The hidden ends are dashed while the scan is hovered or
  selected, and left out of the fit (F), picking, arranging, the analyses
  and the CSV; the driver export writes the same `x_truncate` call.
* **Intervals are stretches of samples.** A drag along a curve records the
  two samples nearest where it started and ended (`Analysis.span`), and the
  analysis is computed on exactly that stretch. Christian: dragging an
  analysis "doesn't know where to start and end" on such a curve. The
  gizmos of such an analysis follow the curve. Sessions keep the span.
* **"Save changes?" on close** when the figure differs from what was last
  saved or opened; the title shows `*`.
* **A settings window keeps its changes however it is closed** (X, Esc,
  Ctrl+W). The Cancel button is now **Revert**, the one way back.
* **His defaults are the built-ins**: analysis labels 11 pt left-aligned,
  captions 14 pt, numbers 12 pt. New: **caption distance** (8 px) between
  an axis's numbers and its caption, which used to sit a fixed 16 px below
  the axis line and overlap numbers bigger than 8 pt. The settings page
  scrolls once it outgrows the screen, like MoloM's.
* The first clicks after opening "not being picked up" was most likely the
  missing orange of round 10 (the clicks registered; the highlight was
  cached): measured through Qt's input pipeline, every click selected the
  right object in 20-70 ms. Loading is 1.4 s in the real event loop.
* Also: the x axis's temperature scale (K / degF) is saved in sessions; an
  integral's baseline on a cooling scan is right (it used `np.interp`,
  which needs x to increase).

## Next

1. **Analyses drawn properly.** Right now a decoded analysis is a tick and a
   number on the curve (`Tg 78.9`, `13.3 J/g`, `Onset 61.1`). Port
   `trios_artists`: the onset/endset tangents, the shaded integral with its
   dH label, and the Tg construction, which now has real numbers to draw
   from - onset point, end point, step height and midpoint.
2. ~~New analyses in the panel.~~ Done: rounds 4 and 8 (double-click-drag
   a curve, pick the model, it is computed and saved with the session).
3. **Axis limits dialog on `M`**, to match the PXRD window, which would free
   `Shift+M` back up for the molar mass.
4. **The heat-flow arrow needs separate style parameters.** `length` scales
   the whole thing uniformly; the shaft width, head width and head length
   should be their own settings (Christian, 2026-09-23, explicitly parked).
   When that lands it is a `can_scale` artist with a non-uniform scale, which
   is the first case the capability flags will have to answer properly.
5. ~~A view history.~~ Done in round 9, on the undo stack itself, at
   Christian's request.
6. **More artists**: a scale bar, a molecule image, a text note with its own
   leader arrow. `is_artist` and the transform already carry them; what is
   missing is the objects and a way to add them.
7. **Analysis labels may need horizontal freedom** when several clash. Locked
   vertically for now, on purpose.
5. **A blank-run subtraction** (empty pan), the DSC counterpart of the PXRD
   background.
6. **Closing a file** (as opposed to taking its scans off the plot) has no
   operator yet: `Document.close_sample` exists and nothing calls it.
7. **SDT / TGA**: the reader already handles the signal names; it needs a
   second y axis and a weight-percent unit.

## Settled on 2026-09-23, with the files Christian supplied

* **Exo down, proved rather than assumed.** `Indium-03082026(1).tri`: on its
  own isothermal segment `Heat Flow = -254.8 x Delta T` (correlation -1.000),
  and the melt is a -69 uV excursion in Delta T, so an ENDOTHERMIC event
  points UP in the stored heat flow. Endo up is exo down. The audit trail and
  OJ-12's export header say the same thing independently.
  `tests/test_data_cases.py` keeps it.
* **The glass transition is decoded.** Four (x, y) pairs at +0/+16/+32/+48 -
  onset cursor, onset, end, end cursor - and the midpoint is the half-height
  crossing between the middle two, which reproduces TRIOS's exported
  `Midpoint 78,911` exactly. The old +132 second cursor read 0.0, which is
  why this looked undecodable. Implemented in ACH-DSC-Plotter (`_tg_fields`,
  TRI-FORMAT.md section 5), vendored in here, and drawn as `Tg 78.9`.
* **Moving a scan in x is out.** Christian: "shifting along x is nonsense."
  Not a setting, not a flagged option: it does not exist.
* **A TRIOS `.txt` export is a first-class input.** It stores W/g and no
  watts, and hides the sample mass in `[Procedure]`; both are handled, so an
  export draws in mW, W/g and W/mol like a `.tri`.

* **A calibration run's ramp segment is not reconstructed, on purpose.** The
  indium file records that segment without Temperature and without Heat Flow
  and has no alias signals to fill them from. Measured against TRIOS's own
  export of that run:
  - heat flow reconstructed as `a*DeltaT + b`, with the constants fitted on
    the file's own isothermal segment: **7 % out** (0.134 W/g on a 1.96 W/g
    span);
  - temperature reconstructed as `T0 - DeltaT0/S`, S = 63.4 uV/K: **0.29 K
    out**.
  The run is a cell-constant verification, judged at +-2 % and +-0.1 degC, so
  a reconstruction that is 7 % and 0.29 K out is worse than no curve. The
  relation IS linear (fitted on the ramp itself it holds to 0.19 %), but its
  constants move with temperature, and TRIOS applies a T1 calibration
  (slope, offset, KCell - all four are in the export header) that this
  program does not have.
  **The export is the answer, and the panel says so**: a `.tri` whose segment
  has no heat flow gets a note naming the `.txt` beside it. Opened that way,
  the indium melt comes out at 28.56 J/g against indium's 28.5 and points up,
  which is the third independent confirmation of exo down.

## Open questions for Christian
* **Picking an object buried under others** (2026-09-25). Where several
  overlap, only the nearest / topmost can be clicked; a lower one is out of
  reach except through the outliner. Click-cycling (each click takes the
  next one down) was considered and DROPPED: the second click of a cycle is
  a double-click, which opens settings. Wants another mechanism - an
  Alt+click that cycles, a small "which one?" list on an ambiguous click,
  or a key that steps down the stack. His call.
* **What should a scaled scan look like?** `y_scale` is allowed and is
  labelled `x2` beside the name and in the export warnings. A stronger
  option is to refuse it outright.
* **Isothermal segments**: they can appear in a run and Christian has never
  used one deliberately (2026-09-23). They read and draw already - the indium
  run's Equilibrate segment is one, labelled "#1 iso 106 degC" - and on a
  temperature axis such a segment is a dot rather than a curve, which is
  honest but not useful. The Time axis is there for them. Nothing more to do
  until somebody actually runs one with data on; then the question is whether
  a figure should mix the two axes at all.
* **MDSC and multi-procedure files** remain unseen. Not worth designing for
  until one exists.

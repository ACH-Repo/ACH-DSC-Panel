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

### Round 12 (2026-09-25): figures of exact size

Christian: two session files - first up-scans in one, second up-scans in
another - exported with the same size settings must sit side by side in Word
exactly alike, without fiddling.

* **Figure size and margins** (Edit menu, F3), saved with the session:
  follow the window, a fixed aspect ratio, or an EXACT size in cm or inches
  with four margins. The margins fix the axes box - numbers and captions
  live inside them, and the dialog warns when one does not fit - so two
  figures with the same layout have the same axes box to the hundredth of a
  millimetre whatever their numbers say. "Use for new figures" makes it the
  default for new sessions.
* **On screen** the figure is its page, scaled to fit the pane on a darker
  surround: what is shown is the export at a zoom.
* **Exports are exact**: a PNG is width x height inches times its dpi, with
  the dpi in the file so Word places it at its size (axes lines within a
  pixel at 600 dpi, tested); an SVG states its size in millimetres. The
  SVG's fonts had been drawn at 72 dpi - three quarters of their size.
* **Axes on either side** (x bottom/top, y left/right), and their numbers
  and caption can each be hidden (axis settings).
* **The driver export works**: it called two functions the template never
  had and left `datas` undefined. It now builds the figure with the same
  size and axes box (`plt.figure(figsize)`, `fig.add_axes`), fonts, sides,
  truncation and offsets; a test runs it and measures matplotlib's SVG.

### Round 13 (2026-09-26): typed x range, y about zero, offset markers

* **`M` sets the x range by numbers**, as in MestReNova: a two-box pop-up,
  the first number selected so typing replaces it, Tab to the second, Enter
  takes both (either order; a comma is a decimal point; a pair that is not a
  range keeps it open). In the axis's own unit. One undo step, like any
  zoom (`RangeDialog`, `MainWindow.set_x_range`).
* **The plain swipe scales y about y = 0**, not about the cursor: zero keeps
  its place and only the scale changes (`PlotWidget.scale_y`). The pinch
  (Ctrl) still zooms both axes about the cursor.
* **Y-offset markers**, the template's `add_yoffset_markers`: every drawn
  scan labelled with its offset (`+0.5`) a little below the curve on a small
  arrow, in ink, at the house style's "Y-offset markers" size (7 pt, the
  template's). F3: "Show or hide the y-offset markers", and "Y-offset
  markers at a temperature..." to stand them somewhere (stored in Celsius).
  Unplaced, they stand 10 % into the stretch every drawn scan covers - the
  view's edge put a later heating scan's arrow on its start-up hook. Saved
  in the session, drawn in exports, and written into the driver as the
  template's own call (the driver test runs it).

### Round 14 (2026-09-26): groups, markers as objects, the arrow's shape

* **Offset markers are objects** (`model.OffsetMarker`, one per scan as
  `Scan.marker`): picked, box-selected, dragged (along the curve and up or
  down from it), hidden and styled like a label; F3 "Select every offset
  marker". Unplaced, one points 6 units in from the left end of its own
  curve - tight against the y axis where the curve reaches it. Round 13's
  figure-wide temperature is gone; the marker's settings set one (and set
  for several markers, it lines them up in a column).
* **Settings for several objects at once.** A settings dialog opened on an
  object that is part of a selection edits every selected object of its
  kind (`_LiveDialog.set_group`): what changes on the shown one is copied to
  the rest, field by field; a field that belongs to one object alone
  (`INDIVIDUAL`: a label's text, a scan's offset, a position) is not, and
  its widget is greyed. Revert puts all of them back; one undo step.
* **A drag carries the selection** (`PlotWidget.drag_group`): dragging one
  of several selected analysis labels stretches every arrow by the same
  amount; several markers move together. Never a scan, never an axis. The
  first click of a double-click narrows the selection; the double-click
  now puts it back (`_click_restore`), so double-click-drag works on a
  shift-selected group.
* **The heat-flow arrow's shape**, in points as `add_exo_arrow` takes them:
  head length, head width, tip angle, tail length, tail width, and a text
  size (house style "Heat-flow arrow text", 10 pt). Length, width and angle
  of the head are tied (w = 2 l tan(angle/2)); "Lock the tip angle" or
  "Lock the head width" (one at a time) says which stays put, unlocked the
  angle follows. The defaults are the template's (9 / 13 / 4.5 / 8.1 pt,
  71.7 degrees), so the arrow on screen is now the size the template draws -
  smaller than the old 7.5 % of the plot height. The old `length` is not
  read from older sessions. The driver passes all of it to `add_exo_arrow`.
* **No "EXO DIRECTION ASSUMED" on a rendered image** (`warnings_for(doc,
  exo=False)`); the console and the driver still say it.
* **Ctrl+A leaves the axes out.**

### Round 15 (2026-09-27): what a number on the figure may say

* **Analysis labels are templates** (`core/labels.py`). The words are the
  user's; `{}` is the measured value, filled in on every draw. Defaults:
  `*T*_{on} = {}`, `*T*_{end} = {}`, `*T*_{g} = {}`, `\Delta*H* = {}`.
  A unit after `{}` converts (`{} degF`, `{} K`, `{} kJ/mol`); none follows
  the axes. A unit the quantity cannot be in is refused and the value shown
  in its own; one needing a missing molar or sample mass shows `?` and
  every export says NO MOLAR MASS. A number typed by hand beside a unit of
  the quantity is allowed (it may be a literature value) and flagged in
  the settings and on export. Labels no longer store numbers, so nothing
  has to rewrite them; an old session's generated label is read back as
  the default template (session version 4). The rules and their reasons
  are the module docstring.
* **Number formats** (`core/numbers.py`): Python's percent format for one
  number, nothing around it. House style: temperatures `%.0f`, enthalpies
  and other results `%.3g`, offset markers `%+.1f`; each analysis and
  marker can override, each axis has its own (automatic by default).
  `%.Ng` is N significant figures written out - 1.50 keeps its zero, 1230
  never becomes 1.23e+03.
* **Offset markers point at the curve as SHOWN**: kept samples inside the
  view. Placed by a sample index (`OffsetMarker.at = ("i", n)`), found and
  moved by walking ALONG the curve, never by looking a temperature up - a
  second heating that starts above 30 degC doubles back. A typed
  temperature (`("T", c)`) takes the shown sample nearest it.
* **Enter in a settings window commits the field and keeps the window
  open** (`dialogs.enter_stays`), for every live dialog and the settings
  page. The arrow's shape is tuned value against value.
* **The pointer shows while gizmos are up.** The reticle is off then, and
  the system pointer was hidden as well: nothing to aim with. Now a cross,
  and a sideways arrow over a handle.
* **Font family** in Edit > Settings, for the whole figure and the driver
  (`plt.rcParams['font.family']`).
* Found on the way: the console no longer printed the exo warning after
  round 14 took it off images; it prints everything again.

### Round 16 (2026-09-27): the analysis window, S, and units in formats

* **The analysis window**: Model is a drop-down that recomputes the same
  interval as another kind, in place (`MainWindow.change_model`); Start
  and End replace the list of TRIOS field names and are TYPED - `98` in
  the axis unit, `98 F`, `371 K`, `98 c` converted (`units.
  parse_temperature`) - and recomputed as one undo step
  (`retype_interval`). Along a measured stretch the typed temperature is
  found by WALKING the segment from the old cursor (`measure.walk_to`), so
  it stays on its branch. A file analysis recomputed here becomes the
  panel's. Results lists what else was computed, in plain names. "Drawn on"
  is offered only where the scan is a guess (a `.txt` export). "Show",
  "Show interval markers", "Same as scan"; one line of help.
* **A unit in a number format converts**, like one after `{}`: `%.0f F` on
  an onset is Fahrenheit. The label's own unit wins over the format's, the
  format's over the axes'. A house-style format's unit applies only where
  it fits (enthalpies and peak heights share one); an analysis's own format
  with a unit it cannot be in is refused and flagged. An axis format takes
  no unit - its numbers sit on ticks. A marker's format may name a heat
  flow unit and the offset is converted (needing the mass when it does).
* **Offset markers set their scan's offset**: Offset (absolute) and Shift
  by (relative; a group moves together); in the marker's one undo step.
* **S scales artists**, Blender's way: the distance from the pivot (the
  selected artists' centre) is the factor, a typed number overrides it,
  Shift is precision, Ctrl snaps to tenths, Enter or a click keeps it, Esc
  or the right button cancels. The arrow (head, tail and text), the legend
  (text and sample) and labels (text); scans never. The arrow is
  `can_scale` now.
* **Windows are readable**: every label selectable for copying, every
  tooltip wrapped (a plain-text tooltip is one line however long), and the
  tooltips and notes cut to a line each.

### Round 17 (2026-09-27): S and R with pivots, the view in the file

* **The framing is saved with the figure** (`Document.view`, session
  version 5). A y range narrowed to show a peak's label came back fitted:
  the view was never in the file. It is now, so a zoom IS a change (the
  title's `*`, the save prompt), and undoing back to the saved framing is
  clean. Found on the way: the modified check wrote the plot's view onto
  the document, which wiped a just-opened file's view before it was put
  back; it only compares now.
* **S and R, with pivots.** R rotates labels and the legend (Blender's R;
  the arrow is not rotated - its direction is what it says); R with scans
  selected still resets their offsets, and with nothing selected does
  nothing. While S or R is live, X / Y / M / C choose the point it is
  about: X the left edge, X again the right; Y the top, Y again the bottom;
  M the middle of the edge just chosen; C the centre. `S X M` is the middle
  of the left edge. S starts about the bottom left, R about the centre. The
  box and the pivot are drawn while live; the plot claims those keys before
  the window's shortcuts (M is otherwise the x range). Rotation is stored
  per artist (`Artist.rotation`, counter-clockwise about its anchor), set in
  its settings too, and saved.
* **Arrow Offset**, in an analysis's settings and a marker's: the label's
  distance from the curve, positive above, absolute (with Default) or
  shifted relatively (a group moves together). The marker no longer sets
  its scan's offset - that is the scan's settings' job (round 16 read
  "offset" as the scan's; it meant the arrow's).
* **.txt analyses are attributed by the user**: one named only by its step
  is offered under EVERY scan with that step name and counts as attributed
  once shown on one (Christian: it is off until ticked, and ticked on the
  scan he picked). "Show every analysis" leaves those alone. "Drawn on" is
  gone.
* **Bahnschrift** is the default figure font (Windows 10 and 11 have it),
  with a sans fallback list, in the driver too.
* **The legend has no frame by default** (the template's `frameon=False`);
  an older session's frame, which was the old default, goes too.
* A version-4 session could still carry a generated label whose number had
  gone stale (`\Delta*H* = 2.492 J/g` beside a 2.37 J/g measurement): any
  label in the exact shape the panel used to generate becomes the template.
* Windows grow to fit their wrapped text (results and problems were cut
  off). Analysis formats keep their unit through a save.

### Round 18 (2026-09-27): the frame, exports, and the outliner

* **The scale pivot is exact for any anchor.** It was predicted (the box
  times the factor) and a box does not grow in proportion - font sizes
  step, the legend's padding is fixed - so everything but a bottom-left
  anchor drifted. Now the box is measured after each step and the anchor
  moved until the pivot is back where it was.
* **Three axis targets, three windows**: the SPINE (ticks: side, direction,
  a fixed major step or automatic, minor intervals, both lengths, the line
  on the opposite side and ticks on it, grid), the NUMBERS (shown, size,
  format), the CAPTION (shown, text, size, distance). A click on the spine
  or the numbers selects nothing (no orange); a double-click opens its
  window. The default frame is Origin's: closed, ticked on all four sides,
  numbers on two. The driver writes the same (`tick_params`, spines,
  `MultipleLocator`, `AutoMinorLocator(n)`, lengths in points).
* **SVG exports are clipped.** Qt's SVG writer ignores clipping, so curves
  past the y range, shading and interval dashes ran over the margins. The
  plot fences its clipped drawing with two invisible marks and
  `plot.clip_svg` wraps what is between them in a real `clipPath`.
  Interval marks are also cut to the axes geometrically (`_clip_segment`),
  since not every SVG viewer honours a clip on a zero-width line.
* **Exports ask** (`ExportDialog`): the file, and the colours - light for a
  page, or as the theme on screen.
* **LaTeX between dollars** in every text on the figure (`markup_runs`):
  `_`/`^` scripts (one character, or a braced group, as mathtext),
  `\mathrm{}` / `\text{}`, Greek and symbols, `\quad` and friends;
  letters italic in math. Added labels are drawn with the markup at all
  (they were plain text). `^{}` superscripts work outside dollars too.
* **The outliner**: the State column (mass, M, exo, offset, analyses) is
  never cut off - names take the rest and elide, with a tooltip; a press on
  a box and a drag down the list gives every box passed the same state, as
  in ORCA Workbench, as ONE undo step (`UndoStack.begin_group`).
* Also: Edit > Theme; the legend's line width; the colour picker's basic
  colours start with the plotter's sixteen, in its order; the window opens
  maximized.

### Round 19 (2026-09-27): tabs, the stack, pictures

Rounds 12-18 were committed first (`4ab47d0`, Christian's request).

* **Tabs, one per figure** (`FigureTab`: document, plot, undo history,
  saved state). `doc`, `plot` and `undo` are the CURRENT tab's. A session
  opens in a tab of its own (an untouched new one is reused); Ctrl+N is a
  new figure. Ctrl+W closes the pop-up in front, else the tab (asking to
  save), else - on the blank background left when the last tab closes -
  the program. Closing the window asks per tab.
* **The window's place and dock** are remembered (`preferences.json`,
  `window`); the first start is maximized.
* **Exports carry no selection** (`MainWindow.unselected`).
* **Artists stay inside the axes box** when moved (`keep_inside`): their
  whole box, not their anchor.
* **Stack order per object** (`Obj.z`, `model.z_of`, kinds in their old
  order by default): Ctrl+(Shift+)PgUp / PgDown, and the context menu. The
  figure is drawn in that order, clipped where it is measured; picking a
  tie goes to the one on top. Page keys, because brackets need AltGr on a
  German keyboard.
* **ChemDraw's alignment** of selected artists: Ctrl+Shift+Alt+L / R / T /
  B to the outermost edge, C centres side to side, M middles up and down.
* **An integration's label slides**: G, then X, moves it along its
  interval (`Analysis.label_at`), never out of it; Y or nothing is the
  vertical move as before.
* **Click rhythm** (`DOUBLE_CLICK_S`, `CYCLE_S`): a second press at the
  same place within 350 ms is a double-click; 350-700 ms selects the next
  object under the pointer, down the stack and round again; slower is a
  new click. Qt calls anything within the system's interval a double-click,
  so the plot re-reads the timing itself. On trial: if it is bad, it goes.
* **M sets the y range too**, after the x pair (Tab reaches it; an
  untouched y pair changes nothing). One undo step.
* **The driver carries the legend and added labels** (`ax.legend` at its
  place with frame, size, sample, spacing, line width; `ax.text` with the
  markup as mathtext - `export.mathtext` - and the rotation).
* **Pictures** (`ImageArtist`): Ctrl+V pastes one (or an image file copied
  in the file browser), dropping an image file puts it where it lands.
  Moved, scaled (S), rotated (R), layered, aligned, deleted like any
  artist; stored in the session as PNG. Not in the driver.

### Round 20 (2026-09-27): the page, structures, text

Round 19 committed first (`f411f26`, Christian's request).

* **The page zooms like a document**: Alt + swipe zooms the whole figure
  on the pane about the pointer, Alt+Shift + swipe moves it, Alt+F fits it
  again - orthogonal to the swipes that frame the DATA, and neither the
  data nor the figure's proportions change. Windows reports every Alt+wheel
  as horizontal, so the window reads the real direction from the system
  message (`MainWindow.nativeEvent`, `PlotWidget.native_wheel`). The File
  menu's mnemonic is Alt+L now, and Help's Alt+P - "&Help" had been
  taking Alt+H from "Show everything" all along; a test checks mnemonics
  against the operators' keys.
* **F fits the data only without a modifier** (Ctrl+F did the same).
* **Ctrl+Up / Ctrl+Down**: the selected texts one point bigger or smaller.
* **Layer** in every object's settings: its place in the stack as a
  number (`_LiveDialog._layer_row`).
* **Structures from a SMILES** (`core/chem.py`, `MoleculeArtist`): Ctrl+V
  on a SMILES draws a skeletal formula - vector, from RDKit's 2D layout
  (CoordGen), drawn by the plot: labels for heteroatoms with their
  hydrogens on the free side, charges, ring double bonds inside the ring,
  triple bonds, the pieces of a salt side by side. ACS 1996 sizes (bonds
  19.2 px long and 0.8 wide, labels 10 pt); double-click for bond length
  and width, label size, colour, a new SMILES. Rotated, the labels stay
  upright unless switched off. The layout is stored, so a session opens
  without RDKit (an optional extra). Not in the driver.
* **Text pastes as a label**, and labels run over several lines (a
  multi-line box in their settings; lines follow the anchor's side).
  Ctrl+Shift+V pastes text as a label even when it reads as a SMILES.
* **The reticle is the pick distance**: its ring is the radius a press
  acts within, and its ticks and line shrink below the built-in size.
* An empty figure draws what was put on it (a structure pasted into an
  empty tab was invisible).

### Round 21 (2026-09-27): a log, element labels, the page's handles

* **A log** (`core/log.py`): `dsc-panel.log` beside the preferences,
  rotating; every unhandled error with its traceback, hard crashes into a
  `.crash` file (`faulthandler`), files read and sessions opened. Its
  excepthook also keeps the program ALIVE after an error in a Qt slot,
  which PySide6 otherwise ends the process for; the window says an error
  was logged. Help > Open the log folder. No interactive console: nothing
  here needs one, and a console in a figure program invites poking at
  state the undo stack does not know about.
* **Structures**: a label font of their own (the figure's by default) and
  "Colour by element" for the labels (the bonds keep the structure's
  colour).
* **The page's handles**: a click on the page's margin (on the page,
  outside the axes box, on nothing) shows eight handles; dragging one
  shows the page it would make, dashed, with its size. Let go: an exact
  figure takes the new size (margins kept), any other figure the new
  aspect ratio - one undo step - and the page is fitted again, as Alt+F.
  Esc or a click elsewhere puts them away.

### Round 22 (2026-09-27): the desktop, F, the outliner

Testing on the desktop PC with a mouse.

* **The middle-button drag is the mouse's two-finger swipe**, as in MoloM
  (`_nav_drag_kind`: its trackpad scroll orbits, its middle drag orbits) and
  Blender. Same modifiers as the swipe, latched at the press as MoloM does:
  plain scales y about 0 (drag up, taller), Shift pans with the figure
  following the pointer, Ctrl zooms both axes about where the drag started,
  Alt zooms the page and Alt+Shift moves it. One undo step per drag, the
  page ones none (as with Alt+wheel). The same distance as a swipe does the
  same amount (60 px a notch). A middle double-click opens nothing. The
  plain wheel is unchanged: Windows delivers his touchpad's swipes as
  notches too, so the wheel and the swipe cannot be told apart.
* **F makes room for the analysis labels** ("an enthalpy at the highest
  peak is cut off"). The fitted y range (`PlotWidget.data_y`) grows until
  every shown analysis label and its arrow is inside the axes box. Labels
  are sized in drawing units and hang a fixed distance from the curve, so
  the range needed depends on the range: a few rounds of `hi = y + reach /
  height * span` settle it. Worked out once per paint; held still while a
  label is dragged.
* **The outliner: data, a line, Decorators.** Files and their segments on
  top, and under each scan what belongs to that trace: its analyses, its
  own labels, and its offset marker while the markers are shown. Below a
  line, **Decorators**: the heat-flow arrow, the legend, free labels,
  pictures and structures - everything drawn that belongs to no scan
  (pictures, structures and free labels had no row at all). Clicking
  Decorators selects all of them; each row ticks, selects, opens and
  hides like any other. A label's row is its first line.
* Found on the way: a file opened into an empty figure came in folded,
  because the Decorators row made "was anything open before?" true. Rows
  now remember being CLOSED instead.
* On this PC: no Python 3.10 (3.13 runs the tests), and ACH-DSC-Plotter
  here lacks `d743702`, so `vendor.py --check` calls the panel's (newer)
  reader stale. Do NOT re-vendor here: it would roll the reader back.

### Round 23 (2026-09-27): presets, parents, the size in numbers

Christian on round 22: the middle drag "works perfectly", the click rhythm
works.

* **Style presets** (`core/presets.py`): a figure's look in a file,
  chosen from Edit > Style presets (filled from the folder each time it
  opens) or F3 "Apply a style preset...". A preset holds every figure
  setting RESOLVED - the values drawn, not "follow my defaults", so it looks
  the same on another machine - and, optionally, the size and margins, so
  two figures given one preset have the same axes box. Applying is one
  undo step on the figure's column; an object's own choices, the handling
  settings and the theme are left alone. A hand-written preset may name
  only some settings; the rest stay as they are. Files are JSON with the
  extension `branding.PRESET_EXT` (`.dscstyle`) in `presets` beside the
  preferences; "Save this figure's style as a preset...", "Open the style
  presets folder", and dropping a preset file on the window installs and
  applies it. JSON, not TOML: Python 3.10 has no TOML reader.
* **Structure labels**: Arial Rounded MT by default, a house-style setting
  of their own ("Structure labels" in Settings; empty is the figure's
  font), and colour by element on for a new structure.
* **Parenting** (Christian: "giving a free label to a scan is a parenting
  operation"). A label given to a scan stays exactly where it is drawn and
  from then on MOVES WITH THE SCAN's offset - G, stacking, R, typed offsets
  - as well as being listed under it, wearing its colour and going with it.
  Stored as the scan's offset at the moment (`TextLabel.parent_offset`);
  `PlotWidget.artist_point` / `set_artist_point` add and remove the
  difference, so nothing stored is rewritten when a scan moves. Ways in:
  drag label rows onto a scan (or anything under it) in the outliner, onto
  the Decorators to free them; Ctrl+P (selected labels to the one selected
  scan), Ctrl+Shift+P frees (Blender's Alt+P is Help's mnemonic here);
  right-click a label, "Belongs to". G on a scan and its own label moves
  the label once, with the scan. A unit change converts the record with
  the offsets; an older session's owned labels stay where they were drawn;
  the driver places them where they are drawn.
* **The size in numbers**: double-click a page handle for a small pop-up,
  width and height in cm or inches. With "Keep the aspect ratio" (on)
  typing one fills in the other; off, the ratio follows. Enter makes the
  figure EXACT at that size - one undo step - keeping the margins it was
  drawn with, rounded up, so the axes box keeps its room; a page smaller
  than its margins is refused.
* Found on the way: ACH-DSC-Plotter's `d743702` was never pushed, which is
  why this PC's checkout is older than the panel's reader (and why GitHub
  Desktop's clone failed: the folder already is the clone).

### Round 24 (2026-09-28): sharp on screen, S on scans, notes, wedges

Christian on round 23: dragging labels in the outliner, the size pop-up
and Arial Rounded MT work; presets mostly.

* **Choppy curves, spines and numbers on a scaled page.** Three causes,
  all from drawing an exact figure scaled onto the pane (k 1.47 in his
  screenshot): the curve was thinned to one point per FIGURE column, so
  each tread was k pixels wide (`columns` now counts device columns of the
  page as shown); the frame is drawn without antialiasing to stay crisp,
  which only holds where a drawing unit is a whole number of device pixels
  (`_crisp`; elsewhere it is antialiased); and hinted glyph advances,
  scaled, spaced the letters unevenly (`figure_font` lays text out
  unhinted - which also makes the layout the same at every zoom and in
  every export).
* **S on scans spreads them** evenly about y = 0 (`start_spread`): order
  kept, the scan nearest zero on it, the rest at whole steps; away from 0
  wider, towards it closer; a typed number is the step in the axis unit;
  Ctrl a round step; one undo step. The frame holds still during it.
* **The offset arrow has caps**, a dimension line, not arrowheads.
* **A trace's name shows on hover only**, no longer while selected.
* **Alt+P frees labels** (Blender's); Help has no mnemonic any more.
* **The Boombox theme** from ORCA Workbench (`orca_workbench/core/
  theme.py`): #2a2d31 paper, #d6d6c2 text, the LCD green #39ff7a for the
  selection; the window's palette follows (`appearance.boombox_palette`).
* **Presets carry the frame and the furniture**: both axes (caption text
  and sizes, distances, ticks, numbers, sides), the heat-flow arrow's place,
  shape and text size, the legend. Not the arrow's direction (the data's).
  Every value in a file is checked before it is used.
* **Stereo wedges**: RDKit picks the wedged bond at each `@`/`@@` centre
  (`WedgeMolBonds`); drawn as a filled wedge or a hash in the ACS
  proportions (2 pt wide end on a 14.4 pt bond, rungs 2.5 pt apart). A
  structure pasted before this has no stereo in its stored layout: retype
  its SMILES in its settings to redraw it.
* **Notes**: a label with a leader arrow to a point (`TextLabel.leader`,
  [degC, heat flow]). Ctrl+Shift+T at the pointer, or right-click a curve
  "Add a note with an arrow here..." - on a curve the tip lands on it and
  the note belongs to that scan, so it moves with it. Selected, the ring at
  the tip is dragged, snapping onto a curve near it; a label's settings
  turn the arrow on or off. The driver writes `ax.annotate`.

### Round 25 (2026-09-28): SDT, the reader comes home, tangents

Started on the desktop (the weight curve on a second y axis, pushed
unfinished as `4bc9426 "intermediary"`), finished on the laptop. See
HANDOFF.md section 0 for the state of the working tree.

* **ACH-DSC-Plotter is retired** (Christian: "we now have a much better DSC
  and TGA plotter with this project"). The reader is the panel's own;
  `tools/vendor.py` and the test that compared it with a sibling checkout
  are gone - a test must not depend on the state of another folder, and
  that one failed on whichever machine had the other repo out of step.
  `docs/TRI-FORMAT.md` and `tests/test_reader.py` moved here. **The driver
  export is frozen** as it is.
* **SDT runs** (SDT650: heat flow AND weight): the weight is a dashed curve
  in the scan's colour on a second y axis opposite the heat flow's, in % of
  the sample mass or mg (F3 "Weight axis: ..."), with its own row under the
  scan in the outliner, in the legend, the CSV, `M` (a third pair) and the
  session. It follows `M` and `F` only, not the wheel. The heat flow of an
  SDT run is Heat Flow / sample mass, as TRIOS's export has it.
* **The reader reads every signal array** (TRI-FORMAT.md 3, 3b): one layout,
  plain or with per-sample flags; the round-25 code had matched a byte
  COUNT that fitted one run's length only, so most SDT files (CN-81, the
  DESY isothermals) came out wrong. The same flags are why a DSC run's last
  segment looked "partial" and why the indium ramp had "no heat flow": both
  are recorded, in flagged arrays. The indium melt now comes from the `.tri`
  alone, 28.56 J/g, pointing up. Flagged samples are NaN; trailing ones are
  trimmed, leading ones kept (sample spans count from the segment start).
* **Sample mass of an SDT run** is derived from Weight / Weight Change (the
  file has no sample-size field), refused unless positive and constant, and
  called "derived from the weight" wherever it is shown. Three DESY runs
  record a negative weight: no mass, and the placeholders say so.
* **Analysis records**: onset/endset cursors are at +86/+132 (the endset had
  been read wrongly), TRIOS's construction is kept as its three (four for a
  Tg) points, and the curve an analysis was made on (heat flow or weight)
  is decoded.
* **Tangent constructions**: onset, endset and Tg are drawn as TANGENTS -
  TRIOS's own stored construction for a `.tri` analysis, the Python one for
  an analysis made here, chords (the round-10 lines) for a `.txt` export's,
  which has no points, with a note in its settings. Per analysis "Lines":
  tangents / chords / none; house style "Lines" and "Tangent overshoot"
  (6 pt past the crossing). Solid, in the axis colour. "Show interval
  markers" is the dashes alone now; an older session with markers off opens
  with Lines "none".
* **The panel's endset was the onset** (the low cursor was taken as the flat
  one for both), and a cooling onset took its baseline on the wrong side.
  The flat cursor now goes by ACQUISITION order: the earlier for an onset,
  the later for an endset. A saved endset reopens corrected (OJ-12: 94.83
  -> 108.06 degC; TRIOS 108.02).
* **S on scans crashed the program** whenever the pointer was on the plot
  (since round 24): the overlay drew a line to "the centre of the pivots",
  a spread has none, and the ZeroDivisionError mid-paint left Qt with an
  unfinished painter - an access violation, not a logged error. Fixed, and
  `paintEvent` now always ends its painter, so a painting error stays an
  error.
* **The outliner shows the FILE name** (Christian): runs saved as `x.tri`,
  `x(1).tri` share TRIOS's sample name, which is now the row's tooltip. A
  scan's default label follows (file name + segment).
* **Redraws were slower** after the NaN safety (every range query scanned
  every sample for NaN, ~50 times a redraw): spans are cached per rebuild.
  24 curves / 227k samples: 297 ms -> 111 ms (round 21: 267 ms). Drawing
  already keeps at most 4 points per pixel column; what is left is building
  the polylines in Python.
* **Stage 3 (SDT UI findings) is finished** - see
  `stage3_progress.md` (outside the repo) for the per-finding log - but the
  weight-as-a-second-axis DESIGN is under review: Christian, 2026-09-28,
  "TGA data needs to be independently visualisable, even in such a way that
  there isn't even a heat flow y-axis anymore", with m% analyses. See Next.
* Also from the desktop: the curve decimation keeps each column's first,
  highest, lowest and last sample in measured order (`_m4`: steep flanks
  were staircases), a structure's box includes its labels, the Boombox
  reticle is LCD green.

### Round 26 (2026-09-29): TGA scans, and the requests in NEXT.md

The TGA work is PLAN "Next" 1 below (steps 1-3 done there). From Christian's
requests of 2026-09-28 (docs/NEXT.md, now emptied):

* **The unit of an analysis's number** ("I do not see how J/mol or kJ/mol
  can be set"): a "Unit" choice in its settings (`Analysis.unit`, None =
  the axes'), J/g, kJ/mol, J/mol, kJ/g, J, mJ for an integration, the
  temperatures for an onset, % and mg for a mass. Per mole needs the molar
  mass and shows "?" with NO MOLAR MASS without it; a unit written after
  `{}` in the label still wins. Saved.
* **Settings windows scroll** on a small screen: never taller than 85 % of
  the screen (`dialogs.SCREEN_SHARE`); past that the rows scroll and the
  buttons stay below them. Small windows are untouched.
* **A typed number moves a decorator**: G, then a number, is a distance in
  the AXES' units - along x with X (the axis's temperature unit), else up
  in its y unit (a parented label: its scan's). It used to be ignored.
* **Notes**: a new one stands straight above its point, arrow pointing
  down; Ctrl+L / R / M put that edge of its text over the point (as they
  do for an analysis label; Ctrl+M, not Ctrl+C, which is Copy in every
  text field) and line plain labels' lines up; its settings type the point
  ("Points at": a temperature in any unit, a height in its axis's unit),
  choose where the arrow leaves the text ("Arrow from": nearest edge or one
  of the nine points) and give the arrow its own colour; G, then X, slides
  a note that belongs to a scan ALONG its curve, tip and text together
  (`PlotWidget._slide_note`), one undo step with the tip.
* From his testing on 2026-09-29:
  - **The fit is KEPT** ("no matter what you do, the plot is
    automatically rescaled without even pressing F"; a lengthened analysis
    arrow rescaled y): an unframed axis's fit is worked out once
    (`PlotWidget.kept_fit`) and again only by F, or when the set of curves
    on that axis changes (shown, hidden, a unit, a truncation) - never
    because something moved. A moved scan keeps the frame until F.
  - **Fit margins per side** (his `set_side_margins`): house style "Fit
    margin" left / right / bottom / top, % of the data's range (0 / 0 / 6
    / 6 built in; per figure, and the user's default).
  - **A new y axis gets room on an exact figure**: the heat flow's joining
    an SDT run's mass on the right grew nothing, and its caption sat on its
    numbers; the side's margin now grows to fit, in the same undo step as
    showing the curve (`_room_for_axes`); only a newly drawn axis's side,
    only grown.
  - **S on mass curves** spreads about the level of the curve that stays
    put where y = 0 is off the axis (an m% axis runs 80-100 %).
  - **Right-click "Mass at this temperature"** marks every selected mass
    curve at that temperature.
  - **The empty plot's menu**: Fit, Stack evenly, a marker line, and
    Background - White, the theme's, or any colour (`Document.
    background`, saved; exports use it). A light page on a dark theme is
    drawn with the light theme's ink, and the reverse
    (`window.drawing_theme`). Open and Select everything are gone from it.
* **RDKit is a dependency** (pyproject) - an install with `--no-deps` still
  needs `pip install rdkit` - and a SMILES pasted without it says so in a
  pop-up instead of becoming a text label: `chem.plausible_smiles` checks
  the grammar without RDKit (tokens, brackets, ring closures, two atoms).

### Round 27 (2026-09-29): margin gizmos, a colour picker, DTG

Christian's requests of 2026-09-29 (docs/NEXT.md, now emptied), with the
choices he made before they were built:

* **Margin gizmos**: an arrow per fit margin on the page's edge, shown
  with the page's handles - left and top margins at the top-left (on the
  top and left edges), right and bottom at the bottom-right - standing at
  the line where the data begins. A drag shows that line dashed; letting go
  sets the margin (`doc.style.fit_<side>`) and refits that axis, ONE undo
  step (`window.set_fit_margin`: a group of the style change and the fit).
  A click selects an arrow; a typed number (a sum works) and Enter then set
  it, like G and a number. A value that cannot be drawn - negative, or
  leaving the data less than 5 % beside the opposite margin
  (`style.FIT_MOST`) - flashes the line red and changes nothing.
  **The fit margins changed meaning** (his choice): a SHARE OF THE AXIS
  left empty, typed as a fraction (left 0.1 is the first tenth of the x
  axis), no longer % of the data's range. Built in: 0 / 0 / 0.05 / 0.05.
  Old values convert (`style.convert_old_fit`): preferences version 2,
  sessions version 6. Two margins summing past 0.95 are scaled down
  together (`PlotWidget.fit_pads`).
* **A colour picker of our own** (`ui/colour.py`, `get_colour`): a
  hue/saturation wheel with WHITE at the centre, so a saturated colour
  made paler is a move inwards (Qt's picker's bar went darker), a value
  bar beside it, R/G/B and H/S/V boxes, hex, the plotter's colours, was /
  now, and a dropper ("Pick from screen", Esc or the right button stops).
  Live: the figure follows the wheel; closing keeps, Revert puts back.
* **Sums in every number box** (`ui/numbox.py`, `numbers.evaluate`):
  "255-20", "(3+4)*2", a comma is a decimal point; + - * / and brackets
  only, from Python's parse tree, never `eval`. Also in typed
  temperatures ("98+5 K"). Not in the hex field: a sum on a whole colour
  does not say which channel it means.
* **The reticle keeps the theme's accent on a light page**: a white page
  on Boombox drew the light theme's amber reticle and orange selection.
  The drawing-theme flip now changes the INK only; `plot.ACCENTS` (reticle,
  band, selection) stay the document theme's, darkened for paper
  (`set_theme(name, accent=...)`).
* **Opaque shading** for an integration ("Opaque shading",
  `Analysis.shade_opaque`, saved): the fill is the colour the translucent
  one makes over the page (`plot.shade_fill`). The analysis window also
  shows "Shade the area" now; `shade` had no checkbox before.
* **A colour gradient** (F3 "Colour gradient on the selection...", two
  scans or more): one colour, darkest and lightest as mixes towards black
  and white (`core/shades.py`), darkest at the top of the stack unless
  "Lightest at the top"; live, one undo step on closing.
* **DTG** (PLAN Next 3, part): a scan of its own (`SIGNAL_DTG`), a row
  under each SDT segment's mass in the outliner, F3 "Show or hide the DTG
  curves". Worked out from the m% (`core/dtg.py`): the least-squares slope
  against TIME in a window given in kelvin of the ramp (the scan's
  "Smoothing", 2 K), per degree over the segment's fitted heating rate;
  a loss is positive. %/degC or %/min ("DTG axis: ..."). It takes the y
  axis the heat flow otherwise has (`Document.y_signal`); a heat flow shown
  beside it is reported with no axis (`Document.axis_missing`), through
  the same placeholder, blink and export warning as a missing molar mass.
  No analyses on a DTG yet.
* **Ctrl+Z reaching the plot** no longer starts the zoom modes (Z and P
  with Ctrl/Alt/Meta are passed on). Not reproduced through the real
  shortcut here; the hole is closed in case it was that.
* From his testing the same day (round 27b):
  - **Opaque shading is a house style too** ("Integration shading",
    translucent / opaque; `Analysis.shading`, None follows it). The
    tickbox was there, in an integration's own window; he looked in
    Settings.
  - **Tangents meet exactly**: "Tangent overshoot" is 0 built in (it was
    6 pt, both lines ran past their crossing).
  - **Min and max in an axis's settings** ("Range", typed, one view step)
    and **"Lock the current framing"** (F3, the empty plot's menu; per
    axis "Locked" in its settings): F and an unframed axis go to the
    locked range instead of the fit (`PlotWidget.home`). A lock is kept
    with its unit (`Axis.lock_context`) and not used in another. A margin
    arrow unlocks its axis.
  - **Decorators move with the data while zoomed** (all kinds, his
    choice, "we will test this first"): a page place is a fraction of the
    axes box AT HOME - the lock, else the fit (`rel_to_px`, `px_to_rel`);
    zoomed they travel with the data and are cut at the axes; at home
    they are where they were put. A session before version 7 stored
    fractions of the view as shown: `rehome` converts them on opening.
  - **Labels that belong to a curve hang from it like analysis labels**
    ("can't they just behave like an analysis arrow plus its label?"): a
    sample `at` and a distance `dx`, `dy` in figure units. A drag slides
    along the curve and changes the distance; a note's arrow drops
    straight onto the point, its text flush over it (Ctrl+L / R / M); a
    curve name keeps its sideways distance. Settings: "On the curve at",
    "Distance", "Sideways". Given to a scan (Ctrl+P, the outliner) a label
    is hung where it stands; freed it keeps its place. The note arrow that
    shot across the window when zoomed is gone with it. The driver export
    gets their drawn places as a hint (`label_hints`).
  - **Delete closes a file** whose row is selected in the outliner while
    the outliner has the keyboard (several: one undo step); elsewhere
    Delete removes curves as before.
  - **F is one press**: every axis back to its home at once. The two-step
    F (x, then y) is the PXRD window's and useless for DSC; it is a
    DATA-TYPE default now, `core/profile.py` (`FIT_STAGED`), where a
    sibling plotter for spectra sets it back.
  - **The dependency is PySide6-Essentials**, not PySide6: everything the
    panel and its tests import is in it (215 MB installed against 675 MB).
  - **A file's own box in the outliner** shows and hides all its curves
    (ticked: all shown, half: some, none: a file with no curve). It had
    none before; Qt makes a row checkable by default, so a press there
    made an empty box that did nothing, and a rebuild took it away.
  - **Files are renamed** (F2 in place, or "Rename" on the row;
    `Sample.title`, saved; its curves, the legend and exports follow) and
    **dragged into order** (a line in the gap, ORCA Workbench's Transform
    list; `window.move_samples`). **The outliner's order is the stack's**:
    S spreads in it with the top file at the top (R during S turns it
    over), "Stack evenly" likewise (it used to put the first file at the
    bottom), the legend lists in it (`Document.in_outliner_order`,
    `set_sample_order`). **Swap two** (F3, and a scan's menu with exactly
    two selected): their offsets, and of two files the files' places too,
    so the next S keeps the swap.
  - **S keeps the order the offsets have** (Christian, 2026-09-29, taking
    back the outliner order and the spread about zero as "the wrong
    reaction to a problem caused by poor handling"): prearranging a little
    chooses the order, and only ties go by the outliner (its top on top);
    the LOWEST scan stays put and is the neutral line, the others step up
    from it. R still turns the order over; "Stack evenly" orders the same
    way (`PlotWidget.stack_order`).
  - **Tp**: an integration's label can give its peak temperature after
    the enthalpy ("Peak (Tp)" in its settings; house style "Integration
    peak temperature", off built in); `{Tp}` in a label puts it anywhere.
  - **Copy and paste labels** (Ctrl+C, Ctrl+V): pasted as FREE labels at
    the pointer (else just down and right of the originals), in the same
    arrangement, notes with their arrows; given to a curve afterwards
    (Ctrl+P, the outliner). The text goes to the system clipboard too.
  - **Version 1.0.0**, committed and tagged; not on PyPI.
* After 1.0.0 (round 27d, uncommitted):
  - **Change a file's source** ("Change the source file..." on its row,
    PowerPoint's "Change picture"): the SAME sample takes another file's
    data, so its curves keep places, offsets, colours, truncation and
    labels; name, molar mass and exo direction are the new file's; the
    panel's own analyses are measured again; a segment the new file lacks
    takes its curve off. One undo step (`window.change_source`).
  - **Side in every axis window** (spine, numbers, caption): the side the
    axis is DRAWN on, set through the window (`set_axis_side`), which
    knows the mass axis takes the heat flow axis's side.
  - **The offset overlay is quiet**: one thin line with the same short
    cap at both ends; the dashed line across to the axis is gone.
  - **One molar mass per file**: a scan's own override is gone (an older
    session's goes to its file where the file has none), and a
    **calculator** sits beside it ("Calculate...", `core/molar.py`): a sum
    formula (C6H6, brackets, decimals, `*` adducts; "." is a decimal
    point), a SMILES, or a composition in the syntax of his
    calculate_sum_formula.py with his building blocks - read as it fits,
    or as chosen - with RDKit's atomic weights, so the numbers are his
    script's. What it was worked out from is kept (`Sample.composition`).
  - **"Same as parent"**: a label's automatic colour is its curve's, and
    its window now says so.
* Round 27e (2026-09-30, docs/NEXT.md 1, uncommitted): **the page's
  white margins**.
  - **Blades**: a pointed oval per margin of an EXACT figure, shown with
    the page's handles, mostly outside the page's edge where the axes
    box's edge meets it - the right and top margins at the upper right,
    the left and bottom ones at the lower left (the fit-margin arrows have
    the other two corners). Dragged, a dashed line across the page shows
    the new edge of the axes box; clicked, a typed number in the figure's
    unit; double-clicked, down to what the margin holds. Never below
    that: a refused number flashes red. A press ON a page square is the
    square's. One undo step each (`window.set_page_margin`).
  - **What a margin holds** is measured once (`PlotWidget.page_needs`):
    an axis's ticks, numbers and caption, whatever decorator reaches out
    of the axes box, else the frame's line. `overflow` (the figure-size
    window's warning) uses it too - it used to compare with the automatic
    layout's breathing room, so a 0.3 cm right margin with no axis was
    reported as cutting numbers off.
  - **F3 "Tighten the page margins"**: all four down to what they hold.
  - **Room grown for an axis is given back** when that axis leaves its
    side (`FigureLayout.grown`, saved with the session, never in a
    preset), unless the margin was set by hand in between. Every path
    that can hide a curve goes through `_room_for_axes` now (hiding a
    signal, removing curves, closing files).
  - Found on his figure: the white space was NOT grown room. An exact
    figure's margins are its own numbers - 1.9 cm left by default, where
    a 12 pt y axis with its caption holds 1.35 cm - and nothing ever
    tightened them. The blades and F3 do.
  - **A view within 2 % of home is not "zoomed"** (`HOME_TOLERANCE`): his
    session's saved framing, a hair from today's fit, cut decorators at
    the axes. Their places still follow the view exactly.
* Round 27f (2026-09-30, from his testing; uncommitted):
  - **The corner squares are gone**; the page keeps its four edge ones.
  - **Blades stand at the page's EDGE, at its corners**, just outside it
    (right and top at the upper right, left and bottom at the lower
    left): pulled in they cut white space off, out they add some - the
    page grows or shrinks, the axes box keeps its size - and they end at
    the new corner. `window.set_page_margins` does it for the blades, the
    dialog and F3 "Tighten" alike.
  - **Tightening reaches the last drawn pixel**: what a margin holds is
    the caption's natural reach minus the empty rows of its box facing
    the page's edge (`_ink_blank`, drawn once at 4x), and a caption's box
    may hang over the page by that much (`axis_label_rect`) - it was kept
    a unit inside, which pushed it back. Measured on his figure: 0.04 mm
    of white left of the y caption, 0.08 mm under the x caption.
  - **Margins in numbers**: a blade double-clicked opens "Page margins"
    (each at least what it holds, a Tighten button), an arrow "Data
    margins" (shares, two on an axis must leave the data room).
  - **Interval marks have a length** ("Marker length" in an analysis,
    house style "Interval marks", 3 built in, was a fixed 4).
  - **Set the molar mass** (F3, a scan's menu) has the calculator.
  - **The offset shown while moving** has two significant figures.
  - **Decorators stay on the page again by default**; F3 "Decorators
    follow the zoom (on / off)" per figure (`Document.follow_zoom`,
    saved; session version 8). Toggling keeps every one where it is
    drawn (`PlotWidget.reframed`); a version-7 figure is converted to
    page places on opening.
  - **Arrows are one solid colour**: an analysis following its curve is
    the shade 75 % of that colour makes over the page (`mixed`), not a
    translucent 75 %, and a head has no outline of its own (the shaft
    ends at it) - analysis labels, notes, offset markers.
  - **Mirror** pictures and structures: Ctrl+Shift+H left-right,
    Ctrl+Shift+V top-bottom (a structure's wedges and hashes swap, so it
    stays the same molecule). Paste as text moved to Ctrl+Alt+V.
  - From his testing of the mirror: a ring's double bonds went OUTSIDE
    the ring - each stores its ring's centre (`bond["ring"]`), which did
    not mirror with the atoms; now it does. A turned structure is mirrored
    left-right ON SCREEN (along its own axis, its rotation reversed), not
    along its own axis alone. And a turned structure's box missed the H of
    an OH: labels are kept level, so their hydrogens' side is decided
    after the turn - `_molecule_layout` now takes each label as drawn and
    turns it back (a pixel test checks every oxygen pixel is inside).
  - **A file with no curve can be closed** ("Close ..." on its row, one
    undo step; `window.close_sample`): CN-58 in his figure could not be
    taken off at all.

### Round 28 (2026-09-30): the axes and the page margins

From his testing of 1.1.0 before the upload, on `Hbc_Tgs.dscpanel` (y axis
on the right, 0.17 cm left margin). `tests/test_round28.py`.

* **Double-clicking the y axis**: nothing failed in a clean state, so three
  causes that each made it do nothing were fixed. `Axis.visible` is the
  CAPTION's, and `objects_at` skipped the spine and the numbers whenever
  the caption was hidden. The line itself and the ticks pointing in (the
  default) were inside the box, where the spine band does not reach: now
  the axis's lines - its own and the mirrored one - and its inward ticks
  are the spine too (`frame_line_gap`), but only when nothing else is
  within the pick distance, so a curve along the frame stays a curve. And
  a double-click slower than 0.35 s is a layer step, which leaves axes
  out, so on an axis it did nothing: on an axis it now opens. A click on
  the spine or the numbers clears the selection like a click on nothing
  (it left the selection alone), and a right-click there no longer
  selects the axis.
* **An axis moved to its other side takes its room with it**
  (`window._to_side`): on an exact figure the two margins keep their
  WHITE space - what each had beyond what it held - so the side the axis
  comes to grows to hold it and the side it leaves shrinks, in the same
  undo step; the axes box keeps its size. The margins used to stay, and
  the numbers were cut off until a blade was touched.
* **Numbers at the corners of the box are never cut off**
  (`_numbers_overhang`, part of `page_needs`): an x number on the box's
  corner is centred on it, so half of it hangs over the margin beside -
  which, with the y axis on the right, held nothing else, and a blade or
  Tighten cut the 50 in two. Likewise a y number above or below the box.
  To the last drawn pixel (`tightBoundingRect`).
* **Hidden numbers**: right-click a number, "Hide the number 50" (its tick
  stays); "Show every number" brings them back. The Numbers window has a
  "Hidden" field (typed like several temperatures: ";", ", " or a space).
  `Axis.hidden_numbers` with `hidden_context` - the unit they were chosen
  in, like a locked range: a 50 hidden in degC is not a 50 in K. In the
  session, not in presets. A number shown again on an exact figure gets
  its margin back (`_hold_margins`).
* **X and Y lock a caption's move** (G or a drag): X was refused ("A scan
  does not move along x") because an axis is not an artist. Both are
  screen directions: X keeps an x caption at its height and a y caption
  at its distance from the axis.
* **Offset markers per selection**: "Show or hide the y-offset markers"
  acts on the selected scans, every scan when none is selected - shown
  when any of them has none, hidden when all have one; the figure's switch
  goes off with the last marker. H on a marker already worked (his figure
  had five hidden); the toggle is now the way to bring one back.
* **The Format box of the numbers** is `number_format` (`%.0f`, `%.1f`,
  `%.2g`; empty is "as few digits as the tick spacing needs"). Its tooltip
  spoke of units, which an axis's numbers cannot carry; it now explains
  the format, and a "Written" row shows what the axis writes with it.
* Found on the way: `QT_QPA_FONTDIR=C:/Windows/Fonts` gives the offscreen
  platform real fonts (CLAUDE.md, "Running it"). And in his figure the
  "ZIF-62" label hangs from CN-103's HIDDEN first up-scan, above the page:
  Tighten would make the top margin 2.26 cm to hold it. Not changed.

### Round 29 (2026-10-01): what S holds still, family-wide

Christian, 2026-10-01: "the scale with S for offsetting could be improved
for all current and future plotters by allowing to change the reference
point of the scaling operation by pressing T/B/M while scale is active".
The first change made family-wide by his new standing rule (his global
notes): the same patch in Triplot and IR-Panel, and the same test file,
`tests/test_family.py`, in both.

* T, B and M during S on curves hold the top scan, the bottom one (as
  before, and where S starts) or the middle of the stack still
  (`PlotWidget.spread_anchor`). The step reached is kept; the dashed
  neutral line moves to the held place; the status line names it. R and
  Esc work as before. X, Y and C still mean nothing to a spread; on
  artists, S keeps its X / Y / M / C pivots.
* Second pass, the same day, from his screenshots: the held place is where
  the curve IS when the key is pressed (the first version took where it
  was when S began, and the stack jumped on every key), and the line runs
  through the held curve - at the offset it sat ~100 %T below a
  transmittance and looked like y = 0.
* Same day, after his question about the trackpad: the plain swipe makes
  every curve taller or flatter IN ITS PLACE (`scale_intensity`) -
  MestReNova's gesture and MoloM's PXRD window's, family-wide at his word.
  It reverses round 13 of Triplot ("scale y about y = 0") and the
  docstring that said MoloM's intensity gesture "must not exist here"
  because a W/g axis would lie: here the axis is scaled and the offsets
  follow, nothing is multiplied, so the numbers stay true. Each curve
  keeps its BASELINE in place (`profile.baseline`: a %T spectrum's near
  its top, a heat flow's median). The old proportional spread is P during
  S, his choice.
* **The source is ASCII again** (golden rule 6): 89 lines in 12 files
  held a degree sign, a minus, an integral, a Delta - the old test only
  looked for dashes, so they got in. Code strings now carry escapes
  (`"\u00b0C"`, the same value), docstrings and comments words (degC);
  the AST with docstrings set aside is unchanged apart from two raw
  regexes, checked by matching. `test_the_source_is_ascii` (as in
  IR-Panel) keeps it so. `tools/gen_operators.py` writes ASCII: printed
  by a Windows shell, "%/\u00b0C" had arrived as one cp1252 byte.
* Same day, a batch from his use of IR-Panel, family-wide at his word:
  the pan draws (it slid the whole page); drafts while a hand is at work
  and after every change, the full drawing when it settles (measured: the
  line width is the cost, not antialiasing, which had only ever been off
  for the frame, for crispness); numpy point lists; align shows at once
  and moves labels on curves; space artists evenly; a box selects
  artists; the hex field beside every colour; "Inherit" (a colour that
  follows another object's, saved); a label given to a curve wears its
  colour; a label on a curve placed by x and y (his choice: it still
  hangs). The page-margin blades were there all along in IR-Panel: they
  show on an exact-size figure only, and his was a fixed aspect ratio.
* Same day, more from his use: the blades on every figure, making it
  exact from the screen on first use (orange note) - and the size window
  going exact from the screen too (his: "the default size settings ...
  all sizes completely out of whack"). Sessions look for moved files
  beside themselves; IR-Panel keeps copies inside (~0.75 MB for ten .sp
  files), Triplot not (.tri files are big; his call). Asked, not
  built: a figure in Word that opens the panel on a double-click (a COM
  OLE server, the ChemDraw way: possible with pywin32, a large fragile
  project; the light alternative, the session inside every exported
  picture, offered and declined for now).

### Round 30 (2026-10-02): labels by name, the pick distance

Christian, 2026-10-02: labels "spawned with default names without having
to type one first", for all selected lines at once, "across panel
plotters"; lower right of each line in PXRD, upper left in IR (if
transmission), upper right in DSC; and the default pick distance 8
"across projects". Family-wide, the same patch in the three members and
two tests in `tests/test_family.py`:

* `Ctrl+T` asks nothing: on selected curves a label each, the curve's
  name, hanging from its end at `profile.name_label_corner`
  (`MainWindow.name_labels`, `PlotWidget.end_sample`); on nothing, a free
  "Label". New labels are selected. His answer for IR in absorbance:
  lower left (the mirror of transmittance).
* The pick distance is 8 px built in (was 14).

### Round 31 (2026-10-02): colours on a white page, family-wide

Christian: why a yellow came out olive on a white page. On a white page
(and every export) only the default screen palette is darkened now
(`paper_colour`); a picked colour is drawn as picked - his choice, for the
whole family. (The selective swipe and "xN" factors he asked for in the
same message went to PXRD-Panel only.)

### After 1.2.0 (2026-10-02): an onset's label, which side

Christian: onsets always spawn at the bottom, "the wrong way around".
`PlotWidget.peak_points_up` read the side from the curve against the chord
between the interval's ends - right for a peak, inverted for an onset or
endset, whose interval is a FLANK (flat, then bending away: the chord lies
on the peak's side). Now an onset or endset is read from its flat end (the
first sample measured for an onset, the last for an endset): the label goes
where the peak goes. `_covered` takes any analysis's cursors, so a typed or
a file's onset is read the same way. Mass curves keep the chord. Released as
1.2.1 the same day (his call).

## Settings windows in order (2026-10-05): settings windows in order, family-wide

Christian, with two screenshots (a region's "Spectra" list, a band
marker's "Arrow colour"): text boxes at the top of their pop-ups, the rows
in an intuitive order - what is most likely edited after making the
object, and what only the window can edit, first; text and colour very
high. Asked: why a region has a spectra list (it is what a MAGNIFYING
region magnifies - one class for highlight and magnify), and why band
markers have arrow rows (labels, notes and markers share `LabelSettings`;
the rows belonged to notes). His word: all three panels, the arrow rows
off band markers, the proposed order.

* `_LiveDialog.FIRST_ROWS` / `LAST_ROWS` / `row_order()`, applied by
  `_buttons` through `order_rows`. Orders: band marker Text, Line at,
  Colour...; note Text, Colour, the arrow...; label Text, Colour, Size...,
  Leader arrow; region Text, From, Colour, Shade...; distance arrow Text,
  Colour, From, To...; analysis Label, Shows, Colour, Number format,
  Model...; offset marker Number format, Colour...; structure SMILES,
  Colour...; caption Text, Shows, Size...; heat-flow arrow Label, Colour...; Show and Layer last.
* A note's rows are shown only while it is a note (they were greyed);
  never on a band marker. A region's curve list only while it magnifies.
* Test: `test_settings_windows_put_the_text_and_the_colour_first` in
  `tests/test_family.py`.

## F3 (2026-10-05): F3 remembers, aliases of your own, family-wide

Christian: show the F3 option used last when the search opens again; and
custom aliases, user/installation specific, shareable as a .json dropped
on the viewport, with a reset to factory. His choices: a recent list (not
the last query typed back), family-wide.

* `core/userops.py` (the same file in every member): `recent` /
  `note_used` (5, newest first), `aliases` / `add_alias` /
  `remove_aliases`, `export` / `read_shared` / `merge` / `install`,
  `reset`; kept in `operators.json` beside the preferences.
* `OperatorRegistry.search(..., extra=)` searches the user's aliases, and
  ranks an operator whose alias starts with what was typed first.
* `OperatorPalette`: "Used last" and "Every operator" headings when the
  box is empty, the newest recent selected; a column for the user's
  aliases (greyed); right-click: "Add an alias...", "Remove my alias".
  The window's `previous` text was never set (dead since Triplot); the
  window builds the palette in `operator_palette` and records a choice
  in `palette_ran`.
* Edit > Operator search: save the aliases as..., install from a file...,
  reset to factory (asked). A dropped alias file installs (asked, with
  what it adds; unknown operators skipped and said).
* Tests in `tests/test_family.py`.

## The source file (2026-10-05): the source file, typed or pasted

Christian (a PXRD file window): set the source file there too, by
browsing or by pasting a full path, the quotes Windows adds stripped. His
word: all three panels, the file's window and the curve's.

* `dialogs.SourceRow` (a path box and Browse...) in `SampleSettings` and
  `ScanSettings` (Triplot's curve window had no File row; it has one now,
  after Analyses). `clean_path`: spaces, quotes, file:/// links.
* `_LiveDialog._source_chosen`: the window closes, `change_source` runs
  (its own undo step), the window opens again on the new file.
  `MainWindow.ask_source_path` is the file dialog both use.
* Test in `tests/test_family.py`.

### Round 32 (2026-10-07): the swipe per axis, the DTG's peak

Christian (docs/NEXT.md 2-4). `tests/test_round32.py`.

* **The swipe on a selection rescales the selected curves' OWN y
  axis** (`PlotWidget.swiped_axes`, `scale_intensity`): the heat flow
  and the m% made taller or flatter one at a time, every curve on the
  axis in its place, as the plain swipe; both axes when both have a
  selected curve; the main axis with none selected. A hidden curve, or
  a heat flow beside a DTG (no axis), does not decide. The status bar
  says which axis. Triplot only, by his choice (2026-10-07): PXRD-Panel's
  per-pattern `multiplier` is not for DSC (nothing is normalised).
* **DTG: "Peak temperature"** (`measure.DTG_PEAK`, `dtg_peak`): the
  measured sample farthest from the line joining the stretch's ends,
  by its span (a drag) or its temperatures (typed); `*T*_{p} = {}`.
  Offered on DTG curves only - every other model reads the heat flow
  (`_series`), which a DTG segment may not even show.
* Asked: how to show TG, DTG and DSC together. The established ways:
  one plot with an outward-offset third y axis (TRIOS, Proteus,
  STARe), or panels stacked on a shared temperature axis (papers).
  He keeps two figures for now; nothing built (the DTG still takes the
  heat flow's axis).
* **Mass lines** (his `plot_SDTs.py`, `add_onset_manual(...,
  showmass=True)`): an analysis with a point on an m% curve
  (`Analysis.has_mass_line`: onset, endset, mass at a temperature) can
  draw a dashed 0.7 pt line across the axes at the height of the point
  its label points at (`PlotWidget.mass_line`), UNDER every curve (its
  own paint item, `MASS_LINE_Z`), its m% without the offset written at
  the left edge just above it in the analysis's colour and label size
  (`_paint_mass_text`). "Mass line" in the analysis's settings, off
  until ticked; saved; house style "Mass lines" `%.1f`, as his script
  rounds. The value is the curve's at the nearest sample, like his
  `y_at_nearest_x` (a mass-at-temperature's own number takes the first
  sample at or past: a sample apart on coarse data).
  - From his first look (a screenshot: values over labels, lines across
    everything): the value is DRAGGED along its line (`Analysis.
    mass_at`, a share of the axes' width) and a little up or down
    (`mass_dy`, within `MASS_REACH` beyond half its height), through a
    handle of its own (`model.MassText`, `Analysis.mass_text`: a click,
    double-click or right-click on it is its analysis's). The line is
    thinner than the curves (house style "Mass line width", 0.5
    against the curves' 1) in its own dashes (`MASS_DASH`, unbroken
    across runs), under everything, and drawn at a quarter of its
    colour (`MASS_FADE`) where it passes behind something
    (`mass_obstacles`): a curve, an analysis label, its arrow, its
    tangents and dashes, a mass line's value, a decorator - worked out
    from where they WILL be drawn (`analysis_label_geometry`, now
    shared with the painting; `artist_box`), since the line goes
    first.
  - G on a selected value moved the analysis's LABEL: a click on the
    value selected its analysis. The value is now selected itself (in
    `Document.objects()` while its line shows, orange when selected);
    G, X and Y move it, H hides its line (`MassText.visible`).
* **Colours as on the screen, family-wide**: his CAU-Ga export drew
  the default palette's orange "nearly brown" - `paper_colour` still
  darkened `model.PALETTE` on white (2026-10-02 spared only picked
  colours). Shown hue-keeping darkening at 3:1 and 3.5:1 and the screen
  colours, he chose the screen colours, for every member.
* **TRIOS's Excel export** (his request: CSV and Excel "equivalent to
  the one in TRIOS"): File > Export as TRIOS Excel workbooks
  (`export.write_trios_excel`), checked cell by cell against three .xls
  files TRIOS wrote (opened through Excel): a Details sheet (Filename -
  the export's own name, in lower case - instrument, operator, run date,
  sample name, the procedure), then a sheet per step, named as TRIOS
  names them (no "/", "-2" after a repeat, the LAST 31 characters), its
  step name, column names, units, and every sample with the flagged
  ones as empty cells - which is why `_trim_empty_ends` now keeps the
  tail aside. An SDT run's weight in % is "Weight" there. Segments on
  the figure, the selected curves' only if any; one workbook per file.
  openpyxl joins the dependencies. A procedure longer than 127 bytes
  read as missing: .NET writes such a length in two bytes
  (`trios_io._meta_string`).
* **The measured data as text** (his word: "the most simple format
  imaginable", never read by TRIOS, so our own): File > Export the
  measured data (tab-separated), `export.write_data_text`. The Excel
  export's segments and columns, a .csv per file named as the file:
  the run's details (`profile.details`, the exotherm) on "#" lines, then
  "# Segment n: step name", a header row "Segment", "Time (min)",
  "Temperature (degC)"..., every sample with its segment's number
  first, `%.8g` (an instrument's float32 holds no more), "." always, an
  empty sample an empty cell. One file per run beside another of the
  same name gets "-2" (`MainWindow._export_per_file`, shared with the
  Excel export).

## The missing file (2026-10-08): missing files kept, found again - family-wide

Christian (2026-10-08): a Triplot session copied about "lost its data
source" - its file had been saved from Downloads as `x(1).tri` and lay
beside the session as `x.tri`. The look beside a session is by exact
name, so the file was missing, and the outliner showed nothing at all.
He chose, for the whole family:

* **The file keeps a row** (`model.MissingSource`, `doc.missing`): its
  name in red, MISSING, its saved path on the tooltip. What the session
  held of it - the file's entry, its curves', the labels hanging from
  them - is KEPT and put back into every save at its place
  (`session._keep_missing`), colour links, span ends and region curves
  moved to match. Before, the next save lost all of it.
* **Right-click: Locate...** (by hand), **Find in a folder...** (his
  idea: `os.walk` under a folder he names, the same extension, the name
  at least 0.85 alike by difflib - `session.similar_files`), Details...,
  Forget (one undo step). A copy's "(1)" / " - Copy" counts as the same
  name and comes first, then names with the same numbers: "Run-2" is as
  alike to "Run-1" as "Run-1(1)" is, so a search only OFFERS
  (`FoundFilesDialog`, the likeliest chosen), and the automatic look
  beside the session stays by exact name. Found, the figure is opened
  again from its own state with the new place (`found_sources`,
  `session.from_state(..., found=...)`): everything back, the undo
  history cleared, changed until saved.
* **Details...** on every file's right-click menu (his request: two files
  of one name): folder, size, created and modified, SHA-256 of the
  contents, and what the run records (`profile.details`); Copy puts it
  on the clipboard. Not modal, so two can stand side by side.
* Found on the way: a colour link names objects by their place in the
  file, and with a file missing the places moved - a link joined the
  wrong curves. `from_state` now restores them through the places in
  the FILE (`_saved_target`).

Test in `tests/test_family.py` (the
same file in every member).

## Next

1. **TGA as a first-class plot** (Christian, 2026-09-28, with his target
   script: stacked m% curves, "mass at temperature" arrows with the value
   above, a dashed vertical marker with a rotated label, a structure).
   Agreed with him, in this order:
   1. DONE - **the m% curve is a scan of its own** (`Scan.signal`,
      `SIGNAL_MASS`): its own tick in the outliner (an SDT segment is two
      rows, mass first), offset (in % or mg), colour, label, G, S, legend,
      parented labels, sessions (`"signal"`; a round-25 session's weight
      opens as a mass scan), CSV ("Mass/%"). An SDT file OPENS WITH ITS
      MASS ONLY. The round-25 `WeightCurve` is gone.
   2. DONE - **the axes follow what is shown**: a mass alone is one y axis
      (m%) on the main side and there is no heat flow axis; both shown, the
      mass keeps the main (left) side and the heat flow goes right. The
      wheel, pinch, pans and zoom band work on the main axis; the other
      follows M and F. F makes room for labels on either axis.
   3. DONE - **Mass-at-temperature markers** (his `add_annot`): an
      analysis "Mass at temperature" on a mass scan (`measure.mass_at`,
      one cursor stored as both), the m% of the first measured sample at
      or past the temperature, offset not in it, "99 %" above the point
      on a leader arrow in the curve's colour. F3 "Mass at temperatures..."
      (typed, axis unit, ", " / ";" / space separated - a bare comma is a
      decimal point) on the selected mass curves or all shown, one undo
      step; right-click a mass curve "Mass at this temperature". House
      style "Masses" `%.0f`. mg uses the recorded mg where the file has
      them (a run with no usable sample mass still labels its mg). The
      analysis window shows "At" instead of Start/End; the model list of a
      mass curve offers only its models (`measure.models_for`).
   4. DONE - **m% onsets**: TRIOS's own onsets made on the weight are the
      mass scan's and draw their stored construction in % on its curve
      (`measure._BASE_OF` "Weight Change" -> %); Onset and Endset are
      offered on a mass curve and measured on its mass (`_series`,
      `series_unit`). A construction in % is never drawn on heat-flow axes,
      nor one in W/g on a mass's.
   5. DONE - **A marker line** (his `mark_peak`): a label with `vline` (a
      temperature in degC): a dashed vertical line across the axes, the
      text upright on it on a background box; sideways moves the line, up
      and down slides the text; picked anywhere along the line; "Line at"
      (typed, any unit) and "Dashed" in its settings. F3 "Add a marker
      line...", or right-click the plot beside the curves (not a curve's
      menu, which stays at four entries).
2. **Christian's open questions from round 25** (HANDOFF.md section 0): the
   Python onset fit vs TRIOS's (1 K median), the label arrow vs the
   tangents' crossing, the cooling Tg's sign, the Weight Corrected Heat Flow
   fallback, CSV blanks.
3. **Weight analyses**: a mass step between two temperatures, and the
   residue. (Onsets on the weight, the DTG and weight offsets are done.)
4. **A preset as the user's default** (a preset goes onto one figure;
   Settings holds the defaults).

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
* ~~Picking an object buried under others~~: settled by the click rhythm
  (round 19; "click rhythm works", round 24).
* **Isothermal segments**: they can appear in a run and Christian has never
  used one deliberately (2026-09-23). They read and draw already - the indium
  run's Equilibrate segment is one, labelled "#1 iso 106 degC" - and on a
  temperature axis such a segment is a dot rather than a curve, which is
  honest but not useful. The Time axis is there for them. Nothing more to do
  until somebody actually runs one with data on; then the question is whether
  a figure should mix the two axes at all.
* **MDSC and multi-procedure files** remain unseen. Not worth designing for
  until one exists.

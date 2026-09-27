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

## Next

1. **Controls on a mouse** - Christian tests on his desktop next: the
   plain wheel (read as a swipe: scales y about 0), Ctrl+wheel (zoom both),
   Shift+wheel (pan), Alt+wheel (page zoom) and Alt+Shift+wheel (page pan,
   which relies on the Windows message for its direction), press vs drag
   near curves and artists, the click rhythm, the outliner sweep, the page
   handles. There is no middle-button pan.
2. **Tangent constructions** for onset/endset and Tg, if wanted.
3. **Style presets** as dropped files chosen from a menu (TOML needs
   `tomli` on Python 3.10, or JSON).
4. **Pictures, structures and free labels in the outliner.**
5. **Structures**: stereo wedges; the driver writes them only as a comment.
6. **A note with its own leader arrow** as an artist.
7. **Closing a file** (`Document.close_sample` exists, no operator).
8. **SDT / TGA** - parked.

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

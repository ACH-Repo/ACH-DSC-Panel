# Working on DSC-Panel

Notes for whoever (or whatever) picks this up next. **Start with
`docs/HANDOFF.md`**: the state of both repos, what is uncommitted, and what
the chat that built this settled. Then `docs/PLAN.md` for where the work is
going; this file is about how it is done here.

## Golden rules

1. **`core/` never imports a UI.** The model, the units, the arranging, the
   undo stack, the session and the exports are plain Python and numpy, so
   they are testable without a window. Qt lives in `ui/` and in
   `register.py`. Same rule as MoloM and ORCA Workbench.
2. **The name lives in `branding.py`.** A test fails if `DSC-Panel` or
   `dsc-panel` is written anywhere else outside prose. A rename is that
   module, the two entry points in `pyproject.toml`, and
   `register --clean-legacy`.
3. **Never write a parser fixture from memory.** The reader
   (`core/trios_io.py`, `core/trios_analysis.py`) is this repo's OWN since
   ACH-DSC-Plotter was retired (2026-09-28): fix it here, never "in the
   Plotter", and there is no vendoring any more. `docs/TRI-FORMAT.md` is the
   format; `tests/test_reader.py` compares every `.tri`/`.txt` pair on disk.
   If a format question comes up, ask Christian for a real file - he has
   them and will provide one. `tests/conftest.py` builds a synthetic sample
   in the shape the reader RETURNS, which is a different thing and is
   allowed. A test must never depend on the state of another repo's
   checkout (the old vendor drift test failed on whichever machine had the
   other repo out of step).
4. **Nothing is normalised, and nothing is assumed.** No scaling a curve to
   its own maximum, no default molar mass, no silent sample mass. When a
   value is missing, the program says so where it would have been used - see
   `units.missing`, the placeholder in `ui/plot.py` and
   `export.warnings_for`.
5. **Python is exactly 3.10.0** (`C:\Program Files\Python310`). No `X | Y`
   annotations, no match statements.
6. **No em-dashes, ASCII in source.** A plain `-`. PowerShell 5.1 reads a
   file without a BOM as cp1252 and mangles anything else. A test checks.
7. **Never commit or push unless Christian asks in that message.** Finishing
   a piece of work is not an implicit request to publish it.

## Where things are

| File | What it owns |
| :-- | :-- |
| `core/model.py` | `Document`, `Sample`, `Scan`, `HeatFlowArrow`, selection |
| `core/units.py` | mW / W/g / W/mol, exo vs endo, what a unit needs |
| `core/loader.py` | path -> `Sample`, and the exotherm-direction detection |
| `core/arrange.py` | stack, distribute, align (the closed-form `y_align`) |
| `core/undo.py` | commands, gesture merging |
| `core/session.py` | the `.dscpanel` file |
| `core/style.py` | the house style: object -> figure -> user default -> built-in |
| `core/figure.py` | the figure's size: window, aspect ratio, or exact size and margins |
| `core/presets.py` | style presets: a figure's look (and size) in a file |
| `core/labels.py` | what an analysis label says: templates, units, the rules |
| `core/chem.py` | a SMILES as atoms and bonds to draw (RDKit, optional) |
| `core/log.py` | the log file, the excepthook, the crash file |
| `core/numbers.py` | how a number is written: the `%.3g` formats |
| `core/export.py` | CSV, the driver bridge, and the export warnings |
| `core/ops.py` | the operator registry (copied from MoloM, keep in step) |
| `ui/plot.py` | the painted plot: view, gestures, picking, drawing |
| `ui/window.py` | operators, menus, docks, drops, exports, undo |
| `ui/settings.py` | Edit > Settings (`Ctrl+,`): the two-column house style page |
| `ui/appearance.py` | the application palette, following the plot's theme |
| `ui/outliner.py`, `ui/palette.py`, `ui/dialogs.py` | the rest of the UI |

## Traps already paid for

* **`segment` from the reader is 1-BASED** (`trios_io` writes `j + 1`).
  Reading it as an index draws every analysis one scan too low, and the
  result looks plausible. `Sample.analyses_for` handles it, and
  `tests/test_realdata.py` catches a regression by integrating the peak.
* **Temperature is not monotonic.** Every segment reverses direction a few
  times and cooling runs backwards, so `np.searchsorted` is wrong. The plot
  clips with a mask, splits into contiguous runs and decimates by
  consecutive pixel column.
* **`re.sub` with a string replacement eats backslashes.** Every replacement
  in `export.write_driver` carries Windows paths, so they are function
  replacements.
* **`QWidget.grab()` already exists.** The transform is `start_grab`; naming
  it `grab` shadowed the screenshot method and broke every test that took a
  picture.
* **A shortcut claimed twice fires neither** (Qt reports an ambiguous
  overload). `_install_shortcuts` raises at startup instead.
* **A modal `exec()` in a test hangs rather than fails.** Menus and dialogs
  are built separately from being shown; tests build them. (Walked into it
  again writing the outliner regression test: `Outliner._menu` SHOWS a menu.)
* **With the log installed, a slot error is logged and SURVIVED** (round
  21): PySide6 hands it to `sys.excepthook`, which `core/log.py` sets in
  the real program only. Tests do not install it, so there the old rule
  below still holds - and a test must not rely on either.
* **An exception inside a Qt slot is not a traceback, it is an abort.**
  PySide6 terminates the process. So a crash with no output is usually an
  ordinary Python error in a slot: the outliner's row keys come in two
  shapes, `("scan", id)` and `("segment", id, seg)`, and unpacking the
  three-part one into two variables killed the program whenever a not-shown
  segment row was selected.
* **Never rebuild a tree from inside its own signal.** `clear()` deletes the
  row the click is still inside. The outliner defers `visibility_changed`,
  `segment_toggled` and `activated_object` with `QTimer.singleShot(0, ...)`,
  and `refill` refuses to run re-entrantly.
* **A Tg record is not a cursor pair.** It holds four (x, y) pairs, and the
  generic "+132 is the second cursor" read gives 0.0. See TRI-FORMAT.md
  section 5 in ACH-DSC-Plotter; the panel only consumes the result.
* **A `.txt` export has no watts and its mass hides in `[Procedure]`.** The
  heat flow carries its own base unit (`Scan.heat_flow` returns
  `(values, base)`), so conversions ask for what they actually still need -
  from W/g it is the mW axis that wants the sample mass, not the per-mole
  one.
* **An artist is not data.** `PlotWidget.is_artist` decides what may move
  along x: the heat-flow arrow may, a scan may not. Anything new that is
  drawn on the figure rather than measured belongs on the artist side.
* **The arrow's y is a fraction measured from the TOP of the plot**, so a
  drag that adds to it moves the arrow down. Getting that backwards is what
  made it feel inverted.
* **A theme is a dictionary in `ui/plot.py`**, applied by `set_theme` into
  module globals. Everything drawn reads those names, so a new theme is an
  entry in `THEMES` and nothing else. `doc.theme` holds the name; the window
  applies it on every refresh, and exports force the light one.
* **A drag acts on what it starts NEAR** (Christian, round 9). Within the
  pick distance (a setting, 14 px built in) of a curve, a press-and-drag
  marks an interval and asks for the analysis on release; near an artist,
  an analysis label or an axis caption it moves it; anywhere else - or with
  Shift - it is a box select. Released unmoved, a press is a click. A
  double-click opens settings; a double-click-drag does what a drag does. A
  scan moves with `G` or a typed number and NOTHING else.
  Round 8 had "one press selects, two act", and it failed in his hands: a
  Windows touchpad's tap-and-drag arrives as ONE press plus a drag, never as
  a double-click, so it was a box every time. Test gestures through Qt's real
  pipeline (`QTest` on `window.windowHandle()`), not only by calling the
  handlers, which is how that was missed.
* **Selecting a buried object in an overlapping stack is unsolved.** Click
  cycling was considered and dropped (Christian, round 9): the second click
  of a cycle is a double-click, which opens settings. Needs another
  mechanism; see PLAN.md, open questions.
* **Zoom, pan and fit are undo steps** (round 9 reversed round 1's "undo is
  for the document"). The plot turns a gesture into ONE step - a wheel or
  pinch burst ends after `VIEW_SETTLE_MS` of stillness - and emits
  `view_committed`. Undo and redo call `plot.commit_view()` first, or a
  Ctrl+Z pressed mid-burst undoes the step before and the burst then lands
  on top and erases the redo. A framing taken in another unit restores as
  the fit, not as meaningless numbers.
* **A styled size is None until someone chooses it.** `Analysis.label_size`,
  `flush`, `Axis.label_size`/`tick_size`, `Legend.size`, `TextLabel.size`
  and `Scan.line_width` fall back on the figure's `doc.style`, then the
  user's `preferences.json`, then the built-in value (`core/style.py`).
  Never read them directly: `style.value(doc, obj, attr)`, or
  `PlotWidget.style_of`. A literal default written onto an object pins it
  and the user's defaults silently stop reaching it - which is why a
  version-1 session's sizes that equal the built-ins are read as None.
* **Tests must not touch the real preferences.** The window never loads
  them (`__main__` does); conftest's autouse `own_preferences` points
  `style.PATH_OVERRIDE` at a temporary file for every test. The pick
  distance is a HANDLING setting (`figure=False`): user-only, saved under
  `handling`, never in a session.
* **A modal dialog in a test used to hang the suite.** conftest's autouse
  `no_modal_loops` makes every `exec()`, `QMessageBox.about` and static
  file/colour/input dialog answer "cancelled" and fails the test at
  teardown naming it. It does not raise, because these run inside slots,
  where PySide6 turns an exception into an abort. A test that means to reach
  one stubs it (`window.ask_analysis = ...`).
* **The palette reaches existing widgets through the event loop**, and
  Fusion's `standardPalette()` follows the colour scheme in force when it is
  asked - taken while the dark scheme was set, the "light" palette came back
  dark. `appearance` sets the scheme first, then an explicit palette, and
  the window applies it before building any widget.
* **A QMenu fetched back through a temporary QAction wrapper** can already
  be deleted on the Python side. The window keeps `self.menus`.
* **A dialog field must not be named like a QWidget method.** `self.size`
  (a spin box) hid `QWidget.size()`, and `width`, `x`, `y` did the same; it
  only showed when something asked a dialog how big it was. A test now scans
  `dialogs.py` and `settings.py` for it - the `grab` trap, again.
* **The render cache must key on EVERY object's selection.** It keyed on
  scans and analyses only, so a selected label or arrow kept (or never got)
  its orange until something else rebuilt the plot: a click that changes
  selection only asks for a repaint.
* **An analysis being adjusted is changed IN PLACE** (`window.remeasure`):
  same object, new fields, and a default label rewritten with the new number
  (`measure.relabelled`). Replacing it left an open dialog editing an object
  no longer in the figure, and kept the old number in the label. Its gizmos
  live exactly as long as its settings dialog: letting go of one recomputes,
  closing the dialog (any way) confirms and ends them, a press elsewhere is
  an ordinary press, and Esc does not strip them. The dialog opens beside
  them (`window.place_beside`, `plot.gizmo_rect`).
* **A window shortcut fires from inside the window's pop-ups** (a Qt.Tool
  settings dialog passes its keys up), so `Ctrl+W` there closed the whole
  program. `close_step` closes the pop-up in front first (`window.popups`).
  A test of a window shortcut must `show()` the window, or it never fires.
* **A DSC curve is a PARAMETRIC curve, not a function of temperature**
  (Christian, round 11). A segment's temperature doubles back at its start
  and runs backwards when cooling, so anything that picks samples by a
  temperature window takes every branch at once. Truncation (`Scan.keep`,
  the template's `x_truncate`) is by FRACTION OF THE SAMPLES, and an
  interval dragged along a curve is stored as the two SAMPLE INDICES under
  the pointer (`Analysis.span`, `PlotWidget.sample_at`, nearest in the
  plane); `measure._series` slices by them. Only a file's analyses and typed
  temperatures still fall back to temperature windows.
* **A trace holds the KEPT samples only** (`trace.first` is where they start
  in the segment). Fit, picking, arranging, CSV and analyses read them; the
  hidden ends are painted dashed in the per-event overlay while the scan is
  hovered or selected, so no export can carry them.
* **`np.interp` needs x to increase.** A chord between the ends of a stretch
  of a COOLING scan came out wrong; use `_chord` in `ui/plot.py`.
* **A pop-up keeps its changes however it is closed** (round 11: "a change
  is a change"). `_LiveDialog.reject` - X, Esc, Ctrl+W - accepts; only the
  Revert button (`revert`) puts things back. Either way the window makes
  one undo step.
* **Unsaved changes are COMPARED, not counted**: `window.is_modified` diffs
  `session.to_state` (with the plot's live view) against the last save or
  open. Since round 17 the view IS in the file, so a zoom is a change;
  undoing back to the saved state is clean. `closeEvent` asks
  (`ask_to_save`, stubbable). The comparison must never WRITE: it runs on
  every title refresh, and copying the view onto the document there wiped
  an opened session's view before it was restored.
* **A move restores what was STORED, not what was drawn** (`_stored_of`).
  Restoring the drawn value turned "follow the house style" (None) into a
  fixed number whenever a drag was cancelled or undone.
* **An axis caption keeps `caption_gap` px from its NUMBERS** (house style,
  per axis `label_gap`), below them for x and left of the widest for y; the
  margins grow to fit. Session version 3 drops older `label_gap`s, which
  were measured from somewhere else.
* **The figure is drawn in its OWN space, 96 units per inch** (round 12,
  `core/figure.py`). 96 is Qt's logical DPI for fonts on screen and in a
  QImage, so a 12 pt font is 12/72 inch in the figure everywhere. At an
  exact size the page is scaled onto the pane (`PlotWidget.page`), so every
  mouse position goes through `to_figure` first, and the pick distance and
  drag slop are pane pixels divided by the scale. `plot_rect()` is a
  FRACTIONAL QRectF (an integer rect rounds an exact margin by 0.26 mm):
  never build a QRect from it, and `QPainter.drawLine` takes QPointF.
* **At an exact size the MARGINS decide the axes box**; numbers and captions
  live inside them and `overflow()` says what does not fit. Automatic
  margins (sized to the widest number) made "10.25" and "0.5" two boxes.
* **Exports are exact**: the PNG's DPI is written AFTER painting (fonts are
  converted with the device's DPI, which must be 96 while painting);
  QSvgGenerator defaults to 72 dpi (every font at 3/4 size until round 12)
  and its root width/height are rewritten in exact mm.
* **The driver export is RUN in a test** (`test_data_cases`, skips without
  achdsc, matplotlib or OJ-12). It used to call `start_plot()` and
  `finish_plot()`, which the template never had; now it emits a whole
  `driver()` with `plt.figure(figsize)` and `fig.add_axes` at the margins.
* **Interval marks** (round 10): a dash at each bound, centred ON the trace,
  in the axis colour; for an analysis whose result is a temperature
  (`Analysis.marks_a_point`: onset, endset, Tg) straight lines bound ->
  point -> bound, no dash at the point; an integration never gets a
  connecting curve. `PlotWidget.interval_marks` is the geometry.
* **Step names are length-prefixed and the length byte is printable**
  (fixed in ACH-DSC-Plotter's reader, round 9): names of 34+ bytes were
  invisible, and CN-119 read 3 segments of 7. TRI-FORMAT.md section 4.
* **Picking reads the LAST PAINT.** `_trace_at` uses the points drawn by the
  previous render, and `refresh()` (which `undo.clear()` calls) rebuilds the
  traces without them. A test that clicks after a refresh must `grab()`
  first, or the click lands on nothing and the test passes vacuously.
* **Qt may deliver a double-click's second press twice**: as a press AND
  then as the double-click, or as the double-click alone. The double-click
  handler drops any box the extra press started; the test helper
  `_double_drag` sends the extra press by default and one test sends none.
* **An analysis made in the panel exists nowhere else.** The session stores
  its model and cursors and recomputes it from the re-read file on load; a
  file's own analyses only have their styling stored, matched by `key()`.
* **A group dialog MIRRORS by diff** (round 14). `_LiveDialog._mirror`
  copies to the rest of the group only the fields whose value on the shown
  object changed since the last change, because every `_apply` writes ALL
  its fields from the widgets - copying everything would flatten each
  object's own values. A new per-object field goes in `INDIVIDUAL`, its
  widget in `GROUP_DISABLED`; the undo step reads `dialog.snapshots()`.
* **The first click of a double-click narrows the selection.** A drag or a
  settings dialog that should act on a shift-selected group must survive
  it: `mouseReleaseEvent` keeps `_click_restore`, and the double-click puts
  the selection back.
* **The heat-flow arrow is in POINTS** (x 96/72 into figure units), like
  `add_exo_arrow`'s arguments. Its tip angle is derived, never stored.
* **An analysis label never holds its number** (round 15). `label` is a
  template; `{}` is filled by `labels.render` on every draw, in the axes'
  units unless a unit follows it. Never write a measured number into a
  label, and read what a label SAYS through `render` (or
  `Analysis.summary(doc)`), never `analysis.label`.
* **`%.3g` is NOT Python's here** (`numbers.write`): significant figures,
  all written, no exponent. A format may hold no text - a unit in a format
  would print one unit's number with another's sign.
* **A point on a curve is a SAMPLE, found by walking** (`PlotWidget._walk`):
  the offset marker, like an analysis span. Temperature jitters sample to
  sample, so the walk tolerates a few units back before calling it a turn.
* **Enter must not close a live dialog** (`dialogs.enter_stays`): a spin
  box ignores Enter after taking its value, and QDialog then presses the
  first auto-default button - OK.
* **A plain-text tooltip is drawn on ONE line**, however long. Dialogs run
  `dialogs.readable` on show, which wraps every tooltip as rich text (and
  makes labels selectable); a tooltip set after showing is not wrapped.
* **An analysis's model and interval change through the WINDOW**
  (`change_model`, `retype_interval`, `remeasure`), each its own undo step,
  never through a dialog's snapshot: the snapshot would record the same
  change a second time.
* **S and R claim their keys through ShortcutOverride** (`PlotWidget.
  event`): M and C are window shortcuts (x range, measure), and a window
  shortcut fires before the focused widget sees the key.
* **A transform places anchors unclamped** (`set_artist_point(...,
  clamp=False)`): scaling a label about its corner moves its centre, and
  the 1 % edge clamp a drag uses moved the pivot instead.
* **A step-name analysis is attributed by being shown** (`Analysis.certain`
  includes "by step name" and visible). It is offered under every scan of
  its step; anything that shows analyses in bulk must skip those.
* **`doc`, `plot` and `undo` are PROPERTIES of the current tab**
  (`MainWindow._figure`, a `FigureTab`). Never connect a signal to a
  BOUND method of them (`self.undo.end_group`): that binds the tab that
  was current at connection time. Connect a lambda that looks it up.
  Pop-ups are closed before a tab switch, so their undo step lands on
  their own figure.
* **Never name a window method after an existing one**: `stack_selected`
  already meant "stack the scans evenly", and an `enabled` predicate
  calling the new one would have re-stacked the scans on every menu
  refresh. Grep first.
* **Drawing order is the stack order** (`PlotWidget._paint_items`, sorted
  by `model.z_of`); a new drawn kind adds itself there and to
  `model.KIND_Z`, or it is never drawn.
* **Windows reports every Alt+wheel as HORIZONTAL** (Qt's platform plugin:
  Alt is a mouse's sideways scroll). The page pan reads the real direction
  from `MainWindow.nativeEvent` (WM_MOUSEWHEEL vs WM_MOUSEHWHEEL). The
  hook runs for every message: it must never raise.
* **A menu mnemonic is a shortcut too**: "&Help" took Alt+H and "Show
  everything" never fired. `test_the_menu_bar_is_file_edit_search_help`
  checks the mnemonics against the operators' keys.
* **A structure is drawn from its STORED layout** (`MoleculeArtist.atoms`,
  `.bonds`); RDKit only makes a new one. Upright labels mean the POINTS
  are turned, not the painter (`_paint_molecule`).
* **Qt's double-click interval is the system's** (500 ms on Windows); the
  plot's click rhythm re-reads the timing (`_note_press`), and a Qt
  double-click slower than 350 ms is a layer step.
* **Qt's SVG writer ignores clipping** (checked, PySide6 6.11). Anything
  inside the axes' clip must stay inside `_paint_all`'s fenced block
  (`_clip_mark`), which `clip_svg` turns into a real `clipPath` after the
  export; a PNG clips anyway. Line segments that must never leave the axes
  are also cut geometrically (`_clip_segment`).
* **An axis has three hit targets** - `axis_spine_rect` (line and ticks),
  `axis_numbers_rect`, the caption box - and `axis_hit()` says which.
  Spine and numbers are never SELECTED (`_frame_part`); `edit_object(axis,
  part=...)` picks the window.
* **A scale's pivot is MEASURED, not predicted**: after changing the sizes
  the anchor goes back, the box is measured, and the anchor is moved by the
  pivot's error. A box does not grow in proportion to its font.
* **`markup_runs` returns `(text, italic, script)`**, script False, "sub" or
  "sup". Every text on the figure goes through it, added labels included.
* **A painter on an image starts from the APPLICATION font.** `_paint_all`
  sets `figure_font()` first, or exports lose the house font family.
* **The fitted y range includes the analysis labels** (`data_y`, round 22),
  and measuring a label asks for the axes box, whose margin asks for the
  widest y number, which asks for the fitted range: `_fitting` answers that
  inner call with the curves alone (the box's HEIGHT does not depend on
  it). `paint_into` memoises the range for one paint (`_fit_memo`); never
  keep it longer, or a change stops refitting.
* **Outliner rows remember being CLOSED, not being open.** "Open unless
  anything was open before" folded every new file away once the Decorators
  row (always there, always open) existed on an empty figure.
* **The middle button is a view gesture** (`_nav`, `nav_kind`); a middle
  double-click must never reach the left-button double-click code, which
  opens settings.
* **A label with a parent is drawn `follow()` above its stored place**
  (round 23): `artist_point` adds its scan's offset change since
  `parent_offset`, `set_artist_point` takes it off, `_artist_origin_px`
  adds it. Anything that places a label from pixels must go through them,
  and a unit change must convert `parent_offset` with the offsets
  (`Document.set_unit`), or every owned label jumps.
* **The outliner's drag is COPY, never Move**: after a MoveAction Qt
  deletes the dragged rows itself (`clearOrRemove`). A drop is a request
  to the window, deferred, and the rows are rebuilt.
* **`figure` is a loop variable in `ui/window.py`** (the tabs); the module
  is `figure_module` there.
* **Everything drawn is on a SCALED page** (round 24): anything counted in
  pixels - the curve's decimation columns, whether a line can go without
  antialiasing - counts DEVICE pixels of the page as shown (`page()[2]`
  times the device pixel ratio), never figure units. Figure text is laid
  out unhinted (`figure_font`) so it spaces evenly at any zoom.
* **A note's tip is `[degC, heat flow]`** (`TextLabel.leader`), with the
  parent's follow added like the text's. `placed_under` keeps it in place
  when a label changes hands; a unit change converts it for a note with a
  parent (a free one has no mass to convert by, like any data-space
  artist).
* **A segment can lack a signal** (a TGA-only segment has no heat flow).
  `missing_for` reports a missing SIGNAL exactly like a missing molar mass,
  so it reaches the placeholder, the blink and the export warning without a
  second mechanism. (The indium ramp that used to be the example turned out
  to be recorded, in flagged arrays - round 25.)
* **An array's length field is a LENGTH, never a signature** (round 25). A
  signal is `<n> 01102101 <size = 4 + 4m> <m> <m u32 flags> 0100 <n> <n f32>`;
  plain arrays have m = 0. The desktop's first SDT reader matched 8 fixed
  bytes whose last 4 were one run's byte count, so only 33601-sample arrays
  were read. Flags: 0 measured, 0x08000008 empty (NaN), 0x10 calculated by
  TRIOS (never a signal). TRI-FORMAT.md sections 3 and 3b.
* **Flagged samples are NaN** and some real runs have them at the START of
  segment 1 (GQ equilibrate runs, CN-INDIUM-CHECK), every DSC run at the end
  of its last segment. `_trim_empty_ends` trims the TAIL only, so sample
  indices (spans, markers) still count from the segment start; anything that
  reads data must be NaN-safe (`np.nanmin`, finite masks after slicing).
* **An SDT run's sample mass is DERIVED** from Weight / Weight Change (the
  file has no sample-size field), refused unless positive and constant, and
  said to be derived wherever it is shown (`head['mass_source']`). A negative
  recorded weight means NO mass, never an inverted curve.
* **The flat cursor goes by ACQUISITION order** (round 25): the earlier
  sample for an onset, the later for an endset, whatever the field names
  say. The panel's endset used to BE its onset. In a TRIOS record the
  onset/endset cursors are at +86/+132 and for an ENDSET the flat one is the
  second, called "Onset cursor x" in TRIOS's export.
* **A file analysis draws TRIOS's STORED construction** (`Analysis.
  stored_construction`, three points, four for a Tg), a panel analysis the
  Python one (`measure.tangent_points`), a `.txt` one chords. A construction
  is placed through `Scan.axes_points`, the same arithmetic as the curve,
  never a mapping of its own. `Analysis.fields["variable"]` says which curve
  an analysis was made on; one on the WEIGHT is never drawn on the heat flow.
* **A mass (m%) curve is a SCAN of its own** (`Scan.signal ==
  SIGNAL_MASS`, 2026-09-28), drawn against `doc.axes["y2"]` in
  `doc.weight_unit`. Anything placed at a scan's height maps through
  `PlotWidget.sy_to_px(scan, ...)` / `px_to_sy`, an artist in data units
  through `ay_to_px` (its parent scan's axis, else the MAIN one), a unit
  through `doc.unit_for(scan)` - never the heat flow's `y_to_px` or
  `doc.y_unit` alone. Gestures act on `main_axis()` ("y2" while a mass is
  shown). An outliner segment key is FOUR parts, `("segment", id, seg,
  signal)`. Arrangements (stack, distribute, align, S) work per signal.
* **A one-cursor analysis stores its temperature as BOTH cursors**
  ("Mass at temperature", `Measurement.needs == 1`): `cursors()`, `key()`
  and the session's recompute then work unchanged; its settings show "At".
* **A note's move carries its tip** (`_fields_of` is `("x", "y",
  "leader")` for a note) and a marker line's its temperature (`("vline",
  "x", "y")`), so an undo puts both back. A marker line's text stands ON
  its line: `artist_point` / `set_artist_point` read and write `vline`,
  never the label's own x.
* **A typed number during G on an artist is a distance in the axes'
  units** (x with X, else y on its axis), `PlotWidget._typed_px`.
* **An unframed axis's range is KEPT** (`PlotWidget.kept_fit`,
  2026-09-29), keyed by what the fit depends on besides placement
  (`_fit_signature`: the curves on the axis, truncation, units, exo, fit
  margins). F (`reset_view`, `fit`) and `rebuild(keep_view=False)` call
  `forget_fit`. Setting an offset without a refresh and then fitting fits
  the OLD traces - go through the undo stack or `refresh()` first.
* **Build a menu, then show it**: `context_menu_for(obj)` builds, and
  `_context_menu` execs. Patching `QMenu.exec` does NOT stop a real modal
  menu here (the test hung until killed); a submenu is kept on its
  parent's wrapper (`menu._paper`).
* **The figure's drawing theme is not always `doc.theme`**
  (`window.drawing_theme`): a page colour of the other family flips the
  ink. `refresh` sets it; the windows keep `doc.theme`.
* **The driver export is FROZEN** (Christian, 2026-09-28). New features go
  into the panel's own drawing and PNG/SVG exports, not `DSC_Plotter.py`.

## Running it

```bash
python -m pytest -q                  # about two minutes with the real files
python -m dscpanel <file.tri>        # from a source checkout
```

A quick look at the real thing, without a window on screen, is
`QT_QPA_PLATFORM=offscreen` plus `window.plot.grab().save(...)`. Text renders
as boxes under the offscreen platform on this machine; that is a font
question in the platform plugin, not a bug in the drawing.

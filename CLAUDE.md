# Working on Triplot (DSC-Panel until 1.0.0)

Notes for whoever (or whatever) picks this up next. **Start with
`docs/HANDOFF.md`**: the state of both repos, what is uncommitted, and what
the chat that built this settled. Then `docs/PLAN.md` for where the work is
going; this file is about how it is done here.

## Golden rules

1. **`core/` never imports a UI.** The model, the units, the arranging, the
   undo stack, the session and the exports are plain Python and numpy, so
   they are testable without a window. Qt lives in `ui/` and in
   `register.py`. Same rule as MoloM and ORCA Workbench.
2. **The name lives in `branding.py`.** A test fails if `Triplot` or
   `triplot` is written anywhere else outside prose. A rename is that
   module, the two entry points in `pyproject.toml`, and
   `register --clean-legacy`. Done once (1.1.0, 2026-09-30): DSC-Panel /
   `ach-dsc-panel` became Triplot / `triplot` on PyPI. The import name
   stays `dscpanel`, sessions stay `.dscpanel`, the old names are in
   `LEGACY_NAMES`, and the first start copies the old user folder across
   (`branding.adopt_legacy_dir`, called first in `__main__.main`).
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
| `core/session.py` | the `.dscpanel` file; finding a moved or missing file |
| `core/style.py` | the house style: object -> figure -> user default -> built-in |
| `core/figure.py` | the figure's size: window, aspect ratio, or exact size and margins |
| `core/presets.py` | style presets: a figure's look (and size) in a file |
| `core/labels.py` | what an analysis label says: templates, units, the rules |
| `core/chem.py` | a SMILES as atoms and bonds to draw (RDKit, optional) |
| `core/log.py` | the log file, the excepthook, the crash file |
| `core/numbers.py` | how a number is written: the `%.3g` formats; typed sums |
| `core/dtg.py` | the DTG: the m% curve's derivative, its units and window |
| `core/shades.py` | shades of one colour for a stack (the F3 gradient) |
| `core/molar.py` | molar masses from a formula, a SMILES or a composition |
| `core/export.py` | CSV, TRIOS Excel workbooks, the measured data as text, the driver bridge, and the export warnings |
| `core/profile.py` | what is particular to DSC/SDT data (one-press F, ...) |
| `core/ops.py` | the operator registry (copied from MoloM, keep in step) |
| `core/userops.py` | F3's memory, the user's: the operators used last, aliases of their own, the shared alias file, the factory reset (`operators.json` beside the preferences) |
| `ui/plot.py` | the painted plot: view, gestures, picking, drawing |
| `ui/window.py` | operators, menus, docks, drops, exports, undo |
| `ui/settings.py` | Edit > Settings (`Ctrl+,`): the two-column house style page |
| `ui/appearance.py` | the application palette, following the plot's theme |
| `ui/colour.py` | the colour picker (wheel, dropper) and the gradient dialog |
| `ui/numbox.py` | the number boxes that take a sum (`NumberBox`, `WholeBox`) |
| `ui/outliner.py`, `ui/palette.py`, `ui/dialogs.py` | the rest of the UI |

## Traps already paid for

* **A file a session cannot read is KEPT** (2026-10-08, family-wide;
  `model.MissingSource` in `doc.missing`): its entry, its curves' entries
  and the labels hanging from them, each with its place in the file.
  `session._keep_missing` puts them back into EVERY `to_state` (so a save
  and `is_modified` see them) and moves the colour links, span ends and a
  region's curves to match. A colour link, a span's ends and a label name
  things by their PLACE in the file, so `from_state` restores links through
  `_saved_target` (places in the file), never through the document's
  lists. Finding the file (`MainWindow.found_sources`) is
  `from_state(to_state(doc), found={saved path: new path})`: the figure
  opened again, the undo history cleared, changed until saved. The look
  beside a session stays by EXACT name; a name merely alike
  (`similar_files`: 0.85, a copy's "(1)" first, then the same numbers) is
  only OFFERED - "Run-1" is as alike to "Run-2" as to "Run-1(1)".

* **The source file changes through the WINDOW, after the settings
  window closes** (2026-10-05, family-wide; `SourceRow`,
  `_LiveDialog._source_chosen`): `change_source` replaces the sample's
  whole `__dict__`, so a window left open would show the old file's rows
  and its Revert would write old values onto the new file. It accepts
  (its own undo step lands first), the source changes (its own step),
  and the window opens again. `clean_path` takes the quotes of "Copy as
  path" off.

* **F3's memory is the USER's, in `operators.json`** (2026-10-05,
  family-wide; `core/userops.py`): the recent list and the aliases, beside
  `preferences.json`, written at every change. It is read again whenever
  the preferences path moves (`userops._ensure`), which is how every test
  gets an empty one from conftest's `own_preferences`. A shared alias file
  is known by its CONTENTS (`"format": "operator-aliases"`), never by its
  name: any other `.json` dropped goes on to the readers. Aliases are
  stored by operator ID - renaming an id orphans them (they are kept, and
  find nothing).

* **A settings window's rows are ORDERED, not built in order**
  (2026-10-05, family-wide): `_LiveDialog.FIRST_ROWS` / `LAST_ROWS` (or
  `row_order()`, which `LabelSettings` overrides per kind) name rows by
  label or "@attribute"; `_buttons` - every window's last call - moves
  them (`order_rows`). A new row joins its window's list, or it lands in
  the middle. The widgets are moved, not rebuilt: hiding a row means its
  field AND `labelForField`.

* **A step's flagged tail is kept aside, not dropped** (`_trim_empty_ends`
  keeps `step["tail"]`): the curves never see it, but TRIOS's Excel export
  writes every sample, the empty ones as empty cells, so
  `export.trios_step_columns` stacks it back. .NET writes a metadata
  string's length in 7-bit groups (`trios_io._meta_string`): a procedure
  of 128 bytes or more has a two-byte length and read as missing.
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
* **An error in a method Qt calls BY ITSELF never reaches the hook**
  (2026-09-30): `mouseMoveEvent`, `paintEvent`, `event`... - PySide6 6.11
  ends the process (an access violation, no line in the log). Every UI
  module ends with `log.guard_classes(globals(), __name__)`, which wraps
  each `...Event` and the methods in `log.HANDLERS` so the error is logged
  and survived - only while the hook is installed, so a test still sees
  it. A new UI module needs the line; `test_every_qt_handler_in_the_ui_is_
  guarded` says so. Found by dragging a label whose curve was hidden.
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
  pick distance (a setting, 8 px built in) of a curve, a press-and-drag
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
  part=...)` picks the window. The axis's LINES and inward ticks are the
  spine too (`frame_line_gap`), ranked behind anything within the pick
  distance. `Axis.visible` is the CAPTION's: never skip the spine or the
  numbers on it (round 28: a hidden y caption made the y axis unopenable).
* **A margin holds the numbers at the box's CORNERS** (round 28,
  `_numbers_overhang` in `page_needs`): a number is centred on its tick,
  so one on the corner hangs half over the margin beside. Where numbers
  are written is `numbered_ticks` / `_number_box`, shared with
  `_paint_grid`; a hidden number (`number_hidden`, kept with its unit
  like a lock) keeps its tick.
* **A mass line is drawn FIRST and fades behind what comes later**
  (`PlotWidget.mass_obstacles`): so where a label, an arrow or a
  decorator will be is worked out before it is painted -
  `analysis_label_geometry` is the one layout of an analysis label,
  used by the painting and by the line. Change a label's layout THERE.
  The line's value is an object of its own, `model.MassText` (its
  analysis's `mass_at` / `mass_dy`, `visible` = the line), listed in
  `Document.objects()` while its line is shown: a click selects IT, so
  G moves it (selecting the analysis made G move the label); a
  double-click or right-click is its analysis's.
* **An axis switching sides goes through `window._to_side`**: on an exact
  figure both margins keep their white space beyond what they hold.
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
  `doc.y_unit` alone. The swipe acts on `swiped_axes()` (the selected
  drawn curves' y axes, else the main one); the other gestures on
  `main_axis()` ("y2" while a mass is
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
* **A fit margin is a SHARE OF THE AXIS** (round 27): left 0.1 is the
  first tenth of the x axis empty. It was % of the data's range until
  preferences version 2 / session version 6, which `style.convert_old_fit`
  converts. Read both of an axis's through `PlotWidget.fit_pads`.
* **A white page draws every object colour as on the screen**
  (`paper_colour`, family-wide 2026-10-07): the default palette too.
  2026-10-02 still darkened `model.PALETTE` to `PAPER_LUMA` on white, and
  its orange came out brown in every export (a picked golden yellow had
  come out olive before that); Christian chose the screen colours as they
  are. `for_light` darkens the handling colours (`ACCENTS`) in
  `set_theme` and nothing else: never call it for an object's colour.
* **The handling colours are not the ink** (`plot.ACCENTS`): the reticle,
  band and selection follow the document's theme even when the page flips
  the ink to the other family. `set_theme(drawing, accent=doc.theme)`.
* **The y axis shows ONE quantity** (`Document.y_signal`): the heat flow,
  or the DTG while one is shown. Never assume "not a mass" means heat flow:
  `Scan.is_heat`, `is_mass`, `is_dtg`, and `doc.y_axis_unit()` for the y
  axis's unit. A heat flow beside a DTG is MISSING (`axis_missing`).
* **A decorator's page place is a fraction of the HOME frame** (round
  27b): `rel_to_px` / `px_to_rel`, never `rect.left() + x * width`. At
  home (the lock, else the fit: `PlotWidget.home`) that is the old
  arithmetic; zoomed, decorators move with the data. `_home_frames`
  must not be asked while a fit is being worked out (`_fitting`).
* **A hidden curve still holds its labels** (`PlotWidget._ghosts`,
  `_label_trace`, 2026-09-30): a trace is built for a hidden scan that a
  label hangs from, for the labels ONLY - never drawn, picked, fitted or
  exported. Without it the label fell back on its stored x and y (the
  middle of the plot). An attached label's move carries x and y as well
  (`_fields_of`, `_value_of`), for when there is no curve point at all.
* **A label on a curve is NOT placed by x and y** (`TextLabel.attached`:
  `at`, `dx`, `dy`). Its curve point comes from the drawn TRACE, so an
  offset set without a rebuild does not move it yet - go through the
  undo stack or `rebuild()`. `_fields_of` is `("at", "dx", "dy")`.
* **The OFFSETS order a stack; the outliner breaks ties** (2026-09-29):
  S and "Stack evenly" keep the order the offsets have
  (`PlotWidget.stack_order`), and only scans on the same offset go by the
  outliner (`Document.outliner_key`: `doc.samples` as listed, a file's
  curves in `model.SIGNAL_ROWS` order), its top on top. S keeps the
  LOWEST scan where it is unless T or M holds the top or the middle
  (`spread_anchor`; family-wide, 2026-10-01). The legend lists in the
  outliner's order.
  Change it only through `set_sample_order` (it re-sorts `doc.scans`,
  which labels in a session are matched by).
* **A spread's held place is where that curve IS when T, B or M is
  pressed** (`spread_anchor` re-reads `floor` and `ceiling` from the
  offsets): nothing moves on the key, only the line, and the step changes
  about the new place from then on. The first version re-applied the step
  from where the place was when S began, as Blender does for a pivot; the
  stack jumped on every key (Christian, 2026-10-01).
* **The spread's line runs through the held CURVE, never its offset**
  (`_spread_line`: the curve's median height). An offset is where the
  curve's zero is, and a transmittance hangs from 100 %: a line at the
  offset ran through the curves below and looked like "y = 0".
* **The plain swipe makes every curve taller IN ITS PLACE**
  (`scale_intensity`, family-wide 2026-10-01; it scaled the axis about
  y = 0 before, which spread the stack apart). Done without multiplying
  data: the axis is scaled about 0 and each offset follows so the curve's
  baseline keeps its place - `profile.baseline` says what a baseline is
  (a transmittance's is near its top, a heat flow's its median). Read the
  range BEFORE moving the offsets: a fitted range refits to the new stack
  first and every curve jumped. Hidden curves follow too. The offsets ride
  in the swipe's undo step (`_burst_offsets`, `commit_view`), never in
  `view_state`, which a session saves as numbers.
* **Ctrl+T asks nothing** (family-wide, 2026-10-02): on selected curves
  it makes one label each, saying the curve's name, hanging from the
  curve's end at `profile.name_label_corner` (`MainWindow.name_labels`,
  `NAME_CORNERS`, `PlotWidget.end_sample` - the end AS SHOWN, walked in a
  little); on nothing, one free label "Label". A curve whose name already
  hangs from it gets no second; the new labels are selected. The pick
  distance is 8 px built in since the same day (it was 14).
* **P during S keeps the stack's own gaps** (`spread_even`, the
  `profile` of depths below the top when S began): the old swipe's
  proportional spread, about the held place, the typed step their mean.
* **A change is drawn as a DRAFT first** (`PlotWidget.drafting`,
  `_DraftPainter`, `SETTLE_MS`): every curve a hairline, then the full
  drawing once nothing has changed for 150 ms, and while a hand is at work
  (a drag, a pan, a swipe settling, G, S or R). Measured on a 150 % screen
  for ten spectra: a full redraw ~190 ms, a draft ~18 ms. The WIDTH of a
  line is what costs (a 6000-point curve: 159 ms at 1.5 px antialiased,
  46 ms without antialiasing, 4 ms as an antialiased hairline), not the
  antialiasing as such. The cache keys on `drafting()`. Tests draw in full
  (conftest `full_drawings` sets `SETTLE_MS` to 0): they read pixels.
* **A pan is drawn, not slid**: the cached picture of the whole page used
  to be moved under the pointer (frame, numbers and captions with it).
* **Point lists come from numpy** (`_polyline_fast`: the polygon's memory
  filled through `shiboken6.VoidPtr`, as pyqtgraph does), checked once at
  import on three points; `_polyline_slow` if a PySide6 ever differs.
* **Moving several artists goes through `MainWindow._move_artists`**:
  every field an artist keeps its place in (`PlotWidget._fields_of`), and
  a refresh at once. Align wrote x and y only, so a label hanging from a
  curve did not move, and nothing showed until the selection changed.
* **A box selects artists and analysis labels too**, touched by what is
  drawn of them; a label caught with its curve is moved once (G leaves a
  child alone when its parent moves).
* **A colour can FOLLOW another object's** (`Obj.colour_from`,
  `model.sync_colours`, run first in every `refresh`): the follower's own
  `colour` is kept up to date, so everything that reads `.colour` works
  unchanged. Saved as `colour_links` (`[list, position]` pairs). A colour
  chosen by hand, the hex field, the F3 colour and a gradient end the link
  (the gradient puts it back on Revert and in its undo step). `colour_from`
  joins a settings window's snapshot whenever `colour` is in it.
* **A label hanging from its curve is placed by x and y**
  (`ArtistTransform._shown_values`, `_hang_at_typed`): the numbers are those
  of a FREE copy at the same spot, so no unit is converted here (Triplot's
  axis may be degC, K or degF); typed, it is hung again from there through
  `set_artist_point`. The old rows (`hang_at`, `hang_dy`, `hang_dx`) still
  exist but are never shown.
* **Given to a curve, a label wears its colour** (`parent_labels` sets
  `colour` "auto", which is "Same as parent" for an owned label).
* **Going EXACT takes the size from the screen**
  (`PlotWidget.exact_from_screen`, `MainWindow.go_exact`, the size
  window's `_mode_changed`): the page as drawn and its margins as they are,
  in the layout's unit - the stored size (8.5 x 6.5 cm) put every text, in
  points, out of all proportion to a figure laid out on a window. The
  blades show on EVERY figure; taking one on a non-exact figure makes it
  exact first (`exact_wanted`, said in orange) - the axes box stays put.
* **`_flash` holds four things** (text, start, seconds, warn): every reader
  takes `[:3]`. `_flash_tick` unpacking all four raised 40 ms after every
  "Saved" - found by the logging test, which only passes after a test that
  flashed (an older order dependence: alone, it fails at 1.1.0 too).
* **A session looks for a moved file BESIDE ITSELF** (`session._read_entry`:
  the path; else its folder and the folders under it, by name; else the
  copy inside, where `profile.EMBED_SOURCES`). A file read from elsewhere
  keeps the SAVED path until the opening is done - scans, labels and regions
  are matched by it - and takes its new path at the end (`relocated`); the
  next save heals the session. The copy is zlib + base64 of the bytes read
  (`Sample.source_bytes`, `_source_copy` caches the text).
* **A sample row is editable (F2) and may have a box**: `_item_changed`
  tells a rename from a tick by comparing the text with `sample.name`
  (`Sample.name` is the title, else the file name).
* **`undo.CallCommand` applies itself when built**: calling the action
  first as well runs it twice (closing a file lost its labels that way).
* **What a page margin HOLDS is `PlotWidget.page_needs`** (round 27e):
  the tightest a margin may go (blades, F3 "Tighten"), and what
  `overflow` checks. `needed_margins` is the AUTOMATIC layout's (with
  breathing room) and only sizes the non-exact figures.
* **A caption's box may hang over the page by its EMPTY rows**
  (`_ink_blank`, round 27f): its letters stop at the page's edge when a
  margin is tight. `page_needs` measures a caption's natural reach, never
  the clamped box, or a too-narrow margin looks wide enough.
* **Decorators follow the zoom only when `doc.follow_zoom`** (off by
  default since round 27f): `rel_to_px` is plain fractions of the axes box
  otherwise. Anything that flips it converts the places
  (`PlotWidget.reframed`), or they jump.
* **A structure's layout is atoms AND bonds' ring centres**: anything
  that moves atoms (`chem.mirrored_layout`) moves `bond["ring"]` too, or
  a ring's inner lines go outside it. Level labels on a turned structure
  are laid out AFTER the turn; `_molecule_layout` and `_paint_molecule`
  must decide the hydrogens' side the same way.
* **Room the program grows is remembered** (`FigureLayout.grown`, per
  side `[before, after]`, in the layout's unit) and given back by
  `_room_for_axes` when the axis leaves; a margin changed by hand drops
  its record. Wrap anything new that can hide a curve in it.
* **Every colour pick goes through `colour.get_colour`** (modal, live,
  Revert gives an invalid QColor); `QColorDialog` is no longer used.
* **The driver export is FROZEN** (Christian, 2026-09-28). New features go
  into the panel's own drawing and PNG/SVG exports, not `DSC_Plotter.py`.

## The family

This panel is one of a family of stacked-trace plotters (Triplot for DSC,
IR-Panel for infrared, PXRD-Panel for powder diffraction), each its own app on the same
handling. A change to that shared handling goes to EVERY member, and
Christian decides which changes are family-wide: when he says so, or when
a change is plainly about the handling and he confirms it. The standing
rule and the list of members are in his global notes; the log of
family-wide changes is kept there too.

`tests/test_family.py` is the SAME file in every member: a family-wide
change comes with its test there, copied to each. Each member's conftest
provides the one fixture it needs, `stack_window`.

## Running it

```bash
python -m pytest -q                  # about two minutes with the real files
python -m dscpanel <file.tri>        # from a source checkout
```

A quick look at the real thing, without a window on screen, is
`QT_QPA_PLATFORM=offscreen` plus `window.plot.grab().save(...)`. Text renders
as boxes under the offscreen platform unless it is told where the fonts
are: `QT_QPA_FONTDIR=C:/Windows/Fonts` gives it the real ones (and real
metrics - a box glyph is 16 units wide at 10 pt, so margins measured
offscreen without it are far too big). The test suite runs WITHOUT it, so
a test about sizes must hold for box glyphs too.

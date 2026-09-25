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
3. **Never write a parser fixture from memory.** The reader is vendored from
   ACH-DSC-Plotter and validated there against TRIOS exports. If a format
   question comes up, ask Christian for a real file - he has them and will
   provide one. `tests/conftest.py` builds a synthetic sample in the shape
   the reader RETURNS, which is a different thing and is allowed.
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
* **A segment can record no heat flow at all** (the ramp of an indium
  calibration run). `missing_for` reports a missing SIGNAL exactly like a
  missing molar mass, so it reaches the placeholder, the blink and the export
  warning without a second mechanism.

## Running it

```bash
python -m pytest -q                  # about two seconds
python tools/vendor.py --check       # is the vendored reader current?
python -m dscpanel <file.tri>        # from a source checkout
```

A quick look at the real thing, without a window on screen, is
`QT_QPA_PLATFORM=offscreen` plus `window.plot.grab().save(...)`. Text renders
as boxes under the offscreen platform on this machine; that is a font
question in the platform plugin, not a bug in the drawing.

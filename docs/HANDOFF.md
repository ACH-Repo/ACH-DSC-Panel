# Handoff: the chat that built DSC-Panel (2026-09-22 to 2026-09-25)

Everything a new session needs to pick this up cold. Read this, then
`docs/PLAN.md` (the decisions and the round-by-round log) and `CLAUDE.md` (the
rules and the traps). `docs/OPERATORS.md` is generated from the code and is
always current.

## 1. State right now

**Both repos have been committed once, nothing pushed.** Work after
`f261ce5` (panel) is in the working tree only.

| Repo | State |
| :-- | :-- |
| `ACH-DSC-Panel` | Initial commit `f261ce5` on `master` (2026-09-25, at Christian's request; not pushed - his other repos use `main`). Rounds 10 and 11 after it are uncommitted. 172 tests pass. |
| `ACH-DSC-Plotter` | Committed `d743702` on `main` (2026-09-25; not pushed): the Tg decode, the `.txt` mass fix and round 9's step-name length byte (`_step_name`), with TRI-FORMAT.md and the re-vendored template. 33 tests, including the three CN-119 export comparisons (its folder is in the gitignored `tests/local_testdata.txt`). |
| `ACH-MoloM` | Untouched by this chat. Its tree already had 10 modified files from earlier work. |

Christian commits and pushes himself, per message, never as a standing
order. An initial commit of the panel has been offered and not yet asked for.
Until it exists, the only recovery for a destroyed file is Claude's own
file history - see section 6.

**Installed on this machine:** `pip install --user -e` (no deps, build
isolation on, because the system setuptools 57.4 lacks PEP 660). Commands
`dsc-panel` and `dsc-panel-gui` are in
`C:\Users\chris\AppData\Roaming\Python\Python310\Scripts`. The Start Menu entry
was registered with `dsc-panel register`; `dsc-panel register --remove` undoes
it. Code edits take effect on the next launch.

## 2. What the program is

`ACH-DSC-Panel` (app **DSC-Panel**, command **`dsc-panel`**, package
`dscpanel`): a standalone PySide6 program for arranging STACKED DSC scans from
TA Instruments TRIOS `.tri` files (and their `.txt` exports). It has the
handling of MoloM's PXRD window, rebuilt for calorimetry. It ARRANGES; the
existing matplotlib program ACH-DSC-Plotter PUBLISHES, and the panel exports a
runnable `DSC_Plotter.py` driver as the bridge. Do not grow a second figure
engine here.

The idea behind it is bigger: a family of stacked-trace plotters on the same
handling, one per data type. DSC is first because Christian needs it. A
standalone PXRD plotter is the sibling he explicitly put off. The global
backlog (`C:\Users\chris\.claude\CLAUDE.md` and
`C:\Users\chris\.claude\backlog\dsc-interactive-plotter.md`) carries that.

## 3. Decisions Christian made (do not reopen)

- **Y data is never normalised per scan.** A DSC baseline depends on mass,
  pan and heating rate. Defensible for IR/PXRD, not for DSC.
- **Units:** W/g default; mW; W/mol (POWER per mole). Integrals report J/g or
  kJ/mol. **Molar mass is never assumed**: a scan without M on a per-mole axis
  is a dashed placeholder with a double-blinking red label, and every export
  prints and stamps `NO MOLAR MASS`.
- **No per-line y scale.** Removed from the scan settings and the model:
  offsets plus axis limits do the same honestly. (Scaling the y AXIS is a view
  gesture and stays.)
- **Scans never move along x.** His words: "shifting along x is nonsense."
  Artists (arrow, captions, legend) DO move in x and y.
- **Stacking is continuous**, offsets are physical numbers, shown with an
  offset arrow.
- **Exo down is the default**, and proved (section 5).
- **A file opens with its FIRST HEATING SCAN only**, every other segment one
  tick away in the outliner. Comparing second/third up-scans across samples is
  the core job.
- **Analyses are objects, OFF by default**, individually switchable.
- **The outliner lives on the right.** (He asked whether that is weird; it is
  not - see section 8.)
- **The name is provisional.** It lives only in `src/dscpanel/branding.py`; a
  test fails if it is hard-coded elsewhere. `register --clean-legacy` plus
  `LEGACY_NAMES` is the deregistration plan; `dsc-panel alias <name>` gives a
  personal name on any platform.
- **The reader is VENDORED** from ACH-DSC-Plotter (`tools/vendor.py`,
  `--check` is the drift alarm). Fix the reader THERE, then re-vendor.

## 4. Standing instruction: the interactions are provisional

Christian, 2026-09-24: "I cannot give you proper instructions without giving
you shit ones first" and "the interactions are very much subject to
fundamentally change". Do not defend a gesture because it exists. Keep input
handling cheap to move. Expect the measuring flow, click semantics and dialogs
to be rearranged again.

## 5. Facts established from his data (with the evidence)

- **Exo down, proved by physics.** `Downloads\Indium-03082026(1).tri`: on its
  isothermal segment `Heat Flow = -254.8 x Delta T` (correlation -1.000); the
  melt is a -69 uV excursion in Delta T, i.e. UP in heat flow. Endothermic up
  = exo down. The indium `.txt` export confirms it independently: the melt
  points up and integrates to 28.56 J/g (indium: 28.5).
- **Exo direction is read per file**: the `.txt` header says `Exotherm
  Direction Down`; a `.tri` carries a TRIOS audit line "Exotherm changed to
  'Exo Down'" (SES-4, indium). Where neither exists it is reported "assumed".
- **The glass-transition record is decoded** (OJ-12): four (x, y) pairs at
  +0/+16/+32/+48 = onset cursor, onset, end, end cursor. Midpoint = the
  half-height crossing between the middle two (reproduces TRIOS's 78,911 degC
  exactly; the mean, 78.849, is wrong-but-plausible). Implemented in
  ACH-DSC-Plotter `_tg_fields`, documented in its `TRI-FORMAT.md` section 5.
- **A calibration run's ramp segment records no Temperature and no Heat
  Flow**, and has no alias signals to fill them from. Reconstructing from the
  raw sensors was measured against the export: 7% out in heat flow, 0.29 K in
  temperature - worse than the +-2% / +-0.1 degC the calibration is judged by.
  So it is NOT reconstructed; the panel names the `.txt` export beside the
  file instead.
- **A `.txt` export is first-class**: it stores W/g and no watts, and hides
  the sample mass in `[Procedure]`. The reader now folds the mass into `head`
  and the panel tracks each file's base unit.
- **The reader's `segment` field is 1-based.** Reading it as an index drew
  every analysis one scan too low. Caught by integrating the peak.
- **Temperature is not monotonic** inside a segment (1-17 reversals; cooling
  runs backwards). No `searchsorted` anywhere in drawing.

Real files on this machine (listed in the gitignored
`tests/local_testdata.txt`): OJ-12 `.tri` + Full `.txt` (TRIOS 5.1.1);
SES-2 `.tri` + `.txt` (TRIOS 6.0); SES-4 `.tri`; indium `.tri` + `.txt`.
Still wanted from Christian: a **target figure** (thesis or paper) for the
look, and one MDSC or multi-procedure file only if his group ever runs them.
Isothermal segments exist in runs but he has never used them deliberately.

## 6. Traps paid for (so they are not paid twice)

Full list in `CLAUDE.md`. The ones that cost the most:

- **A patch script opened `plot.py` for writing and then crashed**, truncating
  it to zero bytes. Recovered from
  `C:\Users\chris\.claude\file-history\<session>\<hash>@vN` (Edit-tool
  snapshots only; script edits are not snapshotted) and re-applied. Lesson:
  copy a file to `$TEMP` before any scripted rewrite, and never pass anything
  but `"\n"` as `newline`.
- **An exception inside a Qt slot is an abort, not a traceback** (PySide6).
  A three-part outliner key unpacked into two variables killed the program.
- **Never rebuild a tree from inside its own signal**; outliner signals are
  deferred with `QTimer.singleShot(0, ...)`.
- **A window-level shortcut fires before the focused widget.** Return bound to
  "settings" stole Enter from the measurement. No operator may claim Return or
  Enter; a test enforces it.
- **A modal `exec()` in a test hangs.** Tests that trigger `activated` or
  `measure_ready` disconnect the window's handler first. Settings dialogs are
  now NON-modal anyway (they block the gizmos otherwise).
- **`trios_analysis.peak_integration` takes time in MINUTES** (it converts to
  seconds itself). Seconds gave enthalpies 60x too big.
- **`str.format` eats `_{g}`** subscript braces; default labels use `%`.
- **A bash heredoc containing Python triple quotes and backslashes breaks.**
  Write longer patches to a `.py` file in the scratchpad and run that.
- **`QWidget.grab` exists**; the transform method is `start_grab`.

## 7. What the program does now (0.1.0, 172 tests)

Reading and data: vendored reader; `.tri` and `.txt`; per-file exo detection;
background loading; sessions (`.dscpanel`); CSV and PNG/SVG export (light
palette, warnings stamped); `DSC_Plotter.py` driver export.

Objects: `Scan`, `Sample`, `Analysis`, `Axis`, and the **`Artist` base class**
(position in `relative` or `data` space, 9-point anchor, colour, and class
flags `can_rotate` / `can_scale`) with `HeatFlowArrow`, `TextLabel` (free or
owned by a scan) and `Legend`. `is_artist` is `isinstance(obj, Artist)`.

Handling (all provisional, see section 4). Round 9's rule: **a drag acts on
what it starts near** (PLAN.md, rounds 8 and 9):
- a press within the pick distance (Settings > Handling, 14 px built in) of
  a CURVE and dragged marks an interval; letting go opens the analysis list
  under the pointer and the analysis is done when it closes (one undo step;
  `Esc` drops it). Near an ARTIST, analysis label or axis caption, a drag
  moves it. Anywhere else, or with `Shift`, a drag is a box select. An
  unmoved press is a click; a double-click opens settings; a
  double-click-drag does what a drag does. Picking is "nearest within N";
- the plain pointer is a RETICLE and the system cursor is hidden inside the
  axes; `Esc` returns to select;
- a scan moves with `G` or a typed number ONLY; `G` with X/Y locks (X only
  for artists); `R` resets offsets; `Ctrl+A` select all;
- two-finger swipe scales y; `Shift`+swipe pans omnidirectionally; `Ctrl`
  (pinch) zooms both; nothing is drawn outside the axes. Zoom, pan and fit
  are UNDO STEPS, one per gesture;
- window: follows the plot's theme (dark Fusion palette by default); menu
  bar File / Edit / Search (button, = F3) / Help (About); saving and
  exporting flash a fading confirmation over the plot;
- measuring by typing: `C` on one selected scan, type a temperature per
  crosshair (axis unit), drag a cursor to adjust, `Enter` opens the list,
  `Esc` steps back one stage; F3 has "Analyse the interval". Double-clicking
  (not dragging) an analysis made here shows its cursors AND its settings and
  keeps its model. Analyses made here are SAVED in the session (model +
  cursors, recomputed on load);
- truncation by POINTS (`Scan.keep`, the template's `x_truncate`): hidden
  ends dashed on hover, out of fit/picking/analyses/exports. Intervals
  dragged along a curve are sample spans (`Analysis.span`);
- closing: pop-ups keep their changes (Revert is the way back); the window
  asks to save when the figure differs from the file;
- house style (`Ctrl+,`, `core/style.py`): sizes and label `flush` resolve
  object -> figure (`doc.style`, in the session) -> the user's default
  (`preferences.json` in `branding.app_dir()`) -> built-in. Styled
  attributes are None until chosen; read them through `style.value`;
- analyses: leader-arrow labels dragged vertically only, auto side away from
  the peak, shaded integrals, interval marks (dashes at the bounds, and for
  onset/endset/Tg lines to the point, in the axis colour; hideable), default
  labels like `\Delta*H* = 13.247 J/g`, `Ctrl+L`/`R`/`M` alignment,
  `Delete` removes them. Double-click one made here: gizmos plus its
  settings beside them; the gizmos end with the dialog;
- figure: template style (no grid, ticks in, minor ticks, italic `*T*`),
  margins sized by font, spine vs caption double-click, Celsius/K/F x axis,
  two themes (`blender-default`, `light`; exports always light), legend
  (the outliner's tick), captions (`Ctrl+T`, or right-click a curve), undo
  over everything including removals. `Z` cycles box, horizontal, vertical.

## 8. Offered or parked, not done

- **Persist window geometry and dock state** (`QSettings`, ~6 lines).
  Offered after the outliner discussion: the outliner is a QDockWidget and can
  already be moved, but its place is not remembered. Why the right side feels
  correct to him: his daily tools (Blender, Photoshop-family, MoloM) all put
  the object list right, and on a PLOT the left edge belongs to the y axis.
- **An initial commit** of ACH-DSC-Panel, and committing the ACH-DSC-Plotter
  reader changes. His call, per message.
- **Heat-flow arrow style parameters** (shaft width, head width, head length
  separately; explicitly parked). A non-uniform `can_scale` artist.
- **Picking an object buried in an overlapping stack** - open, see PLAN.md
  open questions. Click-cycling was dropped (it collides with double-click).
- **Analysis labels may need horizontal freedom** when they clash.
- **Close a file entirely** (`Document.close_sample` exists, no operator).
- **Blank-run (empty pan) subtraction**; **SDT/TGA** mode; more artists
  (scale bar, molecule image).
- **The Tg construction drawn in the plotter template** - the values are
  decoded, the drawing there is not done.

## 9. Conventions (cross-repo, all still in force)

Python exactly 3.10.0. No em-dashes, ASCII source (a test checks the panel).
Never commit or push unless asked in that message. No `C:\Users\chris` paths,
lab PC ids or student names in repo files (`tests/local_testdata.txt` is
gitignored for that reason). Ask for a real data file before writing parser
code or fixtures. MIT licence with the TU Dortmund line; author
`@p3rAsperaAdAstra`; repos under `github.com/ACH-Repo`.

```bash
python -m pytest tests/ -q -p no:cacheprovider
python tools/vendor.py --check
python tools/gen_operators.py > docs/OPERATORS.md
```

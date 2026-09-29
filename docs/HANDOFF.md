# Handoff: the chat that built DSC-Panel (2026-09-22 to 2026-09-28)

Everything a new session needs to pick this up cold. Read this, then
`docs/PLAN.md` (the decisions and the round-by-round log) and `CLAUDE.md` (the
rules and the traps). `docs/OPERATORS.md` is generated from the code and is
always current. `docs/TRI-FORMAT.md` is the binary format.

## 0. LATEST: round 25, 2026-09-28 (laptop) - UNCOMMITTED, possibly unfinished

The repo is on GitHub (`ACH-Repo/ACH-DSC-Panel`, private, branch `main`).
Christian works from a laptop and a desktop PC. `4bc9426 "intermediary"` was
pushed from the desktop mid-round-25 (an interrupted session there); this
laptop pulled it and continued. Christian committed and pushed the laptop's
state as `dbcf753 "intermediary2"` (13:55) when the usage limit hit: stages
1-2 below complete, stage 3 PARTIAL (its agent died at 13:45 mid-edit;
`tests/test_weight.py::test_weight_analyses_are_listed_honestly_and_never_drawn`
fails on a test bug, `ItemFlag & int`; 445 others pass). New requests for
after round 25 are in `docs/NEXT.md`.

**Decisions Christian made on 2026-09-28 (do not reopen):**
- **ACH-DSC-Plotter is RETIRED.** The reader (`core/trios_io.py`,
  `core/trios_analysis.py`) is the panel's OWN: fix it here. `tools/vendor.py`
  and the cross-repo drift test are deleted ("why would we make a test
  dependent on a different repo?"); `docs/TRI-FORMAT.md` and
  `tests/test_reader.py` came over from the Plotter. Its `TEST.txt` was left
  behind (it carries a name and an instrument IP).
- **The `DSC_Plotter.py` driver export is FROZEN** as it is: no tangents, no
  new weight features in it.
- Tangent constructions and SDT support were the two most important items.

**Done (stages 1 and 2 of the workflow, suite green at 405 passed after
stage 2):**
1. **Reader** - the round-25 SDT code matched flagged arrays by 8 fixed bytes,
   4 of which are a BYTE COUNT (fits only 33601-sample arrays), so CN-81
   (39001) and most SDT runs misread (Weight in kg drawn as heat flow). Now
   one array layout, length fields checked, flags read (TRI-FORMAT.md 3/3b).
   Side effect: the DSC "partial final segment" and the indium ramp's
   "missing" heat flow were flagged arrays all along - now read (the indium
   melt integrates to 28.56 J/g from the `.tri` alone). Sample mass of an SDT
   run is derived from Weight / Weight Change, refused when not positive and
   consistent (three DESY runs have a negative recorded weight: no mass), and
   marked "derived from the weight". A `.txt` SDT export's % column "Weight"
   becomes "Weight Change". Onset/endset cursors read at +86/+132 (the endset
   was misread), TRIOS's construction points kept (`construction`), and the
   analysed variable decoded (`variable`: heat flow or weight). Validated on
   all 468 `.tri` here and 231 `.tri`/`.txt` pairs.
2. **Tangents** - onset, endset and Tg drawn as tangents by default (TRIOS's
   own stored points for a `.tri` analysis, Python's for a panel one, chords
   for a `.txt` one with a note); per analysis "Lines": tangents / chords /
   none; house style `analysis_construction` and `tangent_overshoot` (6 pt).
   The panel's own ENDSET was the onset (fixed: OJ-12 94.83 -> 108.06, TRIOS
   108.02) and a cooling onset took its baseline on the wrong side (fixed:
   the flat cursor goes by acquisition order). `tests/test_tangents.py`.

**Stage 3 (the SDT UI findings) finished** (452 tests); its review was
stopped by Christian (he does not want agent fleets - see the memory
`no-agent-swarms`). Then, done directly and uncommitted on top of
`intermediary2`: the S crash fixed, the outliner shows file names, redraws
3x faster, and **TGA redesigned** (PLAN.md Next 1): the m% curve is a scan of
its own and an SDT file opens with it alone; all five TGA steps done (mass-
at-temperature markers, m% onsets, marker lines), and every request in
`docs/NEXT.md` (PLAN round 26); 477 tests. Uncommitted.

**If you pick this up in a new session:**
1. `git status` / `git diff --stat` shows what landed. Run the suite. If it
   is red, the workflow was cut off mid-edit: find the half-done change in
   the diff before anything else.
2. Every report is kept OUTSIDE the repo (they contain local paths):
   `C:\Users\<you>\.claude\backlog\dsc-panel-round25\` - the investigations
   (`report_sdt_reader.md`, `report_sdt_ui_review.json` with F1-F14 and the
   gaps, `report_tangents.md`, `report_plotter_sync.md`) and the stage
   reports (`stage1_reader_report.md`, `stage2_tangents_report.md`, and
   later ones if they were written). The workflow journal with every
   agent's full report is under that session's folder in
   `.claude\projects\...\f13728c1-...\subagents\workflows\wf_799aa108-cf3\`.
   **`stage3_progress.md` in that folder is the live log of stage 3**: the
   restarted agent writes its assessment of each finding first and a
   `DONE` / `FIXED` line after each one. Journals: `wf_799aa108-cf3`
   (stages 1-3, cut off) and `wf_9e46eedd-5b6` (stage 3 restarted, with
   its review and fixes).
3. Whatever of stage 3 is missing: redo it from `report_sdt_ui_review.json`
   (F2, F4, F5, F7-F14; F1/F3/F14 are done in the reader; F6 and the driver
   halves of F7/F12 are NOT to be done - the driver is frozen), guided by
   `stage3_progress.md`. Then review (three lenses, each verified).
4. The doc pass is done for what is known (CLAUDE.md rule 3 and traps,
   README, PLAN round 25). Add stage 3's outcome to PLAN round 25 and clear
   this section's "in progress" once it is finished.
5. Then `docs/NEXT.md` (Christian's next requests, verbatim).
6. Commit only when Christian asks.

**Open for Christian (from the stage reports):** tune the Python onset fit
towards TRIOS (panel analyses are 1.06 K median, up to 8.1 K off TRIOS on the
same cursors); should an analysis label's arrow point at the tangents'
crossing rather than the curve; a cooling panel Tg now runs in acquisition
order (step height sign flips); the Weight Corrected Heat Flow fallback
(normalises by the weight LEFT, labelled W/g) - keep it?; CSV blanks empty or
`nan`; F does not make room for tangents past the data; no cooling
onset/endset/Tg record exists here to confirm TRIOS's point order there.

**The ACH-DSC-Plotter repo** (retired, left untouched): the laptop has
`d743702` unpushed; the desktop has uncommitted SDT reader edits and a
`TRI-FORMAT-SDT.md` (KC-122/KC-127 findings) that exists nowhere else -
worth copying into this repo's docs next time at the desktop. Pushing or
archiving it is Christian's call.

## 1. State right now (as of 2026-09-25; see section 0 for what is newer)

**Both repos have been committed once, nothing pushed.** Work after
`f261ce5` (panel) is in the working tree only.

| Repo | State |
| :-- | :-- |
| `ACH-DSC-Panel` | Initial commit `f261ce5` on `master` (2026-09-25, at Christian's request; not pushed - his other repos use `main`). Rounds 10-11 committed as `35b6db4` (not pushed); rounds 12-18 committed as `4ab47d0`, round 19 as `f411f26`, rounds 20-21 after them (2026-09-27, not pushed). 285 tests pass. |
| `ACH-DSC-Plotter` | Committed `d743702` on `main` (2026-09-25; not pushed): the Tg decode, the `.txt` mass fix and round 9's step-name length byte (`_step_name`), with TRI-FORMAT.md and the re-vendored template. 33 tests, including the three CN-119 export comparisons (its folder is in the gitignored `tests/local_testdata.txt`). |
| `ACH-MoloM` | Untouched by this chat. Its tree already had 10 modified files from earlier work. |

**Rounds 22-24 (2026-09-27/28, on the desktop PC, committed and pushed at
Christian's request):** middle-button drag, F fitting the analysis labels,
the outliner's Decorators; style presets, label parenting, the size pop-up,
structure label defaults; sharpness on a scaled page, S spreading scans,
the Boombox theme, notes, stereo wedges - PLAN.md rounds 22 to 24. PLAN's
"Next" is empty but for optional items. The desktop has Python 3.13 and no
3.10. Its
ACH-DSC-Plotter checkout equals GitHub (`a0c9972`). (Superseded on
2026-09-28: the Plotter is retired and nothing is vendored any more - see
section 0.) The working tree here is CRLF (`core.autocrlf`
true): a script that rewrites a file writes `"\r\n"` to match.

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
- **The reader is the panel's own** (2026-09-28, section 0). Until then it
  was vendored from ACH-DSC-Plotter; that arrangement and `tools/vendor.py`
  are gone.

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

- **A patch script's write can FAIL mid-file on this machine** (round 16:
  `OSError: [Errno 22]` writing `dialogs.py`, another process holding it).
  Scripts write to `<file>.tmp` and `os.replace` it over the original, and
  keep a copy of the original under a name the script does not overwrite.
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

## 7. What the program does now (0.1.0, 285 tests)

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
- two-finger swipe scales y ABOUT y = 0 (zero never moves); `Shift`+swipe
  pans omnidirectionally; `Ctrl` (pinch) zooms both about the cursor; `M`
  types the x range (two boxes, Tab, Enter); nothing is drawn outside the axes. Zoom, pan and fit
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
- figure size (`core/figure.py`, Edit > Figure size and margins): window,
  aspect ratio, or exact cm/in with margins that fix the axes box; drawn in
  96 units per inch and scaled onto the pane; PNG/SVG exports exact; the
  driver export builds the same figure in matplotlib (and now runs at all).
  Axes on either side, numbers and caption hideable;
- truncation by POINTS (`Scan.keep`, the template's `x_truncate`): hidden
  ends dashed on hover, out of fit/picking/analyses/exports. Intervals
  dragged along a curve are sample spans (`Analysis.span`);
- closing: pop-ups keep their changes (Revert is the way back); the window
  asks to save when the figure differs from the file;
- house style (`Ctrl+,`, `core/style.py`): sizes and label `flush` resolve
  object -> figure (`doc.style`, in the session) -> the user's default
  (`preferences.json` in `branding.app_dir()`) -> built-in. Styled
  attributes are None until chosen; read them through `style.value`;
- analysis labels are TEMPLATES (`core/labels.py`): `{}` is the measured
  value, a unit after it converts; number formats are house style
  (`core/numbers.py`); font family in Settings;
- analyses: leader-arrow labels dragged vertically only, auto side away from
  the peak, shaded integrals, interval marks (dashes at the bounds, and for
  onset/endset/Tg lines to the point, in the axis colour; hideable), default
  labels like `\Delta*H* = 13.247 J/g`, `Ctrl+L`/`R`/`M` alignment,
  `Delete` removes them. Double-click one made here: gizmos plus its
  settings beside them; the gizmos end with the dialog;
- figure: template style (no grid, ticks in, minor ticks, italic `*T*`),
  margins sized by font, spine vs caption double-click, Celsius/K/F x axis,
  two themes (`blender-default`, `light`; exports always light), legend
  (the outliner's tick), y-offset markers (the template's
  `add_yoffset_markers`, F3; one movable object per scan), captions (`Ctrl+T`, or right-click a curve), undo
  over everything including removals. `Z` cycles box, horizontal, vertical.

## 8. Offered or parked, not done

- **Persist window geometry and dock state** (`QSettings`, ~6 lines).
  Offered after the outliner discussion: the outliner is a QDockWidget and can
  already be moved, but its place is not remembered. Why the right side feels
  correct to him: his daily tools (Blender, Photoshop-family, MoloM) all put
  the object list right, and on a PLOT the left edge belongs to the y axis.
- **An initial commit** of ACH-DSC-Panel, and committing the ACH-DSC-Plotter
  reader changes. His call, per message.
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

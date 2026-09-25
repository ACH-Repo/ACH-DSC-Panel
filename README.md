# DSC-Panel

An interactive panel for stacked DSC scans from TA Instruments **TRIOS**
files. Drop `.tri` files on it, stack the scans into the arrangement you want,
mark an interval on a curve to analyse it, and hand the result to a figure: a
PNG or SVG, a CSV, or a `DSC_Plotter.py` script that redraws it in matplotlib.

It is the ergonomics of the PXRD window in ACH-MoloM, rebuilt for calorimetry.
The reader is ACH-DSC-Plotter's, vendored in (`tools/vendor.py`), so the
binary format is decoded by the code that was validated against TRIOS exports
value by value.

```bash
pip install -e C:\Users\<you>\Documents\Github\ACH-DSC-Panel
dsc-panel                    # or find "DSC-Panel" in the Start Menu
dsc-panel my-sample.tri      # straight into a file
```

## What it does differently from a plotting script

- **Every segment is an object.** A `.tri` holds a heating ramp, a cooling
  ramp and usually five more; each one is a scan you can select, move, hide,
  colour and right-click. A file opens with its first heating scan on the
  plot and every other segment listed in the outliner, one tick away - so
  comparing the second and third up-scans of four samples is four ticks.
- **Two themes.** `blender-default` is the dark screen one, `light` is the
  same figure on white. Exports are always light, whichever is on screen.
- **Analyses are objects, and they start off.** A run carries a dozen stored
  analyses; each is a row in the outliner with its own box, its own colour
  and its own settings. Where the file could not say for certain which scan
  an analysis belongs to (a `.txt` export names only the step), it is drawn
  with a dashed tick and a question mark, and it can be moved to the right
  scan by hand.
- **The stack is continuous.** Scans go wherever you put them (`G`, or just
  type a number), and the offset each one carries is drawn beside it as a
  number with an arrow. No mouse gesture moves a scan by accident.
- **Nothing is normalised.** The y axis is mW, W/g or W/mol, with real
  numbers on it. A DSC baseline depends on the mass, the pan and the heating
  rate, and scaling each trace to its own extremum would hide exactly the
  differences a stack is for.
- **Per mole is opt-in.** W/mol needs a molar mass, there is no default, and
  a scan that has not been given one is drawn as a dashed placeholder with a
  blinking red label instead of being plotted wrong. An export of a figure
  with one in it carries a `NO MOLAR MASS` notice on the image and on the
  console.
- **A legend when you want one** (`Ctrl+L`): a colour sample and a name per
  drawn scan, taking each scan's own label. It is an artist, so it is dragged
  and anchored like the rest, and it starts off.
- **Labels can belong to a line.** Right-click a curve and add one: it
  takes that line's colour, is listed under it in the outliner, and is
  removed with it. Free-standing captions (`Ctrl+T`) work the same way
  otherwise.
- **Artists carry a transform.** Everything that augments the figure rather
  than coming from the data - the heat-flow arrow, a caption, whatever comes
  next - derives from one base class with a position, an anchor and per-kind
  capability flags. A position can be given as a fraction of the plot or in
  the axes' own units, and switching between them does not move anything.
- **The heat-flow arrow is an object too.** Label it "exo down", "exo up",
  "endo up" or "endo down"; the curves and the y axis follow the label, so
  the arrow and the data cannot contradict each other.
- **The exotherm direction is read from the file** where the file says it (a
  `.txt` export states it in the header; a `.tri` carries TRIOS's audit line),
  and reported as assumed where it does not.

## Keys

The navigation is MoloM's PXRD window and ORCA Workbench's, key for key.

| Key | What it does |
| :-- | :-- |
| click | select what is under the pointer (`Shift` adds) |
| drag from a curve | **mark an interval**; let go and pick the analysis |
| drag from an artist | move it: the arrow, the legend, a label, an analysis label, an axis caption |
| drag from empty space | **box select** (with `Shift`, a box from anywhere, adding) |
| double-click | settings: a curve, an analysis, an axis spine, a caption |
| two-finger swipe | scale the y axis about the cursor |
| `Shift` + swipe | pan the view, in whichever direction the fingers go |
| pinch | zoom both axes about the cursor (Windows sends this as `Ctrl+wheel`) |
| `Z` | cycle zoom: horizontal, vertical, box (`Esc` leaves) |
| `P` | cycle pan: horizontal, vertical, free |
| `F` / `Home` | fit the view (x first, then y) |
| `Esc` | back to plain select |
| `G` | grab the selection: move, or type a number, `Enter` to confirm - the only way a scan moves |
| `X` / `Y` while moving | lock an axis (x only applies to artists) |
| `Shift` / `Ctrl` while moving | precision / snap to round numbers |
| `R` | reset the selected offsets to zero (or all of them) |
| a number | move the selected scans by it; `Enter` confirms, `Esc` cancels |
| `Ctrl+T` | add a caption where the cursor is |
| `Ctrl+L` | show or hide the legend |
| `C` | measure by typing: two temperatures, then `Enter` |
| `Delete` | remove the selection: an analysis, a caption, or scans |
| `Ctrl+A` / `Alt+A` | select everything / nothing; `Shift+click` adds |
| `H` / `Alt+H` | hide the selection / show everything |
| `Shift+M` | set the molar mass |
| `N` | show or hide the outliner |
| `F3` | **operator search**: everything, filtered by what is selected |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo, including a file you removed - and zoom, pan and fit, one gesture at a time |
| `Ctrl+S` / `Ctrl+E` | save the session / export the figure |
| `Ctrl+,` | settings: the house style, for every figure and for this one |

The rule is short on purpose: **a drag acts on what it starts near.**
"Near" is the pick distance (Settings > Handling, 14 px unless you change
it): start within it of a curve and the drag marks an interval; of a label,
the arrow or the legend and it moves that; anywhere else it draws a box. A
click selects, a double-click opens settings. A scan moves with `G` and
nothing else, and an analysis label moves up or down only, with its leader
arrow stretching to follow.

The menu bar is File, Edit, **Search** (the same as `F3`) and Help (About).
Everything else lives in the search, filtered by what is selected.

Right-click a curve for its three entries (settings, molar mass, add a
label).

The figure follows the DSC_Plotter template: no grid, ticks pointing inward
with minor ticks, an italic `T` against an upright unit, and integrations
shaded between the curve and their baseline. All of it is editable per object,
and the x axis can be drawn in degrees Celsius, Kelvin or Fahrenheit.

## Measuring

Press on a curve and drag along it (a double-click-drag works too): the
stretch between the two crosshairs is the interval. Let go, and a short list opens under the pointer -
Onset, Integration, Glass transition and the rest; one click, or type and
`Enter`. The analysis is computed, drawn and added to the outliner at once,
and it is one undo step. `Esc` on the list drops the interval.

To give the temperatures as numbers instead, select one scan and press `C`,
then type a temperature for each crosshair (in whatever unit the axis is
showing) and `Enter`; `Esc` steps back one stage at a time. Double-clicking
an analysis made here brings its cursors back so the interval can be
adjusted.

The arithmetic is `trios_analysis`, the same code the reader uses for the
analyses TRIOS stored, so a measurement made here and one read out of a `.tri`
are the same kind of thing. Against a stored integration in OJ-12 the panel
computes 13.3 J/g where the file says 13.2611.

Each analysis marks its interval with a bracket along the curve (one
tickbox hides it), and a cursor can be picked up and dragged rather than
replaced. Adjusting an existing analysis keeps the model it already has.
Analyses made here are saved with the session and recomputed from the file
when it is reopened.

A finished analysis arrives with its own caption - `\Delta*H* = 13.247 J/g`,
`*T*_{g} = 78.9 degC` - which is editable text in its settings. Captions
anywhere in the figure take the same small markup: `*T*` for italic, `_{g}`
for a subscript, and a backslash name for a Greek letter.

The caption's **alignment** is the plotter's `flush`: which edge of the text
sits on the leader arrow. Left reads away to the right of the feature, right
to the left, centred hangs over it. By default it follows the analysis kind
as the template does - tangent constructions (onset, endset, glass
transition) flush left, integrals centre.

## House style

`Ctrl+,` (Edit > Settings) sets the sizes and the label alignment, in two
columns:

- **Default** is yours: kept on this computer, used by every figure, and
  there the next time the program starts. The **pick distance** lives here
  too, under Handling: it is about your hand, not about a figure.
- **This figure** is saved in the session file and wins over the default,
  for this figure only. Left on "default", it follows the column beside it.

A size chosen in an object's own settings (double-click it) wins over both,
and its **Default** button hands it back.

## Exports

| Export | What it is for |
| :-- | :-- |
| PNG / SVG | the figure, drawn in the light palette, warnings stamped on |
| CSV | the curves as numbers, one x/y column pair per scan |
| `DSC_Plotter.py` | the arrangement as a driver for ACH-DSC-Plotter |

The last one is the point of the panel: it arranges, the plotter publishes.
With `achdsc` installed it writes a complete, runnable `DSC_Plotter.py` with
your paths, segments, colours and offsets already in it; without it, the
driver section alone, to paste into a copy made by `dsc -c .`.

## The name, and changing it

`DSC-Panel` is a working title, so the name lives in exactly one module
(`src/dscpanel/branding.py`) and a test fails if it is hard-coded anywhere
else. Putting the program in the Start Menu is opt-in and reversible, and it
writes down what it created, so a later rename can take the old name away:

```bash
dsc-panel register              # Start Menu entry (add --desktop for one there too)
dsc-panel register --list       # what is registered
dsc-panel register --remove     # take it away again
dsc-panel register --clean-legacy   # after a rename: remove the old name's entries
```

Your own name for it, on any platform (a `.cmd` shim on Windows, a symlink in
`~/.local/bin` elsewhere):

```bash
dsc-panel alias dscp
dsc-panel alias dscp --remove
```

## Project layout

```
src/dscpanel/
  branding.py        every place the program says its own name
  register.py        Start Menu entry, aliases, and the manifest of both
  core/              UI-free: model, units, arranging, undo, session, export
    trios_io.py      VENDORED reader (see tools/vendor.py)
    trios_analysis.py  VENDORED analyses
  ui/                the painted plot, the outliner, the F3 palette, dialogs
tools/vendor.py      copies the reader in from ACH-DSC-Plotter
docs/PLAN.md         what is built, what is next, what is still undecided
docs/OPERATORS.md    every operator, its key and when it lights up
```

## Development

```bash
python -m pytest -q
python tools/vendor.py --check     # has the vendored reader gone stale?
```

Measurements are not committed. The tests that need a real `.tri` look for
paths in `ACHDSC_TESTDATA` or in an uncommitted `tests/local_testdata.txt`,
and skip when there are none.

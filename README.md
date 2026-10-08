# Triplot

An interactive panel for stacked DSC scans from TA Instruments **TRIOS**
files. Drop `.tri` files on it, stack the scans into the arrangement you want,
mark an interval on a curve to analyse it, and hand the result to a figure: a
PNG or SVG, a CSV, or a `DSC_Plotter.py` script that redraws it in matplotlib.

It reads TRIOS `.tri` files and `.txt` exports from DSC and SDT (TGA + DSC)
instruments with its own reader, validated against TRIOS's exports value by
value (`tests/test_reader.py`).

```bash
pip install triplot
triplot                      # start it
triplot my-sample.tri        # straight into a file
triplot register             # put it in the Start Menu (optional)
```

Python 3.10 or newer; PySide6 (the Essentials only), numpy and RDKit come
with it. From a checkout, `pip install -e <checkout>` installs it editable.
Version 1.2.1; what changed is in `CHANGELOG.md`.

It was called **DSC-Panel** until 1.0.0 and installed from the repository
as `ach-dsc-panel`. To move over, uninstall that first (both install the
same `dscpanel` package), then clean up the old name's Start Menu entry:

```bash
pip uninstall ach-dsc-panel
pip install triplot
triplot register --clean-legacy
triplot register
```

Its preferences, presets and window place come across by themselves the
first time Triplot starts, and saved figures keep their `.dscpanel`
extension.

## What it does differently from a plotting script

- **Every segment is an object.** A `.tri` holds a heating ramp, a cooling
  ramp and usually five more; each one is a scan you can select, move, hide,
  colour and right-click. A file opens with its first heating scan on the
  plot and every other segment listed in the outliner, one tick away - so
  comparing the second and third up-scans of four samples is four ticks.
- **Three themes.** `blender-default` is the dark screen one, `light` is
  the same figure on white, `boombox` a brushed-metal dark one. Exports are
  always light, whichever is on screen.
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
- **A legend when you want one** (tick it in the outliner): a colour sample and a name per
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

| Key | What it does |
| :-- | :-- |
| click | select what is under the pointer (`Shift` adds) |
| drag from a curve | **mark an interval**; let go and pick the analysis |
| drag from an artist | move it: the arrow, the legend, a label, an analysis label, an axis caption |
| drag from empty space | **box select** curves, labels and every other artist (with `Shift`, a box from anywhere, adding) |
| double-click | settings: a curve, an analysis, an axis spine, a caption |
| two-finger swipe, mouse wheel, or middle-button drag | every curve taller or flatter, each in its place (drag up: taller); the axis rescales and the offsets follow, so the numbers stay true. With curves selected, only their own y axis: the heat flow and the m% one at a time |
| `Shift` + swipe or middle drag | pan the view, in whichever direction the hand goes |
| pinch, `Ctrl` + wheel or middle drag | zoom both axes about the pointer (Windows sends a pinch as `Ctrl+wheel`) |
| `Alt` + swipe or middle drag | zoom the page, like a document; with `Shift`, move it (`Alt+F` fits it again) |
| `Z` | cycle zoom: box, horizontal, vertical (`Esc` leaves) |
| `P` | cycle pan: horizontal, vertical, free |
| `F` / `Home` | fit the view, with room for every analysis label shown |
| `Esc` | back to plain select |
| `G` | grab the selection: move, or type a number, `Enter` to confirm - the only way a scan moves |
| `X` / `Y` while moving | lock a direction (a scan only moves in y) |
| `Shift` / `Ctrl` while moving | precision / snap to round numbers |
| `R` | reset the selected offsets to zero (or all of them) |
| a number | move the selected scans by it; `Enter` confirms, `Esc` cancels |
| `Ctrl+T` | on selected curves: a label each, saying its name, above its right end; else a caption where the cursor is (retype it with a double-click) |
| `Ctrl+Shift+T` | add a note: a caption with an arrow to the point under the cursor (on a curve, it belongs to that scan); drag the ring at its tip to re-aim it |
| `S` with only scans selected | spread them evenly, the lowest held still; `T`, `B`, `M` hold the top, the bottom or the middle instead; `P` keeps the stack's own gaps in proportion; type the step, `Ctrl` for a round one |
| `Ctrl+P` / `Alt+P` | give the selected labels to the selected scan (they then move with it) / free them; or drag a label onto a scan in the outliner |
| double-click a page handle | type the figure's size in cm or inches, the aspect ratio kept |
| `Ctrl+L` / `Ctrl+R` / `Ctrl+M` | align analysis labels left / right / centred on their arrows |
| `C` | measure by typing: two temperatures, then `Enter` |
| `Delete` | remove the selection: an analysis, a caption, or scans |
| `Ctrl+A` / `Alt+A` | select everything / nothing; `Shift+click` adds |
| `H` / `Alt+H` | hide the selection / show everything |
| `Shift+M` | set the molar mass |
| `N` | show or hide the outliner |
| `F3` | **operator search**: everything, filtered by what is selected; the ones used last on top, Enter repeats the newest; right-click one for an alias of your own |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo, including a file you removed - and zoom, pan and fit, one gesture at a time |
| `Ctrl+S` / `Ctrl+E` | save the session / export the figure |
| `Ctrl+,` | settings: the house style, for every figure and for this one |
| `Ctrl+W` | close the pop-up in front; the window only when no pop-up is open |

The rule is short on purpose: **a drag acts on what it starts near.**
"Near" is the pick distance (Settings > Handling, 8 px unless you change
it): start within it of a curve and the drag marks an interval; of a label,
the arrow or the legend and it moves that; anywhere else it draws a box. A
click selects, a double-click opens settings. A scan moves with `G` and
nothing else, and an analysis label moves up or down only, with its leader
arrow stretching to follow.

The menu bar is File, Edit, **Search** (the same as `F3`) and Help (About).
Everything else lives in the search, filtered by what is selected.

Right-click a curve for its settings, its molar mass, a label or a note;
right-click an axis's number to hide it (its tick stays).

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
showing) and `Enter`; `Esc` steps back one stage at a time.

Double-clicking an analysis made here brings its cursors back as gizmos,
with its settings opened beside them rather than over them. Drag a gizmo
and the analysis is recomputed as you let go; close the settings - OK,
Cancel or the window's X - and the interval is confirmed and the gizmos go.

The arithmetic is `trios_analysis`, the same code the reader uses for the
analyses TRIOS stored, so a measurement made here and one read out of a `.tri`
are the same kind of thing. Against a stored integration in a reference run
the panel computes 13.3 J/g where the file says 13.2611.

Each analysis marks its interval with a dash on the curve at each end, in
the axis colour; an onset, endset or glass transition also gets straight
lines from those dashes to its result point, the template's construction
(one tickbox hides them). A cursor can be picked up and dragged rather than
replaced. Adjusting an existing analysis keeps the model it already has.
On an m% curve, an onset, endset or mass at a temperature can also draw
a dashed line across the plot at the m% of its point, the value at the
left edge ("Mass line" in its settings); drag the value along it.
Analyses made here are saved with the session and recomputed from the file
when it is reopened.

A finished analysis arrives with its own caption - `\Delta*H* = 13.247 J/g`,
`*T*_{g} = 78.9 degC` - which is editable text in its settings. Captions
anywhere in the figure take the same small markup: `*T*` for italic, `_{g}`
for a subscript, and a backslash name for a Greek letter.

**Hiding the ends of a curve** (Scan settings > Hide) is the plotter's
`x_truncate`: the first and last N % of the POINTS, never a temperature
window - a DSC curve doubles back at its start and runs backwards when
cooling. The hidden ends show dashed while the scan is hovered or selected,
and are left out of the fit, the analyses and the exports. For the same
reason an interval dragged along a curve is the stretch of points between
where the drag began and ended, not every point between two temperatures.

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
and its **Default** button hands it back. The **caption distance** is the
space between an axis's numbers and its caption.

Every settings window applies as you touch it and keeps the changes however
it is closed; its **Revert** button is the one way back. Closing the program
with unsaved changes asks first.

## Figure size

Edit > **Figure size and margins** (saved with the session) gives the figure
one of three sizes: whatever the window is, a fixed aspect ratio, or an
**exact size** in centimetres or inches with four margins. At an exact size
the margins decide the axes box - the numbers and captions live inside them,
and the dialog says when one does not fit - so two figures with the same
settings have identical axes boxes whatever their numbers say, and sit side
by side in Word without adjusting. On screen the figure is shown as its page,
scaled to fit. **Use for new figures** makes a layout the default.

Each axis can sit on either side (x bottom or top, y left or right) and hide
its numbers, single numbers or its caption (double-click the axis line or
its numbers). On an exact figure an axis moved to its other side takes its
margin with it, and no margin can be cut into the numbers it holds - the
one at the corner of the box included.

## Sessions

`Ctrl+S` saves the figure as a `.dscpanel` session: the arrangement and the
paths of its files, never the data. A file that has moved is looked for
beside the session (its folder and the folders under it, by name). One that
is nowhere stays in the outliner, in red and MISSING, with its curves,
analyses and labels kept - saved again as they were - and a right-click
looks for it: **Locate...** by hand, or **Find in a folder...**, which
offers the files under a folder named like it (the same extension, the name
85 % alike or more, a copy's "(1)" first). Found, the figure opens again
with everything back. **Details...** on any file's right-click menu says
where it is, its size, dates and a SHA-256 of its contents, and what the run
records - to tell apart two files of one name.

## Exports

| Export | What it is for |
| :-- | :-- |
| PNG / SVG | the figure, drawn in the light palette, warnings stamped on; at an exact size, exactly that size (the PNG carries its dpi, the SVG its millimetres) |
| CSV | the curves as numbers, one x/y column pair per scan |
| TRIOS Excel | File > Export as TRIOS Excel workbooks: the segments on the figure (the selected curves' only, if any) laid out as TRIOS's own Excel export - a Details sheet, then a sheet per step with every sample - one workbook per file |
| Measured data | File > Export the measured data (tab-separated): the same segments as text, a .csv per file - the run's details on `#` lines, a header row (`Segment`, then each column with its unit), every sample; `pandas.read_csv(path, sep="\t", comment="#")` reads it |
| `DSC_Plotter.py` | the arrangement as a driver script for the DSC_Plotter matplotlib template |

The driver needs that template's `achdsc` package, which is not on PyPI.
With it installed the export is a complete, runnable `DSC_Plotter.py` with
your paths, segments, colours and offsets already in it; without it, the
driver section alone, to paste into a copy made by `dsc -c .`.

## The Start Menu, aliases, and the name

The name lives in exactly one module (`src/dscpanel/branding.py`) and a test
fails if it is hard-coded anywhere else; that is how DSC-Panel became
Triplot. Putting the program in the Start Menu is opt-in and reversible,
and it writes down what it created, so a rename can take the old name away:

```bash
triplot register                # Start Menu entry (add --desktop for one there too)
triplot register --list         # what is registered
triplot register --remove       # take it away again
triplot register --clean-legacy # after a rename: remove the old name's entries
```

Your own name for it, on any platform (a `.cmd` shim on Windows, a symlink in
`~/.local/bin` elsewhere):

```bash
triplot alias tp
triplot alias tp --remove
```

## Project layout

```
src/dscpanel/
  branding.py        every place the program says its own name
  register.py        Start Menu entry, aliases, and the manifest of both
  core/              UI-free: model, units, arranging, undo, session, export
    trios_io.py      the TRIOS reader (docs/TRI-FORMAT.md)
    trios_analysis.py  the TRIOS analyses, recomputed
  ui/                the painted plot, the outliner, the F3 palette, dialogs
docs/PLAN.md         what is built, what is next, what is still undecided
docs/TRI-FORMAT.md   the binary .tri format, and how it was decoded
docs/OPERATORS.md    every operator, its key and when it lights up
```

## Development

```bash
python -m pytest -q
```

Measurements are not committed. The tests that need a real `.tri` look for
paths in `TRIOS_TESTDATA` or in an uncommitted `tests/local_testdata.txt`,
and skip when there are none. They name a real file by a hash of its file
name (`tests/conftest.py`, `hashed_name`), so no sample id is in the
source.

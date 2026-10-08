# Changelog

## Unreleased

- Every colour is printed as it is on the screen: on a white page and in
  every export the default curve colours are no longer darkened (their
  orange came out brown).
- The swipe (wheel, middle drag) on SELECTED curves rescales their own
  y axis: select a heat flow and the heat flows grow or flatten while
  the m% stays as it is, and the other way round; with curves on both
  axes selected, both. Nothing selected: the main axis, as before.
- A DTG curve has an analysis: "Peak temperature", where the mass
  changes fastest between the cursors (*T*_{p}).
- Mass lines: an onset, endset or mass-at-temperature on an m% curve
  can draw a dashed line across the plot at the m% of its point, the
  value at the left edge ("Mass line" in its settings; the house
  style's "Mass lines" format, 0.1 % built in). The line is thinner
  than the curves ("Mass line width"), lies under everything, and
  goes faint where it passes behind a curve, a label, a tangent or a
  decorator. Drag its value along the line, or a little up or down -
  or click it and press G (X and Y lock); H hides the line.
- File > Export as TRIOS Excel workbooks: the segments on the figure
  (the selected curves' only, if any) as TRIOS's own Excel export lays
  them out - a Details sheet, then a sheet per step with every sample,
  the instrument's empty ones as empty cells - one workbook per file.
  Needs openpyxl, now a dependency.
- File > Export the measured data (tab-separated): the same segments as
  plain text, a .csv per file - what the run records on lines starting
  with "#", a header row of names and units, then every sample, its
  segment's number first; an empty sample is an empty cell.
- A procedure of 128 characters or more in a .tri was read as missing.

- A file a session cannot find stays in the outliner, in red and
  MISSING, and what the session held of it - its curves, their analyses,
  the labels on them - is kept and saved again as it was (before, the
  next save lost all of it). Right-click it: Locate... (by hand), Find in
  a folder... (the files under a folder named like it - the same
  extension, the name 85 % alike or more, a copy's "(1)" first - offered,
  never taken by themselves), Details..., Forget. Found, the figure opens
  again with everything back.
- Details... on a file's right-click menu: where it is, its size and
  dates, a SHA-256 of its contents and what the run records - to tell
  apart two files of one name.

- The source file in a file's settings, and a curve's: type or paste
  another path (the quotes Windows adds with Ctrl+Shift+C are dropped)
  and press Enter, or Browse... It takes the file's place as "Change the
  source file" does - one undo step - and the window opens again on it.

- F3 lists the operators you ran from it last on top, the newest
  selected: F3 then Enter does it again. Remembered between runs.
- Aliases of your own: right-click an operator in F3, "Add an alias...",
  and the word you type finds it from then on (shown greyed beside it).
  Edit > Operator search saves them as a .json file to share; dropping
  such a file on the window installs its aliases (you are asked first;
  operators this panel does not have are skipped), and "Reset the
  operator search to factory" forgets them and the recent list.

- Settings windows in an order you can work down: the text first, then
  the colour, then what only the window can set (a marker line's
  position, a note's point and arrow, a region's stretch), then sizes and
  style; Show and Layer at the bottom.
- A band marker's (marker line's) window has no arrow rows any more: they
  belonged to notes. A label's arrow rows appear only once "Leader
  arrow" makes it a note.

## 1.2.1 (2026-10-02)

- An onset's or endset's label stands on the side its peak goes (above a
  peak that rises, below one that falls), as an integration's does. It
  went to the other side whenever the onset was made by dragging along
  the curve.

## 1.2.0 (2026-10-02)

- On a white page (and in every export) a colour you picked is drawn
  exactly as picked; only the default screen palette is darkened to read
  on paper. A yellow used to come out olive.
- `Ctrl+T` asks nothing: on selected curves it makes a label for each,
  saying its name, hanging from the curve (above its right end); with nothing
  selected, one free label "Label" to retype with a double-click. New
  labels are selected.
- The pick distance is 8 px unless you change it (it was 14).
- S on curves holds the lowest still, as before; T, B or M while it is live
  holds the top, the bottom or the middle of the stack still instead, where
  it is when the key is pressed. The dashed line runs through the held curve.
- The plain swipe (wheel, middle drag) makes every curve taller or flatter in
  its place; the axis rescales and the offsets follow. It used to scale the
  axis about y = 0, which spread the stack apart: P during S does that now,
  keeping the stack's own gaps in proportion.
- A pan shows the data moving under a still frame (the whole page moved
  until the button was let go).
- Faster drawing: every change shows at once as a draft, the curves drawn
  thin, and in full once nothing has changed for a moment; curves are put
  together several times faster.
- Align from F3 shows at once and moves labels hanging from a curve too;
  new: space the selected artists evenly across or down.
- A box selects labels, markers and other artists, not only curves.
- Colours: the colour as #rrggbb beside every swatch, to copy and paste;
  "Inherit" makes a colour follow another object's for good; a label given
  to a curve takes the curve's colour.
- A label on a curve is placed by x and y like every other artist (no more
  "Distance" and "Sideways"), and still moves with its curve.
- The page-margin blades are there on every figure; taking one on a figure
  that is not of an exact size makes it exact as it is on screen (the
  axes box stays where it is), and says so in orange. Choosing "an exact
  size" in Figure size and margins also starts from the screen.
- A session whose files were moved looks for them beside itself (its
  folder and the folders under it) and keeps their curves.

## 1.1.0 (2026-09-30)

**Renamed Triplot** (it was DSC-Panel) and released on PyPI:

```bash
pip install triplot
```

The commands are `triplot` and `triplot-gui`; the import name stays
`dscpanel`, and saved figures keep `.dscpanel`. Uninstall `ach-dsc-panel`
first, then run `triplot register --clean-legacy` once to take the old Start
Menu entry away. The first start copies DSC-Panel's preferences, presets
and registration across.

- Change a file's source in the outliner, keeping its curves' arrangement.
- Side (left/right, bottom/top) in every axis window.
- A quieter offset overlay while shifting scans.
- One molar mass per file, and a molar mass calculator beside it: sum
  formulas, SMILES, and building-block compositions.
- "Same as parent" for the colour of a label that belongs to a curve.
- Page-margin blades at the corners of an exact-size figure: pulled in
  they cut white space off, out they add some; the axes box keeps its
  size. Their numbers on a double-click; F3 "Tighten the page margins"
  down to the last drawn pixel; room grown for an axis given back when the
  axis goes. The page's corner squares are gone.
- The data margins' arrows open their numbers on a double-click.
- Interval marks have a length of their own (shorter by default).
- "Set the molar mass" offers the calculator.
- Two significant figures in the offset shown while moving a scan.
- Decorators stay on the page when zooming again; an F3 toggle makes them
  follow the zoom.
- Arrows in one solid colour.
- Mirror pictures and structures (Ctrl+Shift+H / Ctrl+Shift+V), on
  screen whatever they are turned by; paste as text is Ctrl+Alt+V.
- A turned structure's selection holds its labels' hydrogens.
- Hide single axis numbers: right-click one ("Hide the number 50"; its
  tick stays), or type them in the numbers' window. They are kept with
  the unit they were chosen in.
- The numbers' window shows what the axis writes with its Format.
- X and Y lock the move of an axis caption.
- "Show or hide the y-offset markers" acts on the selected scans (every
  scan when none is selected).
- Moving an axis to its other side moves its margin with it on an
  exact-size figure; the axes box keeps its size.
- Fixed: a margin could be cut so far that the number at the corner of the
  box (an x axis's first, with the y axis on the right) was cut in two.
- Fixed: the y axis could not be double-clicked while its caption was
  hidden, nor on its line and inward ticks, nor with a slow double-click.
- Fixed: hiding a curve dropped its labels on the middle of the plot, and
  dragging one ended the program. They now stay where they hang.
- Fixed: an error inside a mouse, key or paint handler ended the program
  without a word in the log; it is now logged, and the program carries on.

## 1.0.0 (2026-09-29)

The first release: an interactive panel for stacked DSC and SDT/TGA scans
from TA Instruments TRIOS files, as DSC-Panel. Not released on PyPI.

What it does, in brief:

- **Reading**: TRIOS `.tri` files and their `.txt` exports, DSC and SDT
  (TGA + DSC), with the program's own reader, validated value by value
  against TRIOS's exports. The exotherm direction is
  read per file; a sample or molar mass is never assumed.
- **Curves**: every segment is a scan of its own - heat flow, m% (a TGA
  curve) and DTG (its derivative, %/degC or %/min) - shown, hidden,
  coloured, labelled and stacked; mW, W/g and W/mol, % and mg.
- **Stacking**: continuous offsets (G, or a typed number), S to spread
  evenly in the order the offsets have (R turns it over), Stack evenly,
  align, swap two; files renamed (F2) and dragged into order in the
  outliner.
- **Analyses**: TRIOS's own (onset, endset, Tg, integration, peak height)
  and new ones measured by dragging along a curve, with tangent
  constructions, labels as templates (`{}` the number, `{Tp}` the peak
  temperature), units per analysis, shading (translucent or opaque).
- **The figure**: exact size or aspect, fit margins set by arrows on the
  page's edge, axis ranges typed and locked, themes, house style and
  presets, decorators (labels, notes hanging from their curves, marker
  lines, legend, pictures, SMILES structures) that move with the data when
  zoomed; copy and paste of labels; a colour picker with a hue wheel and a
  dropper; sums in every number box.
- **Exports**: PNG and SVG at exact size, CSV, and a `DSC_Plotter.py`
  driver script (its features frozen).
- **Sessions**: `.dscpanel` files keep the arrangement, never copies of the
  data; older sessions open where they were.

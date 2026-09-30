# Changelog

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

# Changelog

## 1.0.0 (2026-09-29)

The first release: an interactive panel for stacked DSC and SDT/TGA scans
from TA Instruments TRIOS files. Installed from GitHub (not on PyPI):

```bash
pip install git+https://github.com/ACH-Repo/ACH-DSC-Panel.git@v1.0.0
```

What it does, in brief (the round-by-round log is `docs/PLAN.md`):

- **Reading**: TRIOS `.tri` files and their `.txt` exports, DSC and SDT
  (TGA + DSC), with the program's own reader, validated value by value
  against TRIOS's exports (`docs/TRI-FORMAT.md`). The exotherm direction is
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
  driver script (frozen at its 2026-09-28 features).
- **Sessions**: `.dscpanel` files keep the arrangement, never copies of the
  data; older sessions open where they were.

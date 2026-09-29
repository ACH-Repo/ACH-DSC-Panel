# Operators

Every user-facing action, as registered in `ui/window.py` through
`core/ops.py`. The menus, the keyboard and the F3 palette all read that one
registry, so an action cannot exist in one of them and not in the others.

**Lights up when** is the `enabled` predicate. F3 lists an operator that is
not allowed right now, greyed out rather than hidden, because the palette is
also how somebody finds out what the program can do.

This file is GENERATED. After adding an operator, run:

    python tools/gen_operators.py > docs/OPERATORS.md

## File

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Open TRIOS files... | `Ctrl+O` | always |  |
| New figure | `Ctrl+N` | always |  |
| Open a session... | `Ctrl+Shift+O` | always |  |
| Save the session | `Ctrl+S` | a scan is open |  |
| Save the session as... | `Ctrl+Shift+S` | a scan is open |  |
| Export the figure... | `Ctrl+E` | a scan is open |  |
| Export the curves as CSV... |  | a scan is open |  |
| Export as a DSC_Plotter.py driver... |  | a scan is open | hands the arrangement to ACH-DSC-Plotter |
| Close the pop-up in front, the tab, or the window | `Ctrl+W` | always |  |

## Edit

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Paste (a picture, a SMILES, text) | `Ctrl+V` | always |  |
| Paste as a text label | `Ctrl+Shift+V` | always |  |
| Undo | `Ctrl+Z` | there is something to undo | also walks back zoom, pan and fit, one gesture at a time |
| Redo | `Ctrl+Y` | there is something to redo |  |
| Figure size and margins... |  | always | exact cm/in and margins, saved with the session |
| Apply a style preset... |  | always |  |
| Save this figure's style as a preset... |  | always |  |
| Open the style presets folder |  | always |  |

## Select

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Select everything | `Ctrl+A` | a scan is open |  |
| Select nothing | `Alt+A` | something is selected |  |
| Invert the selection | `Ctrl+I` | a scan is open |  |
| Select every scan of this sample |  | a scan is selected |  |
| Select every offset marker |  | always |  |

## Transform

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Move the selection | `G, then a number, Enter (Esc cancels)` | something is selected | then a number, Enter; Shift is precision, Ctrl snaps |
| Scale the selection | `S, then move or type a factor, Enter (Esc cancels); with only scans selected, spreads them about y = 0` | the arrow, the legend or a label is selected |  |
| Align the artists' left edges | `Ctrl+Shift+Alt+L` | always |  |
| Align the artists' right edges | `Ctrl+Shift+Alt+R` | always |  |
| Align the artists' top edges | `Ctrl+Shift+Alt+T` | always |  |
| Align the artists' bottom edges | `Ctrl+Shift+Alt+B` | always |  |
| Align the artists' centres, side to side | `Ctrl+Shift+Alt+C` | always |  |
| Align the artists' middles, up and down | `Ctrl+Shift+Alt+M` | always |  |
| Stack the selected scans evenly |  | two or more scans selected |  |
| Distribute the offsets evenly |  | three or more scans selected |  |
| Align the selection to the active scan |  | two or more scans selected | closed-form fit to the first selected scan |
| Reset the offsets of the selected scans | `R, with scans selected` | a selected scan has an offset, or a label or the legend is selected (then R rotates) |  |
| Rotate the selection | `R, with a label or the legend selected` | a label or the legend is selected |  |

## Object

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Text bigger | `Ctrl+Up` | always |  |
| Text smaller | `Ctrl+Down` | always |  |
| Bring to front | `Ctrl+Shift+PgUp` | always |  |
| Bring forward | `Ctrl+PgUp` | always |  |
| Send backward | `Ctrl+PgDown` | always |  |
| Send to back | `Ctrl+Shift+PgDown` | always |  |
| Settings for the selection... | `double-click` | something is selected | double-click does the same |
| Hide the selection | `H` | something is selected |  |
| Show everything | `Alt+H` | something is hidden |  |
| Remove the selection | `Del` | a scan is selected |  |
| Remove every scan of this file |  | always |  |
| Colour for the selection... |  | a scan is selected |  |
| Show every analysis of the selected scans |  | always |  |
| Hide every analysis of the selected scans |  | always |  |
| Set the molar mass... | `Shift+M` | a scan is selected | there is no default M, so this is how W/mol happens |
| Show or hide the y-offset markers |  | always |  |
| Show or hide the legend |  | always | or its tick in the outliner |
| Align labels left | `Ctrl+L` | an analysis, or a scan with one shown, is selected | the selected labels, else all on the selected scans |
| Align labels right | `Ctrl+R` | an analysis, or a scan with one shown, is selected |  |
| Align labels centred | `Ctrl+M` | an analysis, or a scan with one shown, is selected |  |
| Legend settings... |  | always |  |
| Add a label... | `Ctrl+T` | always |  |
| Add a marker line... | `or right-click the plot` | always |  |
| Add a note with an arrow... | `Ctrl+Shift+T, or right-click a curve` | always |  |
| Give the selected labels to the selected scan | `Ctrl+P, or drag the label onto the scan in the outliner` | always |  |
| Free the selected labels from their scan | `Alt+P` | always |  |

## View

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Fit the page to the window | `Alt+F` | always |  |
| Fit the view | `F or Home` | a scan is open |  |
| Set the x range... | `M` | always |  |
| X axis: temperature |  | the x axis is not temperature |  |
| X axis: time |  | the x axis is not time |  |
| Y axis: mW |  | the y axis is not mW |  |
| Y axis: W/g |  | the y axis is not W/g |  |
| Y axis: W/mol |  | the y axis is not W/mol |  |
| Mass axis: % of the sample mass |  | always |  |
| Mass axis: mg |  | always |  |
| Show or hide the mass curves |  | always |  |
| Show or hide the heat flow curves |  | always |  |
| Theme: blender-default |  | always |  |
| Theme: light |  | always |  |
| Theme: boombox |  | always |  |
| Show or hide the outliner | `N` | always | the dock on the right |
| X axis in Celsius |  | always |  |
| X axis in Kelvin |  | always |  |
| X axis in Fahrenheit |  | always |  |
| X axis: ticks and frame... |  | always |  |
| X axis numbers... |  | always |  |
| X axis caption... |  | always |  |
| Y axis: ticks and frame... |  | always |  |
| Y axis numbers... |  | always |  |
| Y axis caption... |  | always |  |

## Arrow

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Heat-flow arrow settings... |  | always |  |
| Flip the heat-flow direction |  | always | flips the data and the axis with it |
| Say it the other way round (exo / endo) |  | always | exo down <-> endo up: same figure, other word |

## App

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Search operators... | `F3` | always | also the Search button on the menu bar |
| Open the log folder |  | always |  |
| About DSC-Panel |  | always | Help menu: version, reader, Qt |
| Settings... | `Ctrl+,` | always | sizes, label alignment, pick distance |

## Analyse

| Operator | Key | Lights up when | Note |
| :-- | :-- | :-- | :-- |
| Mass at temperatures... |  | always |  |
| Measure on the selected scan | `C, or double-click-drag a curve` | always | the typed route; double-click-drag a curve is the quick one |
| Analyse the interval... | `Enter, with both cursors down` | always |  |
| Stop measuring |  | always |  |


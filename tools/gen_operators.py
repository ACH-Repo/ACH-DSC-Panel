"""Write docs/OPERATORS.md from the operator registry itself.

    python tools/gen_operators.py > docs/OPERATORS.md

MoloM keeps a hand-written OPERATORS.md and it drifts, because a list of
actions maintained beside the code is a list nobody updates in the same
commit. Here the document is GENERATED from the registry, so it cannot be
wrong about what exists, what key it has or when it is allowed. The only
hand-written parts are the prose at the top and the notes below, which is
the part a generator cannot supply.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: The one-line "why" for the operators where the label is not the whole
#: story. Everything else gets a blank.
NOTES = {
    "label.add": "on selected curves: their names, nothing asked",
    "file.export_driver": "hands the arrangement to ACH-DSC-Plotter",
    "transform.grab": "then a number, Enter; Shift is precision, Ctrl snaps",
    "arrange.align": "closed-form fit to the first selected scan",
    "sample.molar_mass": "there is no default M, so this is how W/mol happens",
    "arrow.flip": "flips the data and the axis with it",
    "arrow.relabel": "exo down <-> endo up: same figure, other word",
    "view.outliner": "the dock on the right",
    "object.settings": "double-click does the same",
    "measure.start": "the typed route; double-click-drag a curve is the quick one",
    "app.settings": "sizes, label alignment, pick distance",
    "app.about": "Help menu: version, reader, Qt",
    "app.operator_search": "also the Search button on the menu bar",
    "app.aliases_save": "a .json to share: dropped on a panel, it installs them",
    "app.aliases_install": "or drop the file on the window",
    "app.search_reset": "your aliases and the recent list; asked first",
    "edit.undo": "also walks back zoom, pan and fit, one gesture at a time",
    "legend.toggle": "or its tick in the outliner",
    "figure.layout": "exact cm/in and margins, saved with the session",
    "analysis.flush_left": "the selected labels, else all on the selected scans",
}

#: `enabled` is a predicate, so it cannot describe itself. These are its
#: sentences. An operator with no entry is always allowed.
WHEN = {
    "file.session_save": "a scan is open",
    "file.session_save_as": "a scan is open",
    "file.export_image": "a scan is open",
    "file.export_csv": "a scan is open",
    "file.export_driver": "a scan is open",
    "view.fit": "a scan is open",
    "select.all": "a scan is open",
    "select.invert": "a scan is open",
    "select.none": "something is selected",
    "transform.grab": "something is selected",
    "object.settings": "something is selected",
    "object.hide": "something is selected",
    "object.remove": "a scan is selected",
    "object.colour": "a scan is selected",
    "sample.molar_mass": "a scan is selected",
    "select.same_sample": "a scan is selected",
    "arrange.stack": "two or more scans selected",
    "arrange.align": "two or more scans selected",
    "arrange.distribute": "three or more scans selected",
    "arrange.reset": "a selected scan has an offset, or a label or the "
                     "legend is selected (then R rotates)",
    "transform.rotate": "a label or the legend is selected",
    "transform.scale": "the arrow, the legend or a label is selected",
    "object.show_all": "something is hidden",
    "edit.undo": "there is something to undo",
    "edit.redo": "there is something to redo",
    "view.axis_temperature": "the x axis is not temperature",
    "view.axis_time": "the x axis is not time",
    "analysis.flush_left": "an analysis, or a scan with one shown, is selected",
    "analysis.flush_right": "an analysis, or a scan with one shown, is selected",
    "analysis.flush_center": "an analysis, or a scan with one shown, is selected",
}

ORDER = ("File", "Edit", "Select", "Transform", "Object", "View", "Arrow",
         "App")

HEAD = """# Operators

Every user-facing action, as registered in `ui/window.py` through
`core/ops.py`. The menus, the keyboard and the F3 palette all read that one
registry, so an action cannot exist in one of them and not in the others.

**Lights up when** is the `enabled` predicate. F3 lists an operator that is
not allowed right now, greyed out rather than hidden, because the palette is
also how somebody finds out what the program can do.

This file is GENERATED. After adding an operator, run:

    python tools/gen_operators.py > docs/OPERATORS.md
"""


def main():
    from PySide6.QtWidgets import QApplication
    from dscpanel.core import units
    QApplication.instance() or QApplication([])
    from dscpanel.ui.window import MainWindow
    window = MainWindow()
    lines = [HEAD]
    by_category = {}
    for op in window.ops.all():
        by_category.setdefault(op.category, []).append(op)
    for category in ORDER + tuple(sorted(set(by_category) - set(ORDER))):
        entries = by_category.get(category)
        if not entries:
            continue
        lines.append("## {}\n".format(category))
        lines.append("| Operator | Key | Lights up when | Note |")
        lines.append("| :-- | :-- | :-- | :-- |")
        for op in entries:
            key = op.shortcut or op.key or ""
            when = WHEN.get(op.id, "always")
            for unit in units.UNITS:
                if op.id.endswith("unit_" + unit.replace("/", "_")):
                    when = "the y axis is not {}".format(unit)
            lines.append("| {} | {} | {} | {} |".format(
                op.label, "`{}`".format(key) if key else "", when,
                NOTES.get(op.id, "")))
        lines.append("")
    # ASCII, whatever the console's code page: printed into a file by a
    # Windows shell, a degree sign arrived as one cp1252 byte, which is
    # not UTF-8 at all.
    text = "\n".join(lines)
    for char, word in (("\u00b0", "deg"), ("\u2212", "-")):
        text = text.replace(char, word)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

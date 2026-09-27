"""The main window: the plot, the outliner, and every operator.

The shape is MoloM's rather than the PXRD dialog's, because this is a program
and not a panel inside one: a real main window with docks, a status bar and a
menu bar whose entries are all operators. Every action is registered once in
`core/ops.py`, so the menu, the shortcut and the F3 palette can never disagree
about what exists or when it is allowed - and a shortcut claimed twice is a
startup error rather than a pair of QActions that quietly fire neither.

The window owns the undo stack, because undo is about the document and a
gesture in the plot is only one of the things that changes it. The plot hands
over what a gesture did (`transform_done`) rather than writing history itself.
"""

import json
import os
import re

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (QAction, QColor, QCursor, QImage, QKeySequence,
                           QPainter)
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog,
                               QDockWidget, QFileDialog, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QWidget)

from .. import branding
from ..core import (arrange, export, loader, measure, model, ops, session,
                    style, undo, units)
from ..core import figure as figure_module
from .dialogs import (AnalysisSettings, ArrowSettings, AxisSettings,
                      CaptionSettings, FigureSettings, LabelSettings,
                      ExportDialog, LegendSettings, NumberSettings,
                      OffsetMarkerSettings, RangeDialog, SampleSettings,
                      ScanSettings, install_basic_colours)
from . import appearance
from .loading import Loader
from .outliner import Outliner
from .palette import MeasurePalette, OperatorPalette
from . import plot as plot_module
from .plot import PlotWidget, paper_palette
from .settings import SettingsDialog


class MainWindow(QMainWindow):
    """One document, one plot, one outliner."""

    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        self.setWindowTitle(branding.window_title())
        self.doc = model.Document()
        # Dressed BEFORE any widget exists, so nothing is built in the
        # system's light look and repainted a moment later.
        appearance.apply(self.doc.theme)
        self.undo = undo.UndoStack(on_change=self._undo_changed)
        # The colour picker's basic colours: the plotter's, in its order.
        install_basic_colours()
        #: The export dialog's last choice of colours: light, for a page.
        self._export_light = True
        self.plot = PlotWidget(self.doc, self)
        self.setCentralWidget(self.plot)
        self.setAcceptDrops(True)
        self.resize(*self.opening_size())

        self.outliner = Outliner(self)
        self.outliner.set_document(self.doc)
        dock = QDockWidget("Outliner", self)
        dock.setObjectName("outliner")
        dock.setWidget(self.outliner)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._outliner_dock = dock

        self.readout = QLabel("")
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("color: #6ea8ff; font-weight: bold;")
        self.note = QLabel("")
        self.note.setStyleSheet("color: #c8a45a;")
        self.statusBar().addWidget(self.readout, 1)
        self.statusBar().addPermanentWidget(self.mode_label)
        self.statusBar().addPermanentWidget(self.note)

        self.loader = Loader(self)
        self.loader.loaded.connect(self._sample_loaded)
        self.loader.failed.connect(self._sample_failed)
        self.loader.progress.connect(self._loading_progress)

        self.plot.hovered.connect(self.readout.setText)
        self.plot.mode_changed.connect(self.mode_label.setText)
        self.plot.context_menu.connect(self._context_menu)
        self.plot.transform_done.connect(self._transform_done)
        self.plot.measure_ready.connect(self._measure_ready)
        self.plot.view_committed.connect(self._view_committed)
        self.plot.selection_changed.connect(self._selection_changed)
        self.plot.activated.connect(self.edit_object)
        self.outliner.visibility_changed.connect(self._set_visible)
        # A sweep across the outliner's boxes is ONE undo step.
        self.outliner.sweep_started.connect(
            lambda: self.undo.begin_group("show / hide"))
        self.outliner.sweep_finished.connect(self.undo.end_group)
        self.outliner.segment_toggled.connect(self.toggle_segment)
        self.outliner.selection_picked.connect(self._outliner_selected)
        self.outliner.activated_object.connect(self.edit_object)
        self.outliner.menu_for.connect(
            lambda obj, pos: self._context_menu(obj, pos))

        self.ops = ops.OperatorRegistry()
        self._last_operator = ""
        self._register_ops()
        self._install_shortcuts()
        self._build_menus()
        self._undo_changed()
        # An empty window has nothing to lose; from here on, a difference
        # from this is a change.
        self.mark_clean()

    #: Wider than tall, because a DSC figure is, and small enough to sit
    #: beside something else. Clamped to the screen, which is the trap the
    #: PXRD window hit at 150% scaling.
    PREFERRED_SIZE = (1080, 660)

    def opening_size(self):
        width, height = self.PREFERRED_SIZE
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, int(available.width() * 0.9))
            height = min(height, int(available.height() * 0.85))
        return max(640, width), max(420, height)

    # --------------------------------------------------------------- refresh
    def refresh(self, keep_view=True):
        plot_module.set_theme(self.doc.theme)
        # The windows around the plot wear its theme too: the outliner, the
        # menus and the dialogs were light beside a dark plot.
        appearance.apply(self.doc.theme)
        self.plot.rebuild(keep_view=keep_view)
        self.outliner.refill()
        self._sync_title()

    def _sync_title(self):
        subject = os.path.basename(self.doc.path) if self.doc.path else ""
        if self.is_modified():
            subject = (subject or "unsaved") + " *"
        self.setWindowTitle(branding.window_title(subject))

    # ------------------------------------------------------ unsaved changes
    def _document_state(self):
        """What saving now would write, as text - for "has anything changed".

        Compared rather than counted: undoing back to the saved state is
        clean again, a zoom (on the undo stack, not in the file) is not a
        change, and what never touches the undo stack (a file opened, the
        unit switched) is one.
        """
        # The plot's framing as it is NOW, without writing it anywhere: this
        # runs on every title refresh, and writing it onto the document here
        # wiped a just-opened session's saved view before it was restored.
        state = session.to_state(self.doc)
        state["view"] = session.view_to_state(self._current_view())
        return json.dumps(state, sort_keys=True, default=str)

    def _current_view(self):
        """The plot's framing, or None where it is fitted."""
        state = self.plot.view_state()
        return (None if state["x"] is None and state["y"] is None
                else dict(state))

    def _sync_view(self):
        """The framing on the document, where the session file finds it:
        the plot owns the live view, the file keeps it."""
        self.doc.view = self._current_view()

    def mark_clean(self):
        self._clean_state = self._document_state()
        self._sync_title()

    def is_modified(self):
        clean = getattr(self, "_clean_state", None)
        return clean is not None and self._document_state() != clean

    def ask_to_save(self):
        """"save", "discard" or "cancel", asked in a box. A method of its
        own so a test can answer it without a modal event loop."""
        name = (os.path.basename(self.doc.path) if self.doc.path
                else "this figure")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(branding.APP_NAME)
        box.setText("Save the changes to {} before closing?".format(name))
        box.setInformativeText("Closing without saving loses them.")
        save = box.addButton("Save", QMessageBox.AcceptRole)
        discard = box.addButton("Close without saving",
                                QMessageBox.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        if clicked is discard:
            return "discard"
        return "cancel"

    def closeEvent(self, event):
        """Closing with unsaved changes asks first (Christian: a hotkey from
        muscle memory must not take a project with it). Save, close without
        saving, or stay; a save that is cancelled keeps the window open."""
        if self.is_modified():
            answer = self.ask_to_save()
            if answer == "cancel" or (answer == "save"
                                      and not self.save_session()):
                event.ignore()
                return
        QMainWindow.closeEvent(self, event)

    def _undo_changed(self):
        # Gizmos up for an analysis whose interval an undo just changed:
        # put them where the analysis now says it was measured.
        editing = self.plot.editing()
        if editing is not None and len(editing.cursors()) == 2:
            self.plot.measuring()["cursors"] = list(editing.cursors())
        self.refresh()

    def _selection_changed(self):
        self.outliner.sync_selection()

    def _outliner_selected(self):
        self.plot.update()

    def _set_visible(self, obj, visible):
        self.undo.set_props([(obj, "visible", bool(visible))],
                            "show" if visible else "hide")

    def _transform_done(self, changes, label):
        self.undo.set_props(changes, label)

    def _view_committed(self, before, after, label):
        """A zoom, a pan or a fit, as one undo step.

        Christian, round 9: zooming in on a feature several times should come
        back out with Ctrl+Z, one step at a time. It used to be kept off the
        stack on purpose (undo was "for the document"); in use, the framing
        is part of what a Ctrl+Z is expected to walk back.
        """
        plot = self.plot
        self.undo.push(undo.CallCommand(
            lambda: plot.restore_view(after),
            lambda: plot.restore_view(before), label))

    def undo_step(self):
        # A zoom whose fingers are still settling is finished first, so this
        # undoes IT rather than the step before (see `PlotWidget.commit_view`).
        self.plot.commit_view()
        return self.undo.undo()

    def redo_step(self):
        self.plot.commit_view()
        return self.undo.redo()

    # ------------------------------------------------------------- operators
    def _register_ops(self):
        r = self.ops.register
        any_scan = lambda c: bool(c.doc.scans)
        selected = lambda c: bool(c.doc.selected())
        scans_selected = lambda c: bool(c.doc.selected_scans())
        several = lambda c: len(c.doc.selected_scans()) >= 2

        r("file.open", "Open TRIOS files...", lambda c: c.open_files(),
          category="File", key="Ctrl+O", shortcut="Ctrl+O",
          aliases=("import", "tri", "add files"))
        r("file.session_open", "Open a session...",
          lambda c: c.open_session(), category="File", key="Ctrl+Shift+O",
          shortcut="Ctrl+Shift+O")
        r("file.session_save", "Save the session", lambda c: c.save_session(),
          category="File", key="Ctrl+S", shortcut="Ctrl+S", enabled=any_scan)
        r("file.session_save_as", "Save the session as...",
          lambda c: c.save_session(ask=True), category="File",
          key="Ctrl+Shift+S", shortcut="Ctrl+Shift+S", enabled=any_scan)
        r("file.export_image", "Export the figure...",
          lambda c: c.export_image(), category="File", key="Ctrl+E",
          shortcut="Ctrl+E", enabled=any_scan, aliases=("svg", "png", "save"))
        r("file.export_csv", "Export the curves as CSV...",
          lambda c: c.export_csv(), category="File", enabled=any_scan)
        r("file.export_driver", "Export as a DSC_Plotter.py driver...",
          lambda c: c.export_driver(), category="File", enabled=any_scan,
          aliases=("matplotlib", "script", "template"))
        # Ctrl+W closes the POP-UP in front while any is open, and the window
        # only when none is. Christian: muscle memory for "close this" must
        # not take the whole project with it.
        r("file.close", "Close the window (or the pop-up in front)",
          lambda c: c.close_step(), category="File", key="Ctrl+W",
          shortcut="Ctrl+W", aliases=("quit", "exit"))

        r("edit.undo", "Undo", lambda c: c.undo_step(), category="Edit",
          key="Ctrl+Z", shortcut="Ctrl+Z", aliases=("zoom back", "back"),
          enabled=lambda c: (c.undo.can_undo()
                             or c.plot._view_burst is not None))
        r("edit.redo", "Redo", lambda c: c.redo_step(), category="Edit",
          key="Ctrl+Y", shortcut="Ctrl+Y", extra_keys=("Ctrl+Shift+Z",),
          enabled=lambda c: c.undo.can_redo())

        r("select.all", "Select everything", lambda c: c.select_all(True),
          category="Select", key="Ctrl+A", shortcut="Ctrl+A",
          enabled=any_scan)
        r("select.none", "Select nothing", lambda c: c.select_all(False),
          category="Select", key="Alt+A", shortcut="Alt+A", enabled=selected)
        r("select.invert", "Invert the selection", lambda c: c.invert_selection(),
          category="Select", key="Ctrl+I", shortcut="Ctrl+I", enabled=any_scan)
        r("select.same_sample", "Select every scan of this sample",
          lambda c: c.select_same_sample(), category="Select",
          enabled=scans_selected)

        r("transform.grab", "Move the selection", lambda c: c.plot.start_grab(),
          category="Transform", key="G",
          shortcut="G, then a number, Enter (Esc cancels)",
          enabled=selected, aliases=("offset", "drag", "shift"))
        # Blender's S, for what is drawn on the figure and is not data: the
        # arrow, the legend, a label. Christian, round 16.
        r("transform.scale", "Scale the selection", lambda c: c.plot.start_scale(),
          category="Transform", key="S",
          shortcut="S, then move or type a factor, Enter (Esc cancels)",
          enabled=lambda c: any(c.plot.scale_fields(o)
                                for o in c.doc.selected()),
          aliases=("size", "bigger", "smaller", "resize", "grow"))
        r("arrange.stack", "Stack the selected scans evenly",
          lambda c: c.stack_selected(), category="Transform",
          enabled=several, aliases=("spread", "offset", "space out"))
        r("arrange.distribute", "Distribute the offsets evenly",
          lambda c: c.distribute_selected(), category="Transform",
          enabled=lambda c: len(c.doc.selected_scans()) >= 3)
        r("arrange.align", "Align the selection to the active scan",
          lambda c: c.align_selected(), category="Transform",
          enabled=several, aliases=("baseline", "overlay", "match"))
        # R: the selected scans' offsets back to zero; with a label or the
        # legend selected instead, Blender's rotate. Nothing selected,
        # nothing happens (Christian, round 17).
        r("arrange.reset", "Reset the offsets of the selected scans",
          lambda c: c.r_key(), category="Transform", key="R",
          shortcut="R, with scans selected",
          aliases=("unstack", "align to zero", "flatten"),
          enabled=lambda c: (any(s.offset for s in c.doc.selected_scans())
                             or c.rotatable_selected()))
        r("transform.rotate", "Rotate the selection",
          lambda c: c.plot.start_rotate(), category="Transform",
          shortcut="R, with a label or the legend selected",
          enabled=lambda c: c.rotatable_selected(),
          aliases=("turn", "angle", "rotation", "tilt"))

        # NO Return binding. A window-level QAction on Return fires BEFORE
        # the plot sees the key, so pressing Enter to confirm a measurement
        # opened the scan's settings instead - Christian spotted the
        # double-booking from the symptom. Double-click is the way in.
        r("object.settings", "Settings for the selection...",
          lambda c: c.edit_object(), category="Object",
          shortcut="double-click", enabled=selected)
        r("object.hide", "Hide the selection", lambda c: c.hide_selected(),
          category="Object", key="H", shortcut="H", enabled=selected)
        r("object.show_all", "Show everything", lambda c: c.show_all(),
          category="Object", key="Alt+H", shortcut="Alt+H",
          enabled=lambda c: any(not o.visible for o in c.doc.objects()))
        r("object.remove", "Remove the selection",
          lambda c: c.remove_selected(), category="Object", key="Delete",
          shortcut="Del",
          enabled=lambda c: bool(c.doc.selected_scans()
                                 or [o for o in c.doc.selected()
                                     if isinstance(o, (model.Analysis,
                                                       model.TextLabel))]))
        r("object.remove_file", "Remove every scan of this file",
          lambda c: c.remove_selected_files(), category="Object",
          enabled=scans_selected, aliases=("close file", "unload"))
        r("object.colour", "Colour for the selection...",
          lambda c: c.colour_selected(), category="Object",
          enabled=scans_selected)
        r("analysis.show", "Show every analysis of the selected scans",
          lambda c: c.set_analyses(True), category="Object",
          enabled=lambda c: any(s.analysis_objects
                                for s in c.doc.selected_scans()),
          aliases=("onsets", "tg", "enthalpy", "annotations"))
        r("analysis.hide", "Hide every analysis of the selected scans",
          lambda c: c.set_analyses(False), category="Object",
          enabled=lambda c: any(a.visible for s in c.doc.selected_scans()
                                for a in s.analysis_objects))
        r("sample.molar_mass", "Set the molar mass...",
          lambda c: c.ask_molar_mass(), category="Object", key="Shift+M",
          shortcut="Shift+M", enabled=scans_selected,
          aliases=("M", "g/mol", "per mole"))

        r("view.fit", "Fit the view", lambda c: c.plot.fit(),
          category="View", shortcut="F or Home", enabled=any_scan)
        # MestReNova's M: two numbers, typed straight through (Christian,
        # round 13).
        r("view.x_range", "Set the x range...", lambda c: c.ask_x_range(),
          category="View", key="M", shortcut="M", enabled=any_scan,
          aliases=("limits", "xlim", "zoom to", "from to", "range"))
        r("figure.offset_markers", "Show or hide the y-offset markers",
          lambda c: c.toggle_offset_markers(), category="Object",
          enabled=any_scan,
          aliases=("offset", "yoffset", "add_yoffset_markers", "stack"))
        r("select.offset_markers", "Select every offset marker",
          lambda c: c.select_offset_markers(), category="Select",
          enabled=lambda c: c.doc.offset_markers and bool(c.doc.scans),
          aliases=("offset", "yoffset", "markers"))
        r("view.axis_temperature", "X axis: temperature",
          lambda c: c.set_axis(model.AXIS_TEMPERATURE), category="View",
          enabled=lambda c: c.doc.x_axis != model.AXIS_TEMPERATURE)
        r("view.axis_time", "X axis: time",
          lambda c: c.set_axis(model.AXIS_TIME), category="View",
          enabled=lambda c: c.doc.x_axis != model.AXIS_TIME)
        for unit in units.UNITS:
            r("view.unit_" + unit.replace("/", "_"),
              "Y axis: {}".format(unit),
              (lambda u: lambda c: c.set_unit(u))(unit), category="View",
              enabled=(lambda u: lambda c: c.doc.y_unit != u)(unit))
        for theme in (plot_module.THEME_DARK, plot_module.THEME_LIGHT):
            r("view.theme_" + theme.replace("-", "_"),
              "Theme: {}".format(theme),
              (lambda name: lambda c: c.set_theme(name))(theme),
              category="View", aliases=("dark", "light", "colours"),
              enabled=(lambda name: lambda c: c.doc.theme != name)(theme))
        r("view.outliner", "Show or hide the outliner",
          lambda c: c._outliner_dock.setVisible(
              not c._outliner_dock.isVisible()),
          category="View", key="N", shortcut="N")

        r("measure.start", "Measure on the selected scan",
          lambda c: c.plot.start_measure(), category="Analyse", key="C",
          shortcut="C, or double-click-drag a curve",
          enabled=lambda c: len(c.doc.selected_scans()) == 1,
          aliases=("analyse", "onset", "integrate", "cursors", "tg"))
        r("measure.apply", "Analyse the interval...",
          lambda c: c.plot.measure_confirm(), category="Analyse",
          shortcut="Enter, with both cursors down",
          enabled=lambda c: bool(c.plot.measuring()
                                 and len(c.plot.measuring()["cursors"]) >= 2),
          aliases=("onset", "integrate", "glass transition", "enthalpy",
                   "compute", "run"))
        r("measure.cancel", "Stop measuring",
          lambda c: c.plot.end_measure(), category="Analyse",
          enabled=lambda c: c.plot.measuring() is not None)
        for name, unit in (("Celsius", units.TEMP_C), ("Kelvin", units.TEMP_K),
                           ("Fahrenheit", units.TEMP_F)):
            r("view.x_unit_" + unit,
              "X axis in {}".format(name),
              (lambda u: lambda c: c.set_x_unit(u))(unit), category="View",
              enabled=(lambda u: lambda c: (
                  c.doc.x_unit != u
                  and c.doc.x_axis == model.AXIS_TEMPERATURE))(unit))
        # No key: Ctrl+L belongs to the label alignment below (Christian,
        # round 10). The outliner's tick and F3 still toggle it.
        r("legend.toggle", "Show or hide the legend",
          lambda c: c.toggle_legend(), category="Object",
          aliases=("key", "which colour is which"))
        # The template's `flush` for analysis labels, on keys: which edge of
        # the text sits on its arrow.
        flushable = lambda c: bool(c.flush_targets())
        for side, key, words in (
                (style.FLUSH_LEFT, "Ctrl+L", "left"),
                (style.FLUSH_RIGHT, "Ctrl+R", "right"),
                (style.FLUSH_CENTER, "Ctrl+M", "centred")):
            r("analysis.flush_" + side,
              "Align analysis labels {}".format(words),
              (lambda f: lambda c: c.set_flush(f))(side), category="Object",
              key=key, shortcut=key, enabled=flushable,
              aliases=("flush", "alignment", "justify", words))
        r("legend.settings", "Legend settings...",
          lambda c: c.edit_object(c.doc.legend), category="Object")
        r("label.add", "Add a label...", lambda c: c.add_label(),
          category="Object", key="Ctrl+T", shortcut="Ctrl+T",
          aliases=("text", "caption", "annotate", "title"))
        for which in ("x", "y"):
            for part, words in (("spine", "axis: ticks and frame"),
                                ("numbers", "axis numbers"),
                                ("caption", "axis caption")):
                r("axis.{}_{}".format(which, part if part != "spine"
                                      else "settings"),
                  "{} {}...".format(which.upper(), words),
                  (lambda w, pt: lambda c: c.edit_object(
                      c.doc.axes[w], part=pt))(which, part),
                  category="View",
                  aliases=("ticks", "spine", "minor", "major", "frame",
                           "locator", "numbers", "caption", "label"))
        r("arrow.settings", "Heat-flow arrow settings...",
          lambda c: c.edit_object(c.doc.arrow), category="Arrow")
        r("arrow.flip", "Flip the heat-flow direction",
          lambda c: c.flip_arrow(), category="Arrow",
          aliases=("exo", "endo", "invert", "upside down"))
        r("arrow.relabel", "Say it the other way round (exo / endo)",
          lambda c: c.relabel_arrow(), category="Arrow")

        r("app.operator_search", "Search operators...",
          lambda c: c.operator_search(), category="App", key="F3",
          shortcut="F3", aliases=("command palette", "find command", "menu"))
        r("app.about", "About {}".format(branding.APP_NAME),
          lambda c: c.show_about(), category="App",
          aliases=("version", "help", "licence", "license", "credits"))
        r("figure.layout", "Figure size and margins...",
          lambda c: c.edit_figure(), category="Edit",
          aliases=("size", "aspect ratio", "width", "height", "margins",
                   "centimetres", "inches", "page", "export size", "word"))
        r("app.settings", "Settings...", lambda c: c.open_settings(),
          category="App", key="Ctrl+,", shortcut="Ctrl+,",
          aliases=("preferences", "defaults", "house style", "font size",
                   "text size", "flush", "alignment", "options"))

    def _install_shortcuts(self):
        """One QAction per keyed operator. A clash is a startup error.

        Qt does not pick a winner when two actions share a shortcut: it
        reports an ambiguous overload and fires NEITHER, which looks like a
        key that stopped working for no reason.
        """
        clashes = self.ops.duplicate_keys()
        if clashes:
            raise RuntimeError("shortcut claimed twice: {}".format(clashes))
        for op in self.ops.keyed():
            for key in ops.chord_variants(op.key) + list(op.extra_keys):
                action = QAction(op.label, self)
                action.setShortcut(QKeySequence(key))
                action.setShortcutContext(Qt.WindowShortcut)
                action.triggered.connect(
                    (lambda o: lambda _c=False: self.run_op(o.id))(op))
                self.addAction(action)

    #: The menu bar, kept short (Christian, round 9): File, Edit, a Search
    #: button and Help. Everything the old Object, Transform, View and Arrow
    #: menus held is one F3 away, filtered by the selection, which a menu
    #: cannot do.
    MENUS = (
        ("&File", ("file.open", "file.session_open", None,
                   "file.session_save", "file.session_save_as", None,
                   "file.export_image", "file.export_csv",
                   "file.export_driver", None, "file.close")),
        ("&Edit", ("edit.undo", "edit.redo", None, "select.all",
                   "select.none", "select.invert", "select.same_sample",
                   None, "figure.layout", "app.settings",
                   ("Theme", ("view.theme_blender_default",
                              "view.theme_light")))),
        ("&Help", ("app.about",)),
    )

    def _build_menus(self):
        bar = self.menuBar()
        self._menu_actions = []
        #: {title: QMenu}, kept so the menus can be reached again (a QMenu
        #: fetched back through a temporary QAction wrapper can already be
        #: gone on the Python side).
        self.menus = {}
        for title, ids in self.MENUS:
            if title == "&Help":
                # SEARCH is a button on the bar itself rather than an entry
                # inside Help: it is how everything else is reached now.
                search = bar.addAction("&Search")
                search.setToolTip("Search every operator (F3)")
                search.triggered.connect(
                    lambda _c=False: self.run_op("app.operator_search"))
                self._search_action = search
            menu = bar.addMenu(title)
            self.menus[title] = menu
            menu.aboutToShow.connect(self._sync_menu_state)
            self._fill_menu(menu, ids)

    def _fill_menu(self, menu, ids):
        """Entries by operator id; None is a separator, and a pair
        `(title, ids)` a submenu - the Theme under Edit."""
        for op_id in ids:
            if op_id is None:
                menu.addSeparator()
                continue
            if isinstance(op_id, tuple):
                submenu = menu.addMenu(op_id[0])
                self.menus[op_id[0]] = submenu
                submenu.aboutToShow.connect(self._sync_menu_state)
                self._fill_menu(submenu, op_id[1])
                continue
            op = self.ops.get(op_id)
            if op is None:
                continue
            action = menu.addAction(op.label)
            if op.key:
                action.setShortcut(QKeySequence(op.key))
                # The window-level QAction already fires this; the menu
                # entry only SHOWS the key, or Qt reports an ambiguous
                # overload and neither of them works.
                action.setShortcutVisibleInContextMenu(True)
                action.setShortcutContext(Qt.WidgetShortcut)
            if op.id.startswith("view.theme_"):
                action.setCheckable(True)
            action.triggered.connect(
                (lambda o: lambda _c=False: self.run_op(o.id))(op))
            self._menu_actions.append((action, op))

    def _sync_menu_state(self):
        for action, op in self._menu_actions:
            action.setEnabled(op.enabled(self))
            if action.isCheckable():
                # The theme in force is the ticked (and greyed) one.
                action.setChecked(not op.enabled(self))

    def run_op(self, op_id):
        op = self.ops.get(op_id)
        if op is None or not op.enabled(self):
            return False
        op.run(self)
        return True

    def popups(self):
        """This window's pop-ups that are open, most recently opened LAST.

        Every visible dialog whose parent chain leads here: the settings of
        an object, an analysis opened from a scan's settings, the settings
        page. Found from the widgets themselves rather than from a list kept
        by hand, so a new kind of pop-up cannot be forgotten.
        """
        found = []
        for widget in QApplication.topLevelWidgets():
            if (widget is self or not widget.isVisible()
                    or not isinstance(widget, QDialog)):
                continue
            parent = widget.parentWidget()
            while parent is not None and parent is not self:
                parent = parent.parentWidget()
            if parent is self:
                found.append(widget)
        tracked = [d for d in getattr(self, "_dialogs", []) if d in found]
        return [w for w in found if w not in tracked] + tracked

    def close_step(self):
        """Ctrl+W: the pop-up in front if any is open, else the window.

        The active pop-up when one has the focus, otherwise the one opened
        last. Closing a pop-up is what its own X does. Returns what closed:
        the pop-up, or None when it was the window.
        """
        popups = self.popups()
        if not popups:
            self.close()
            return None
        active = QApplication.activeWindow()
        target = active if active in popups else popups[-1]
        target.close()
        self.note.setText("Closed {}".format(target.windowTitle()))
        return target

    def operator_search(self):
        dialog = OperatorPalette(self.ops, self, self, self._last_operator)
        if dialog.exec() and dialog.chosen:
            self._last_operator = ""
            self.run_op(dialog.chosen)

    def open_settings(self):
        """The house style page. One at a time: a second copy editing the
        same defaults would only disagree with the first."""
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return existing
        dialog = SettingsDialog(self)
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        return dialog

    # ------------------------------------------------------------- the menus
    def _context_menu(self, obj, pos):
        menu = QMenu(self)
        if isinstance(obj, model.Scan):
            self._scan_menu(menu, obj)
        elif isinstance(obj, model.HeatFlowArrow):
            for op_id in ("arrow.settings", "arrow.flip", "arrow.relabel"):
                self._menu_op(menu, op_id)
            menu.addSeparator()
            hide = menu.addAction("Hide the arrow")
            hide.triggered.connect(
                lambda _c=False: self._set_visible(obj, False))
        elif isinstance(obj, model.OffsetMarker):
            many = len(self.settings_group(obj))
            act = menu.addAction(
                "Settings for the {} selected markers...".format(many + 1)
                if many else "Offset marker settings...")
            act.triggered.connect(lambda _c=False: self.edit_object(obj))
            hide = menu.addAction("Hide this marker")
            hide.triggered.connect(
                lambda _c=False: self._set_visible(obj, False))
            self._menu_op(menu, "select.offset_markers")
        elif isinstance(obj, model.Analysis):
            many = len(self.settings_group(obj))
            act = menu.addAction(
                "Settings for the {} selected analyses...".format(many + 1)
                if many else "Settings for {}...".format(obj.summary()))
            act.triggered.connect(lambda _c=False: self.edit_object(obj))
            hide = menu.addAction("Hide this analysis")
            hide.triggered.connect(
                lambda _c=False: self._set_visible(obj, False))
            scan = menu.addAction("Settings for {}...".format(
                obj.scan.display_name()))
            scan.triggered.connect(lambda _c=False: self.edit_object(obj.scan))
        elif isinstance(obj, model.Sample):
            act = menu.addAction("Sample settings for {}...".format(obj.name))
            act.triggered.connect(lambda _c=False: self.edit_sample(obj))
            gone = menu.addAction("Remove {} from the plot".format(obj.name))
            gone.triggered.connect(lambda _c=False: self.remove_sample(obj))
        else:
            for op_id in ("file.open", "view.fit", "select.all",
                          "arrange.stack"):
                self._menu_op(menu, op_id)
        if not menu.isEmpty():
            menu.exec(pos if isinstance(pos, QPoint) else QPoint(pos))

    def _scan_menu(self, menu, scan):
        """Two entries, and only two.

        Everything else a right-click used to offer is in the outliner, the
        menus or F3 already, and Christian's report was blunt: the menu that
        pops up on a curve should be small. The molar mass stays because it
        is the one thing worth reaching for without leaving the curve.
        """
        act = menu.addAction("Settings for {}...".format(scan.display_name()))
        act.triggered.connect(lambda _c=False: self.edit_object(scan))
        molar = menu.addAction("Set the molar mass...")
        molar.triggered.connect(lambda _c=False: self.ask_molar_mass([scan]))
        caption = menu.addAction("Add a label...")
        caption.triggered.connect(lambda _c=False: self.add_label(scan=scan))

    def _menu_op(self, menu, op_id):
        op = self.ops.get(op_id)
        if op is None:
            return
        action = menu.addAction(op.label
                                + ("\t" + op.key if op.key else ""))
        action.setEnabled(op.enabled(self))
        action.triggered.connect(lambda _c=False: self.run_op(op_id))

    # ------------------------------------------------------------- documents
    def open_files(self, paths=None):
        if paths is None:
            paths, _f = QFileDialog.getOpenFileNames(
                self, "Open TRIOS measurements", "",
                "TRIOS files (*.tri *.txt);;All files (*)")
        queued = self.loader.load(paths or [])
        if queued:
            self.note.setText("Reading {} file(s)...".format(queued))
        return queued

    def _loading_progress(self, done, total):
        if total and done < total:
            self.note.setText("Reading {} of {}...".format(done + 1, total))

    def _sample_loaded(self, sample):
        existing = self.doc.sample_for(sample.path)
        if existing is not None:
            self.doc.samples.remove(existing)
            for scan in list(existing.scans):
                self.doc.remove_scan(scan)
        self.doc.add_sample(sample, model.default_segments(sample))
        self.undo.clear()
        self.note.setText(loader.summary(sample))
        self.statusBar().setToolTip(sample.note or "")
        self.refresh(keep_view=False)

    def _sample_failed(self, path, message):
        self.note.setText("Could not read {}: {}".format(
            os.path.basename(path), message))

    def toggle_segment(self, sample, seg, on=True):
        """Put one segment of an open file on the plot, or take it off.

        Undoable, like everything else: the scan object is kept by the
        command, so an undo puts back the same one with its colour and its
        offset rather than a fresh copy.
        """
        existing = [s for s in sample.scans if s.seg == seg]
        if on and not existing:
            colour = model.PALETTE[len(self.doc.scans) % len(model.PALETTE)]
            scan = model.Scan(self.doc._next_id(), sample, seg, colour)
            self.undo.push(undo.CallCommand(
                lambda: self.doc.insert_scan(scan),
                lambda: self.doc.detach_scan(scan),
                "show {}".format(scan.short_program())))
        elif not on and existing:
            self.remove_scans(existing)
        self.refresh()

    def remove_scans(self, scans, label=None):
        """Take scans off the document, undoably.

        The scans themselves are held by the command, so Ctrl+Z brings the
        SAME objects back, in their old places, with their offsets, colours
        and molar masses. Christian's report: removing a file and pressing
        Ctrl+Z did nothing, because removal was outside the stack entirely.
        """
        scans = [s for s in scans if s in self.doc.scans]
        if not scans:
            return
        places = [(scan, self.doc.scans.index(scan)) for scan in scans]
        label = label or "remove {} scan(s)".format(len(scans))

        owned = {}

        def remove():
            for scan, _index in places:
                owned[id(scan)] = self.doc.labels_of_removed(scan)
                self.doc.detach_scan(scan)

        def restore():
            for scan, index in sorted(places, key=lambda pair: pair[1]):
                self.doc.insert_scan(scan, index)
                for label in owned.get(id(scan), ()):
                    if label not in self.doc.labels:
                        self.doc.labels.append(label)

        self.undo.push(undo.CallCommand(remove, restore, label))
        self.refresh()

    def remove_sample(self, sample):
        """Take a whole file off the plot, undoably."""
        self.remove_scans(list(sample.scans),
                          "remove {}".format(sample.name))

    def open_session(self, path=None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, "Open a session", "",
                "{} sessions (*{});;All files (*)".format(
                    branding.APP_NAME, branding.SESSION_EXT))
        if not path:
            return None
        try:
            doc, problems = session.load(path, loader.read_sample)
        except Exception as exc:
            self.note.setText("Could not open the session: {}".format(exc))
            return None
        self.doc = doc
        self.undo.clear()
        self.plot.set_document(doc)
        self.outliner.set_document(doc)
        self.note.setText("; ".join(problems) if problems
                          else "Opened {}".format(os.path.basename(path)))
        self.refresh(keep_view=False)
        if doc.view:
            # The framing it was saved with: a y range narrowed to show a
            # peak's label came back fitted before round 17.
            self.plot.restore_view(doc.view)
        self.mark_clean()
        return path

    def save_session(self, ask=False, path=None):
        path = path or (self.doc.path if not ask else "")
        if not path:
            path, _f = QFileDialog.getSaveFileName(
                self, "Save the session",
                "figure" + branding.SESSION_EXT,
                "{} sessions (*{})".format(branding.APP_NAME,
                                           branding.SESSION_EXT))
        if not path:
            return None
        self._sync_view()
        try:
            session.save(self.doc, path)
        except OSError as exc:
            # A slot: an exception here is an abort, not a message.
            self.note.setText("Could not save: {}".format(exc))
            self.plot.flash("NOT saved - {}".format(exc.strerror or exc))
            return None
        self.mark_clean()
        self.note.setText("Saved {}".format(os.path.basename(path)))
        # MoloM's fading confirmation: the moment of saving is the moment
        # nobody is looking at the status bar.
        self.plot.flash("Saved {}".format(os.path.basename(path)))
        return path

    # --------------------------------------------------------------- exports
    def ask_export(self):
        """The export dialog: `(path, light)`, or None if cancelled. A
        method of its own so a test can answer it without a modal loop."""
        name = (os.path.splitext(self.doc.path)[0] + ".svg"
                if self.doc.path else "dsc.svg")
        layout = self.doc.figure
        size = ("{:g} x {:g} {}, PNG at {:d} dpi".format(
            layout.width, layout.height, layout.unit, int(layout.dpi))
            if self.plot.layout_mode() == figure_module.MODE_SIZE
            else "as the window")
        dialog = ExportDialog(self, name, self._export_light, size)
        if not dialog.exec():
            return None
        return dialog.values()

    def export_image(self, path=None, light=None):
        """The figure as SVG or PNG. `light` True is dark ink on white,
        for a page; False draws it in the theme on screen."""
        if path is None:
            chosen = self.ask_export()
            if not chosen:
                return None
            path, light = chosen
            self._export_light = bool(light)
        if light is None:
            light = self._export_light
        if not path:
            return None
        # The exo direction is NOT stamped on an image (Christian, round
        # 14): whether an assumed direction is right is the user's call.
        # It is still printed, and still written into the driver.
        warnings = export.warnings_for(self.doc, exo=False)
        if os.path.splitext(path)[1].lower() == ".svg":
            self._render_svg(path, warnings, light)
        else:
            self._render_png(path, warnings, light)
        # Printed as well as stamped - all of it, the exo direction and the
        # label notes included: the blinking label in the window can be
        # looked past, so the export says it out loud.
        for line in (export.warnings_for(self.doc)
                     + export.label_notes(self.doc)):
            print("[{}] {}".format(branding.APP_NAME, line))
        self.note.setText(
            "Exported {}{}".format(os.path.basename(path),
                                   "  -  " + "; ".join(warnings)
                                   if warnings else ""))
        self.plot.flash("Exported {}".format(os.path.basename(path)))
        return path

    def export_geometry(self):
        """`(canvas_w, canvas_h, dpi, width_px, height_px)` of an export.

        A figure of exact size is exported at EXACTLY its size: width x
        height inches times its dpi, the axes box where its margins put it,
        whatever the window looks like. Otherwise the figure on screen, at
        twice the drawing resolution.
        """
        canvas_w, canvas_h = self.plot.canvas_size()
        if self.plot.layout_mode() == figure_module.MODE_SIZE:
            dpi = float(self.doc.figure.dpi)
            width_in, height_in = self.doc.figure.inches()
            return (canvas_w, canvas_h, dpi, int(round(width_in * dpi)),
                    int(round(height_in * dpi)))
        dpi = 2.0 * figure_module.DESIGN_DPI
        return (canvas_w, canvas_h, dpi,
                int(round(canvas_w * dpi / figure_module.DESIGN_DPI)),
                int(round(canvas_h * dpi / figure_module.DESIGN_DPI)))

    def _render_png(self, path, warnings, light=True):
        canvas_w, canvas_h, dpi, width_px, height_px = self.export_geometry()
        image = QImage(width_px, height_px, QImage.Format_ARGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        scale = dpi / figure_module.DESIGN_DPI
        painter.scale(scale, scale)
        try:
            with paper_palette(self.plot, light):
                image.fill(QColor(plot_module._BG) if not light
                           else QColor(255, 255, 255))
                self.plot.paint_into(painter, columns=width_px)
                self._stamp(painter, warnings)
        finally:
            painter.end()
        # The DPI goes into the file AFTER painting: Qt turns a font's point
        # size into pixels with the device's DPI, and while painting that
        # has to be the drawing's own 96. Word reads it back and places the
        # picture at its physical size.
        per_metre = int(round(dpi / 0.0254))
        image.setDotsPerMeterX(per_metre)
        image.setDotsPerMeterY(per_metre)
        image.save(path)

    def _render_svg(self, path, warnings, light=True):
        from PySide6.QtCore import QSize
        from PySide6.QtSvg import QSvgGenerator
        canvas_w, canvas_h = self.plot.canvas_size()
        generator = QSvgGenerator()
        generator.setFileName(path)
        # 96, the drawing's own resolution. The generator's default is 72,
        # which turned every point size into pixels at 72 and drew all the
        # text at three quarters of its size.
        generator.setResolution(int(figure_module.DESIGN_DPI))
        generator.setSize(QSize(int(round(canvas_w)), int(round(canvas_h))))
        generator.setViewBox(QRectF(0.0, 0.0, canvas_w, canvas_h))
        generator.setTitle("{} figure".format(branding.APP_NAME))
        generator.setDescription("; ".join(
            s.display_name() for s in self.doc.visible_scans()))
        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # The SVG writer ignores clipping; the plot marks where its clip
        # starts and ends, and `clip_svg` writes a real one in afterwards.
        self.plot._svg_clip = []
        try:
            with paper_palette(self.plot, light):
                painter.fillRect(QRectF(0.0, 0.0, canvas_w, canvas_h),
                                 QColor(255, 255, 255) if light
                                 else QColor(plot_module._BG))
                self.plot.paint_into(painter, columns=int(canvas_w * 4))
                self._stamp(painter, warnings)
        finally:
            painter.end()
            clips, self.plot._svg_clip = self.plot._svg_clip, None
        plot_module.clip_svg(path, clips)
        if self.plot.layout_mode() == figure_module.MODE_SIZE:
            width_in, height_in = self.doc.figure.inches()
            _exact_svg_size(path, width_in * 25.4, height_in * 25.4)

    def _stamp(self, painter, warnings):
        """Draw the warnings onto the figure itself.

        Christian's rule: somebody must not be able to render an image with
        misleading data by ignoring the blinking in the window. A line of red
        text on the figure travels with it, which a console message does not.
        """
        if not warnings:
            return
        painter.save()
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(200, 30, 30))
        y = 18
        for line in warnings:
            painter.drawText(14, y, line)
            y += 15
        painter.restore()

    def export_csv(self, path=None):
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Export the curves", "dsc.csv",
                "Comma-separated values (*.csv)")
        if not path:
            return None
        written = export.curves_csv(self.doc, path)
        self.note.setText("Exported {}".format(os.path.basename(path))
                          if written else "Nothing to export")
        if written:
            self.plot.flash("Exported {}".format(os.path.basename(path)))
        return written

    def export_driver(self, path=None):
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Export as a DSC_Plotter driver", "DSC_Plotter.py",
                "Python (*.py)")
        if not path:
            return None
        self.doc.view_x_hint = self.plot.view_x()
        self.doc.view_y_hint = self.plot.view_y()
        self.doc.marker_hint = self.marker_hint()
        written, kind = export.write_driver(self.doc, path)
        self.note.setText(
            "Wrote {} ({})".format(os.path.basename(written), kind))
        self.plot.flash("Wrote {}".format(os.path.basename(written)))
        return written

    def marker_hint(self):
        """`{id(marker): (celsius, yoff_label)}` as the plot draws each
        marker, for the driver: where an unplaced one lands depends on the
        view, and the template takes the label's distance as a fraction of
        the axes height."""
        rect = self.plot.plot_rect()
        hint = {}
        for scan in self.doc.scans:
            marker = scan.marker
            hint[id(marker)] = (self.plot.marker_celsius(marker),
                                -self.plot.marker_dy(marker, rect)
                                / max(1.0, rect.height()))
        return hint

    # ------------------------------------------------------------- selection
    def select_all(self, on=True):
        self.doc.select_all(on)
        self._selection_changed()
        self.plot.update()

    def invert_selection(self):
        for obj in self.doc.objects():
            obj.selected = not obj.selected
        self._selection_changed()
        self.plot.update()

    def select_same_sample(self):
        samples = {id(s.sample) for s in self.doc.selected_scans()}
        for scan in self.doc.scans:
            if id(scan.sample) in samples:
                scan.selected = True
        self._selection_changed()
        self.plot.update()

    # ------------------------------------------------------------- arranging
    def _curve_of(self, scan):
        # The KEPT part: a truncated start-up hook must not steer a stack or
        # an alignment any more than it steers the fit.
        return scan.kept_curve(self.doc.x_axis, self.doc.y_unit,
                          self.doc.exo, self.doc.x_unit)

    def stack_selected(self):
        scans = self.doc.selected_scans() or self.doc.visible_scans()
        step = arrange.suggested_step(scans, self._curve_of)
        if not step:
            return
        first = min((s.offset for s in scans), default=0.0)
        self.undo.set_props(arrange.stack(scans, step, first), "stack")

    def distribute_selected(self):
        self.undo.set_props(arrange.distribute(self.doc.selected_scans()),
                            "distribute")

    def align_selected(self):
        scans = self.doc.selected_scans()
        if len(scans) < 2:
            return
        # The ACTIVE scan is the first selected one, which is the one the
        # eye starts on and the one the outliner lists first.
        self.undo.set_props(
            arrange.align_to(scans[0], scans[1:], self._curve_of), "align")

    def reset_offsets(self):
        """The selected scans back on zero - only those. With nothing
        selected this does nothing: resetting every offset of a stack
        because nothing was picked was one keystroke from losing it."""
        scans = self.doc.selected_scans()
        if not scans:
            return None
        return self.undo.set_props([(s, "offset", 0.0) for s in scans],
                                   "reset offsets")

    def rotatable_selected(self):
        return any(self.plot.can_transform("rotate", o)
                   for o in self.doc.selected())

    def r_key(self):
        """R: scans selected, their offsets to zero; otherwise a selected
        label or legend is rotated (the arrow is not: its direction is what
        it says)."""
        if self.doc.selected_scans():
            return self.reset_offsets()
        if self.rotatable_selected():
            return self.plot.start_rotate()
        return None

    # --------------------------------------------------------------- objects
    def settings_group(self, obj):
        """The other selected objects a settings dialog on `obj` edits too:
        the ones of its own kind, when `obj` is part of the selection."""
        if obj is None or not getattr(obj, "selected", False):
            return []
        return [o for o in self.doc.selected()
                if o is not obj and type(o) is type(obj)]

    def edit_object(self, obj=None, part=None):
        """The settings of `obj` (the selection's first without one). An
        axis has three: `part` "spine" (ticks), "numbers" or "caption" -
        what was double-clicked, when not given."""
        if obj is None:
            chosen = self.doc.selected()
            obj = chosen[0] if chosen else None
        if isinstance(obj, model.Sample):
            return self.edit_sample(obj)
        group = self.settings_group(obj)
        if isinstance(obj, model.Scan):
            dialog = ScanSettings(self, obj, self.doc.y_unit,
                                  on_change=self._live_change)
        elif isinstance(obj, model.Axis):
            # Three windows (Christian, round 18): the SPINE opens the
            # ticks, the NUMBERS their size and format, the CAPTION the
            # caption. Which was double-clicked is what the plot picked.
            part = part or self.plot.axis_hit() or "spine"
            kind = {"caption": CaptionSettings,
                    "numbers": NumberSettings}.get(part, AxisSettings)
            dialog = kind(self, obj, self.doc, on_change=self._live_change)
        elif isinstance(obj, model.TextLabel):
            dialog = LabelSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.Legend):
            dialog = LegendSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.Analysis):
            dialog = AnalysisSettings(self, obj, on_change=self._live_change)
            if self.plot.editing() is obj and not group:
                # Its gizmos are up: the dialog opens BESIDE them, and
                # closing it - any way - confirms the interval and ends them.
                avoid = self.plot.gizmo_rect()
                if avoid is not None:
                    self.place_beside(dialog, avoid)
                self._editing = (obj, dialog)
                dialog.finished.connect(
                    lambda _result, a=obj: self._editing_closed(a))
        elif isinstance(obj, model.HeatFlowArrow):
            dialog = ArrowSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.OffsetMarker):
            dialog = OffsetMarkerSettings(self, obj,
                                          on_change=self._live_change)
        else:
            return None
        if group:
            dialog.set_group(group)
            self.note.setText("Settings for {} objects: what they share is "
                              "set for all of them".format(len(group) + 1))
        self._run_live_dialog(dialog, obj, "settings")
        return obj

    def _measure_ready(self, scan, x0, x1, editing, span=None):
        """Two cursors are down: ask what to compute, then compute it.

        From the double-click-drag this runs the moment the button comes up,
        so the analysis is finished by the time the list closes - nothing is
        left to confirm. Cancelling the list drops that interval entirely:
        the gesture is one movement, and redoing it is cheaper than tidying
        up after it. Cursors placed with `C` are kept on a cancel instead,
        so Esc still steps back through them one at a time.
        """
        measuring = self.plot.measuring() or {}
        if editing is not None:
            # An analysis that already exists keeps ITS model: adjusting an
            # interval is not a chance to change what is being measured, and
            # being asked again every time is the annoyance.
            return self.remeasure(editing, x0, x1, span)
        chosen = self.ask_analysis(x0, x1)
        if not chosen:
            if measuring.get("gesture"):
                self.plot.end_measure()
            return None
        analysis = measure.run(chosen, scan, x0, x1, span=span)
        if analysis is None:
            self.note.setText(
                "{} could not be computed between those cursors".format(
                    chosen))
            if measuring.get("gesture"):
                self.plot.end_measure()
            return None

        def undo_it():
            if analysis in scan.analysis_objects:
                scan.analysis_objects.remove(analysis)

        def redo_it():
            if analysis not in scan.analysis_objects:
                scan.analysis_objects.append(analysis)

        self.undo.push(undo.CallCommand(
            redo_it, undo_it, "measure {}".format(analysis.model_name)))
        self.plot.end_measure()
        self.note.setText("{}: {}".format(analysis.model_name,
                                          analysis.summary()))
        self.refresh()
        return analysis

    def remeasure(self, analysis, x0, x1, span=None):
        """Move an analysis made here to a new interval, IN PLACE.

        The same object, with new result fields: its styling stays, and so
        does everything holding it - the open settings dialog, the outliner
        row, the selection. It used to be replaced by a fresh object, which
        left an open dialog editing an analysis no longer in the figure, and
        kept the old label, number and all. A default label is rewritten
        with the new number; one somebody typed is kept (`measure.relabelled`).

        The gizmos stay up while the analysis's settings are open (they are
        how the interval is adjusted) and go when they are not.
        """
        fields = measure.compute(analysis.model_name, analysis.scan, x0, x1,
                                 span)
        if not fields:
            self.note.setText(
                "{} could not be computed between those cursors".format(
                    analysis.model_name))
            return None
        old_label = analysis.label
        new_label = measure.relabelled(analysis, fields)
        changes = [(analysis, "fields", fields),
                   (analysis, "span", measure.clean_span(span))]
        if new_label != old_label:
            changes.append((analysis, "label", new_label))
        changes.extend(self._now_measured_here(analysis))
        self.undo.set_props(changes, "re-measure {}".format(
            analysis.model_name))
        dialog = self._editing_dialog(analysis)
        if dialog is not None:
            dialog.adopt_measurement(old_label, new_label)
        elif self.plot.editing() is analysis:
            self.plot.end_measure()
        self.note.setText("{}: {}".format(analysis.model_name,
                                          analysis.summary(self.doc)))
        return analysis

    @staticmethod
    def _now_measured_here(analysis):
        """A file's analysis recomputed here is the panel's from now on:
        its numbers no longer come from TRIOS, and the session must store
        how to make it again."""
        if analysis.source == "panel":
            return []
        return [(analysis, "source", "panel"),
                (analysis, "attribution", "measured here")]

    def retype_interval(self, analysis, start, end):
        """The interval typed in the settings, in degC: recompute there.

        On an analysis measured along the curve the typed temperature is
        found by WALKING the segment from where that cursor was, so it
        stays on the same branch of a curve that doubles back; otherwise
        the temperatures are the interval. One undo step, like a gizmo
        drag. Returns the analysis, or None when it cannot be computed.
        """
        scan = analysis.scan
        span = analysis.span
        if span:
            temperature = scan.temperature()
            lo, hi = scan.kept_range(len(temperature))
            first = measure.walk_to(temperature, span[0], start, lo, hi)
            last = measure.walk_to(temperature, span[1], end, lo, hi)
            span = (first, last) if first != last else None
            if span is not None:
                start = float(temperature[first])
                end = float(temperature[last])
        low, high = sorted((start, end))
        done = self.remeasure(analysis, low, high, span)
        if done is not None and self.plot.editing() is analysis:
            self.plot.set_measure_cursors([low, high], span)
        return done

    def change_model(self, analysis, name):
        """Make `analysis` another kind (onset -> endset, ...) on the same
        interval, IN PLACE and as one undo step. False when it cannot be
        computed there, or has no interval to compute on."""
        cursors = analysis.cursors()
        if len(cursors) != 2:
            self.note.setText("This analysis has no interval to recompute on")
            return False
        fields = measure.compute(name, analysis.scan, cursors[0], cursors[1],
                                 analysis.span)
        if not fields:
            self.note.setText("{} could not be computed on that "
                              "interval".format(name))
            return False
        model_name = fields.get("Model", name)
        changes = [(analysis, "model_name", model_name),
                   (analysis, "name", model_name),
                   (analysis, "fields", fields)]
        changes.extend(self._now_measured_here(analysis))
        self.undo.set_props(changes, "make it {}".format(model_name))
        self.note.setText("{}: {}".format(model_name,
                                          analysis.summary(self.doc)))
        return True

    def _editing_dialog(self, analysis):
        """The open settings dialog that owns this analysis's gizmos."""
        editing = getattr(self, "_editing", None)
        if editing is None or editing[0] is not analysis:
            return None
        return editing[1] if editing[1].isVisible() else None

    def _editing_closed(self, analysis):
        """Its settings closed - by OK, Cancel or the window's X: confirm.

        Christian: the gizmos exist only while the settings are open. An
        interval moved and not yet confirmed is taken now, and the gizmos go.
        """
        self._editing = None
        state = self.plot.measuring()
        if state is None or state.get("editing") is not analysis:
            return
        cursors = sorted(float(c) for c in state["cursors"])
        stored = sorted(analysis.cursors())
        span = measure.clean_span(state.get("span"))
        if len(cursors) == 2 and (span != analysis.span or len(stored) != 2
                                  or any(abs(a - b) > 1e-6
                                         for a, b in zip(cursors, stored))):
            self.remeasure(analysis, cursors[0], cursors[1], span)
        self.plot.end_measure()

    def place_beside(self, dialog, avoid):
        """Move `dialog` next to - never over - `avoid`, a global rect.

        The side with more room on the screen, top-aligned with the plot, and
        pulled back on screen if it does not fit. Its frame is not known
        before it is shown, so a margin stands in for the title bar.
        """
        from PySide6.QtGui import QGuiApplication
        dialog.adjustSize()
        width = dialog.width() + 16
        height = dialog.height() + 40
        screen = (QGuiApplication.screenAt(avoid.center())
                  or self.screen() or QGuiApplication.primaryScreen())
        area = screen.availableGeometry()
        room_left = avoid.left() - area.left()
        room_right = area.right() - avoid.right()
        if room_right >= width + 12 or room_right >= room_left:
            x = avoid.right() + 12
        else:
            x = avoid.left() - 12 - width
        x = max(area.left(), min(x, area.right() - width))
        y = max(area.top(), min(avoid.top(), area.bottom() - height))
        dialog.move(x, y)
        return QPoint(x, y)

    def ask_analysis(self, x0, x1):
        """Which analysis to run between two temperatures, or None.

        The quick list opens WHERE THE POINTER IS - the button just came up
        over the curve, and a list in the middle of the window is a trip
        across the screen for every analysis. Kept a method of its own so a
        test can answer it without reaching a modal event loop.
        """
        unit = units.TEMPERATURE_LABEL.get(self.doc.x_unit, self.doc.x_unit)
        low, high = sorted((self.plot.to_axis(x0), self.plot.to_axis(x1)))
        dialog = MeasurePalette(measure.MODELS, self)
        dialog.setWindowTitle("Analyse {:.1f} - {:.1f} {}".format(low, high,
                                                               unit))
        dialog.place_at(QCursor.pos())
        if not dialog.exec() or not dialog.chosen:
            return None
        return dialog.chosen

    def set_x_unit(self, unit):
        """Draw the x axis in Celsius, Kelvin or Fahrenheit.

        A display conversion only: the data, the stored analyses and anything
        measured here all stay in the file's own Celsius, so switching back
        and forth cannot drift.
        """
        self.doc.x_unit = unit
        for scan in self.doc.scans:
            scan._cache_key = None
        self.refresh(keep_view=False)
        self.note.setText("X axis in {}".format(
            units.TEMPERATURE_LABEL.get(unit, unit)))

    def flush_targets(self):
        """The analyses Ctrl+L / Ctrl+R / Ctrl+M act on.

        The selected analyses; with none selected, every analysis shown on
        the selected scans, so one key lines up all the labels of a curve.
        """
        chosen = [obj for obj in self.doc.selected()
                  if isinstance(obj, model.Analysis)]
        if chosen:
            return chosen
        return [analysis for scan in self.doc.selected_scans()
                for analysis in scan.visible_analyses()]

    def set_flush(self, side):
        """Align analysis labels left, right or centred on their arrows,
        as one undo step."""
        targets = self.flush_targets()
        if not targets:
            self.note.setText("Select an analysis label (or its scan) first")
            return 0
        self.undo.set_props([(a, "flush", side) for a in targets],
                            "align labels")
        self.note.setText("{} label(s) aligned {}".format(
            len(targets), style.FLUSH_TITLES.get(side, side)))
        return len(targets)

    # --------------------------------------------------------------- x range
    def x_range_dialog(self):
        """The `M` pop-up, filled with the range on screen (not shown)."""
        lo, hi = self.plot.view_x()
        if self.doc.x_axis == model.AXIS_TEMPERATURE:
            unit = units.TEMPERATURE_LABEL.get(self.doc.x_unit, "")
        else:
            unit = "min"
        return RangeDialog("X range", unit, lo, hi, self)

    def ask_x_range(self):
        dialog = self.x_range_dialog()
        if not dialog.exec():
            return None
        return self.set_x_range(*dialog.values())

    def set_x_range(self, lo, hi):
        """Frame x from `lo` to `hi` (axis units), as one undo step."""
        if not hi > lo:
            return None
        self.plot.commit_view()
        self.plot._view_begin("x range")
        self.plot.set_view_x(lo, hi)
        self.plot.commit_view()
        self.note.setText("x from {:g} to {:g}".format(lo, hi))
        return (lo, hi)

    # ---------------------------------------------------- y-offset markers
    def toggle_offset_markers(self):
        """The template's `add_yoffset_markers`, on or off. Undoable."""
        shown = not self.doc.offset_markers
        self.undo.set_props([(self.doc, "offset_markers", shown)],
                            "y-offset markers")
        self.note.setText("Y-offset markers {}".format(
            "shown" if shown else "hidden"))

    def select_offset_markers(self):
        """Every drawn scan's marker, so they can be moved or styled as one."""
        self.doc.select_only([s.marker for s in self.doc.visible_scans()])
        self._selection_changed()
        self.plot.update()

    def toggle_legend(self):
        """Put the key on the figure, or take it off. Undoable like the rest."""
        legend = self.doc.legend
        self.undo.set_props([(legend, "visible", not legend.visible)],
                            "legend")
        self.note.setText("Legend {}".format(
            "shown" if legend.visible else "hidden"))

    def add_label(self, text=None, at=None, scan=None):
        """Put a caption on the figure, undoably.

        Placed where the cursor is, or in the middle when there is no cursor
        (F3, a menu). It is an object from the moment it exists: draggable,
        editable, selectable, saved with the session.
        """
        from PySide6.QtWidgets import QInputDialog as _Input
        if text is None:
            text, ok = _Input.getText(self, "Add a label", "Text:")
            if not ok or not text.strip():
                return None
            text = text.strip()
        rect = self.plot.plot_rect()
        cursor = at or self.plot._cursor
        if cursor is not None:
            x = (cursor.x() - rect.left()) / max(1.0, rect.width())
            y = (cursor.y() - rect.top()) / max(1.0, rect.height())
        else:
            x = y = 0.5
        label = model.TextLabel(self.doc._next_id(), text,
                                min(0.98, max(0.02, x)),
                                min(0.98, max(0.02, y)), scan)
        self.undo.push(undo.CallCommand(
            lambda: self.doc.labels.append(label),
            lambda: self.doc.remove_label(label),
            "add a label"))
        self.refresh()
        return label

    def edit_figure(self):
        """This session's figure size and margins (`core/figure.py`)."""
        dialog = FigureSettings(self, self.doc.figure, plot=self.plot,
                                on_change=self._live_change)
        self._run_live_dialog(dialog, self.doc.figure, "figure size")
        return dialog

    def edit_sample(self, sample):
        dialog = SampleSettings(self, sample, on_change=self._live_change)
        self._run_live_dialog(dialog, sample, "sample settings")
        return sample

    def _run_live_dialog(self, dialog, obj, label):
        """Show a live dialog and turn what it did into ONE undo step.

        The dialog has already written to the object a dozen times by the
        time OK is pressed, so the changes are read back, the object is put
        back the way it was, and the undo stack applies them again. That is
        the only way a live dialog and an undo stack can both be honest.

        SHOWN, not `exec`ed: these are non-modal, so the plot stays live
        underneath and the undo step is built when the dialog finishes rather
        than when this function returns. The reference is kept, or Python
        collects the dialog the moment this returns.
        """
        before = dialog.snapshot()
        extra_before = None
        if isinstance(obj, model.Scan):
            extra_before = obj.sample.molar_mass
        self._dialogs = [d for d in getattr(self, "_dialogs", [])
                         if d.isVisible()]
        self._dialogs.append(dialog)
        dialog.finished.connect(
            lambda result, d=dialog: self._live_dialog_done(
                d, obj, label, before, extra_before, result))
        dialog.show()
        dialog.raise_()
        return dialog

    def _live_dialog_done(self, dialog, obj, label, before, extra_before,
                          result):
        if not result:
            self._live_change()
            return
        # The dialog's snapshot as it is NOW: a re-measure while it was open
        # moves the "before" label on with the number (`adopt_measurement`),
        # so the settings step does not undo the label back to an old value.
        changes = []
        for target, before in dialog.snapshots():
            for name, old in before.items():
                new = getattr(target, name)
                if new != old:
                    setattr(target, name, old)
                    changes.append((target, name, new))
        if isinstance(obj, model.Scan):
            new = obj.sample.molar_mass
            if new != extra_before:
                obj.sample.molar_mass = extra_before
                changes.append((obj.sample, "molar_mass", new))
        if changes:
            self.undo.set_props(changes, label)
        else:
            self.refresh()

    def _live_change(self):
        for scan in self.doc.scans:
            scan._cache_key = None
        self.refresh()

    def set_analyses(self, on):
        """Switch every analysis of the selected scans on or off at once.

        The per-analysis boxes are in the outliner and in the scan's
        settings; this is the "all of them" shortcut, for the scan that has
        one onset and one integration worth showing.
        """
        changes = []
        for scan in self.doc.selected_scans():
            for analysis in scan.analysis_objects:
                # One offered "by step name" is attributed by being shown on
                # ITS scan; "all of them" would put it on every scan whose
                # step has that name.
                if on and analysis.attribution == "by step name":
                    continue
                changes.append((analysis, "visible", bool(on)))
        self.undo.set_props(changes,
                            "show analyses" if on else "hide analyses")

    def hide_selected(self):
        objs = [o for o in self.doc.selected() if o.visible]
        self.undo.set_props([(o, "visible", False) for o in objs], "hide")

    def show_all(self):
        objs = [o for o in self.doc.objects() if not o.visible]
        self.undo.set_props([(o, "visible", True) for o in objs], "show all")

    def remove_selected(self):
        """Delete: whatever is selected, in the order it makes sense.

        An analysis or a caption goes on its own - deleting the scan under a
        selected analysis would be a surprise - and only a selection of scans
        removes scans.
        """
        analyses = [o for o in self.doc.selected()
                    if isinstance(o, model.Analysis)]
        labels = [o for o in self.doc.selected()
                  if isinstance(o, model.TextLabel)]
        if analyses or labels:
            self.remove_analyses(analyses, labels)
            return
        self.remove_scans(self.doc.selected_scans())

    def remove_analyses(self, analyses=(), labels=()):
        """Take analyses and captions off the figure, undoably."""
        places = [(a, a.scan, a.scan.analysis_objects.index(a))
                  for a in analyses if a in a.scan.analysis_objects]
        label_places = [(lb, self.doc.labels.index(lb)) for lb in labels
                        if lb in self.doc.labels]
        if not places and not label_places:
            return

        def remove():
            for analysis, scan, _index in places:
                if analysis in scan.analysis_objects:
                    scan.analysis_objects.remove(analysis)
            for label, _index in label_places:
                self.doc.remove_label(label)

        def restore():
            for analysis, scan, index in places:
                if analysis not in scan.analysis_objects:
                    scan.analysis_objects.insert(
                        min(index, len(scan.analysis_objects)), analysis)
            for label, index in sorted(label_places, key=lambda p: p[1]):
                if label not in self.doc.labels:
                    self.doc.labels.insert(
                        min(index, len(self.doc.labels)), label)

        count = len(places) + len(label_places)
        self.undo.push(undo.CallCommand(
            remove, restore, "remove {} object(s)".format(count)))
        self.refresh()

    def remove_selected_files(self):
        samples = []
        for scan in self.doc.selected_scans():
            if scan.sample not in samples:
                samples.append(scan.sample)
        scans = [s for sample in samples for s in sample.scans]
        self.remove_scans(scans, "remove {} file(s)".format(len(samples)))

    def colour_selected(self):
        scans = self.doc.selected_scans()
        if not scans:
            return
        colour = QColorDialog.getColor(QColor(scans[0].colour), self,
                                       "Colour for the selection")
        if not colour.isValid():
            return
        self.undo.set_props([(s, "colour", colour.name()) for s in scans],
                            "colour")

    def ask_molar_mass(self, scans=None):
        scans = scans or self.doc.selected_scans()
        if not scans:
            return None
        samples = []
        for scan in scans:
            if scan.sample not in samples:
                samples.append(scan.sample)
        current = samples[0].molar_mass or 0.0
        value, ok = QInputDialog.getDouble(
            self, "Molar mass",
            "Molar mass in g/mol for {}:".format(
                ", ".join(s.name for s in samples)),
            float(current), 0.0, 1e7, 4)
        if not ok:
            return None
        self.undo.set_props(
            [(s, "molar_mass", float(value) if value > 0 else None)
             for s in samples], "molar mass")
        return value

    # ----------------------------------------------------------------- views
    def set_theme(self, name):
        """Switch the palette, and remember it on the document. The windows
        around the plot follow it (`ui/appearance.py`)."""
        self.doc.theme = plot_module.set_theme(name)
        appearance.apply(self.doc.theme)
        self.plot.invalidate()
        self.outliner.refill()             # its scan colours follow the theme
        self.note.setText("Theme: {}".format(self.doc.theme))

    def about_text(self):
        """What Help > About says: the version, what it is running on, and
        where the pieces came from. Separate from showing it, so a test can
        read it without a modal box."""
        import platform
        import PySide6
        from PySide6.QtCore import qVersion
        from .. import __version__
        return (
            "<p><b>{name}</b> {version}<br>{what}</p>"
            "<p>TRIOS reader: {reader}<br>"
            "Python {python} &nbsp;/&nbsp; PySide6 {pyside} &nbsp;/&nbsp; "
            "Qt {qt}</p>"
            "<p>Your defaults: {prefs}</p>"
            "<p>{copyright}<br><a href=\"{repo}\">{repo}</a></p>").format(
                name=branding.APP_NAME, version=__version__,
                what=branding.DESCRIPTION,
                reader=loader.reader_origin(),
                python=platform.python_version(),
                pyside=PySide6.__version__, qt=qVersion(),
                prefs=style.preferences_path(),
                copyright=branding.COPYRIGHT, repo=branding.REPOSITORY)

    def show_about(self):
        QMessageBox.about(self, "About {}".format(branding.APP_NAME),
                          self.about_text())

    def set_axis(self, axis):
        self.doc.x_axis = axis
        for scan in self.doc.scans:
            scan._cache_key = None
        self.refresh(keep_view=False)

    def set_unit(self, unit):
        changes = self.doc.set_unit(unit)
        for scan in self.doc.scans:
            scan._cache_key = None
        if changes:
            self.undo.set_props(changes, "unit")
        self.refresh(keep_view=False)

    def flip_arrow(self):
        arrow = self.doc.arrow
        other = (units.EXO_UP if arrow.direction == units.EXO_DOWN
                 else units.EXO_DOWN)
        self.undo.set_props([(arrow, "direction", other)], "flip the arrow")

    def relabel_arrow(self):
        """Say the same thing the other way round: exo down becomes endo up.

        The figure does not change - that is the point. Christian asked for
        both labels to exist; `units.orientation` is what keeps relabelling
        from flipping the data when it should not.
        """
        arrow = self.doc.arrow
        word = (units.WORD_ENDO if arrow.word == units.WORD_EXO
                else units.WORD_EXO)
        direction = (units.EXO_UP if arrow.direction == units.EXO_DOWN
                     else units.EXO_DOWN)
        self.undo.set_props([(arrow, "word", word),
                             (arrow, "direction", direction)], "relabel")

    # ------------------------------------------------------- drag and drop
    def dragEnterEvent(self, event):
        if self._dropped(event) :
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self._dropped(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        sessions = [p for p in paths
                    if p.lower().endswith(branding.SESSION_EXT)]
        if sessions:
            self.open_session(sessions[0])
            return
        self.open_files(paths)

    @staticmethod
    def _dropped(event):
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        out = []
        for url in mime.urls():
            path = url.toLocalFile()
            if not path:
                continue
            if (loader.looks_readable(path)
                    or path.lower().endswith(branding.SESSION_EXT)):
                out.append(path)
        return out


def _exact_svg_size(path, width_mm, height_mm):
    """Write an SVG's physical size to the hundredth of a micrometre.

    The generator takes a size in WHOLE pixels at its resolution, so it can
    only say "84.67 mm" to the nearest quarter millimetre; the root element's
    width and height are rewritten with the exact values, and the viewBox
    (the drawing's own units) is left as it is.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    head = re.search(r"<svg\b[^>]*>", text)
    if head is None:
        return False
    tag = head.group(0)
    tag = re.sub(r'\swidth="[^"]*"',
                 lambda _m: ' width="{:.4f}mm"'.format(width_mm), tag, count=1)
    tag = re.sub(r'\sheight="[^"]*"',
                 lambda _m: ' height="{:.4f}mm"'.format(height_mm), tag,
                 count=1)
    text = text[:head.start()] + tag + text[head.end():]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return True

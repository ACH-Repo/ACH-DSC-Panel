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

import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (QAction, QColor, QCursor, QImage, QKeySequence,
                           QPainter)
from PySide6.QtWidgets import (QApplication, QColorDialog, QDockWidget,
                               QFileDialog, QInputDialog, QLabel, QMainWindow,
                               QMenu, QMessageBox, QWidget)

from .. import branding
from ..core import (arrange, export, loader, measure, model, ops, session,
                    style, undo, units)
from .dialogs import (AnalysisSettings, ArrowSettings, AxisSettings,
                      CaptionSettings, LabelSettings, LegendSettings,
                      SampleSettings, ScanSettings)
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
        self.setWindowTitle(branding.window_title(subject))

    def _undo_changed(self):
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
        r("file.close", "Close the window", lambda c: c.close(),
          category="File", key="Ctrl+W", shortcut="Ctrl+W")

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
        r("arrange.stack", "Stack the selected scans evenly",
          lambda c: c.stack_selected(), category="Transform",
          enabled=several, aliases=("spread", "offset", "space out"))
        r("arrange.distribute", "Distribute the offsets evenly",
          lambda c: c.distribute_selected(), category="Transform",
          enabled=lambda c: len(c.doc.selected_scans()) >= 3)
        r("arrange.align", "Align the selection to the active scan",
          lambda c: c.align_selected(), category="Transform",
          enabled=several, aliases=("baseline", "overlay", "match"))
        r("arrange.reset", "Reset the offsets to zero",
          lambda c: c.reset_offsets(), category="Transform", key="R",
          shortcut="R", aliases=("unstack", "align to zero", "flatten"),
          enabled=lambda c: any(s.offset for s in c.doc.scans))

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
        r("legend.toggle", "Show or hide the legend",
          lambda c: c.toggle_legend(), category="Object", key="Ctrl+L",
          shortcut="Ctrl+L", aliases=("key", "which colour is which"))
        r("legend.settings", "Legend settings...",
          lambda c: c.edit_object(c.doc.legend), category="Object")
        r("label.add", "Add a label...", lambda c: c.add_label(),
          category="Object", key="Ctrl+T", shortcut="Ctrl+T",
          aliases=("text", "caption", "annotate", "title"))
        r("axis.x_settings", "X axis settings...",
          lambda c: c.edit_object(c.doc.axes["x"]), category="View")
        r("axis.y_settings", "Y axis settings...",
          lambda c: c.edit_object(c.doc.axes["y"]), category="View")
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
                   None, "app.settings")),
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
            for op_id in ids:
                if op_id is None:
                    menu.addSeparator()
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
                action.triggered.connect(
                    (lambda o: lambda _c=False: self.run_op(o.id))(op))
                self._menu_actions.append((action, op))

    def _sync_menu_state(self):
        for action, op in self._menu_actions:
            action.setEnabled(op.enabled(self))

    def run_op(self, op_id):
        op = self.ops.get(op_id)
        if op is None or not op.enabled(self):
            return False
        op.run(self)
        return True

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
        elif isinstance(obj, model.Analysis):
            act = menu.addAction("Settings for {}...".format(obj.summary()))
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
        try:
            session.save(self.doc, path)
        except OSError as exc:
            # A slot: an exception here is an abort, not a message.
            self.note.setText("Could not save: {}".format(exc))
            self.plot.flash("NOT saved - {}".format(exc.strerror or exc))
            return None
        self._sync_title()
        self.note.setText("Saved {}".format(os.path.basename(path)))
        # MoloM's fading confirmation: the moment of saving is the moment
        # nobody is looking at the status bar.
        self.plot.flash("Saved {}".format(os.path.basename(path)))
        return path

    # --------------------------------------------------------------- exports
    def export_image(self, path=None):
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Export the figure", "dsc.svg",
                "SVG image (*.svg);;PNG image (*.png)")
        if not path:
            return None
        warnings = export.warnings_for(self.doc)
        if os.path.splitext(path)[1].lower() == ".svg":
            self._render_svg(path, warnings)
        else:
            self._render_png(path, warnings)
        for line in warnings:
            # Printed as well as stamped: the blinking label in the window
            # can be looked past, so the export says it out loud.
            print("[{}] {}".format(branding.APP_NAME, line))
        self.note.setText(
            "Exported {}{}".format(os.path.basename(path),
                                   "  -  " + "; ".join(warnings)
                                   if warnings else ""))
        self.plot.flash("Exported {}".format(os.path.basename(path)))
        return path

    def _render_png(self, path, warnings):
        ratio = 2.0
        image = QImage(int(self.plot.width() * ratio),
                       int(self.plot.height() * ratio),
                       QImage.Format_ARGB32)
        image.setDevicePixelRatio(ratio)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            with paper_palette(self.plot, True):
                self.plot.paint_into(painter,
                                     columns=int(self.plot.width() * ratio))
                self._stamp(painter, warnings)
        finally:
            painter.end()
        image.save(path)

    def _render_svg(self, path, warnings):
        from PySide6.QtSvg import QSvgGenerator
        from PySide6.QtCore import QRect
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(self.plot.size())
        generator.setViewBox(QRect(0, 0, self.plot.width(),
                                   self.plot.height()))
        generator.setTitle("{} figure".format(branding.APP_NAME))
        generator.setDescription("; ".join(
            s.display_name() for s in self.doc.visible_scans()))
        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            with paper_palette(self.plot, True):
                painter.fillRect(0, 0, self.plot.width(), self.plot.height(),
                                 QColor(255, 255, 255))
                self.plot.paint_into(painter,
                                     columns=self.plot.width() * 4)
                self._stamp(painter, warnings)
        finally:
            painter.end()

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
        written, kind = export.write_driver(self.doc, path)
        self.note.setText(
            "Wrote {} ({})".format(os.path.basename(written), kind))
        self.plot.flash("Wrote {}".format(os.path.basename(written)))
        return written

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
        return scan.curve(self.doc.x_axis, self.doc.y_unit,
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
        """R: put the selected scans back on zero, or all of them.

        The selection first, because that is what R means with something
        picked; everything when nothing is selected, which is the "undo my
        stacking" gesture.
        """
        scans = self.doc.selected_scans() or self.doc.scans
        self.undo.set_props([(s, "offset", 0.0) for s in scans],
                            "reset offsets")

    # --------------------------------------------------------------- objects
    def edit_object(self, obj=None):
        if obj is None:
            chosen = self.doc.selected()
            obj = chosen[0] if chosen else None
        if isinstance(obj, model.Sample):
            return self.edit_sample(obj)
        if isinstance(obj, model.Scan):
            dialog = ScanSettings(self, obj, self.doc.y_unit,
                                  on_change=self._live_change)
        elif isinstance(obj, model.Axis):
            # The SPINE opens the axis; the CAPTION opens the caption. Which
            # one was double-clicked is what the plot just picked.
            if self.plot.axis_hit() == "caption":
                dialog = CaptionSettings(self, obj, self.doc,
                                         on_change=self._live_change)
            else:
                dialog = AxisSettings(self, obj, self.doc,
                                      on_change=self._live_change)
        elif isinstance(obj, model.TextLabel):
            dialog = LabelSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.Legend):
            dialog = LegendSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.Analysis):
            dialog = AnalysisSettings(self, obj, on_change=self._live_change)
        elif isinstance(obj, model.HeatFlowArrow):
            dialog = ArrowSettings(self, obj, on_change=self._live_change)
        else:
            return None
        self._run_live_dialog(dialog, obj, "settings")
        return obj

    def _measure_ready(self, scan, x0, x1, editing):
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
            chosen = editing.model_name
        else:
            chosen = self.ask_analysis(x0, x1)
            if not chosen:
                if measuring.get("gesture"):
                    self.plot.end_measure()
                return None
        analysis = measure.run(chosen, scan, x0, x1)
        if analysis is None:
            self.note.setText(
                "{} could not be computed between those cursors".format(
                    chosen))
            if measuring.get("gesture"):
                self.plot.end_measure()
            return None
        old = editing
        if old is not None and old in old.scan.analysis_objects:
            # Adjusting an existing one: the new analysis takes its place and
            # its appearance, so a re-measure does not restyle the figure.
            analysis.colour = old.colour
            analysis.label = old.label
            analysis.label_dy = old.label_dy
            analysis.label_size = old.label_size
            analysis.flush = old.flush
            analysis.show_interval = old.show_interval
            analysis.shade = old.shade
            old.scan.analysis_objects.remove(old)

        def undo_it():
            if analysis in scan.analysis_objects:
                scan.analysis_objects.remove(analysis)
            if old is not None and old not in old.scan.analysis_objects:
                old.scan.analysis_objects.append(old)

        def redo_it():
            if analysis not in scan.analysis_objects:
                scan.analysis_objects.append(analysis)
            if old is not None and old in old.scan.analysis_objects:
                old.scan.analysis_objects.remove(old)

        self.undo.push(undo.CallCommand(
            redo_it, undo_it,
            "{} {}".format("re-measure" if old is not None else "measure",
                           analysis.model_name)))
        self.plot.end_measure()
        self.note.setText("{}: {}".format(analysis.model_name,
                                          analysis.summary()))
        self.refresh()
        return analysis

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
        changes = []
        for name, old in before.items():
            new = getattr(obj, name)
            if new != old:
                setattr(obj, name, old)
                changes.append((obj, name, new))
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

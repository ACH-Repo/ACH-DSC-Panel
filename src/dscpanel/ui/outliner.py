"""The outliner: every object in the figure, and what state it is in.

Once scans can be hidden, dragged anywhere and given a molar mass one at a
time, the plot alone stops being able to say what is in the figure - a hidden
scan is invisible by definition, and "which of these eight is still waiting
for its M" is not a question a curve can answer. So there is a list, as in
Blender and as in MoloM.

It is a TREE because the data is one: a sample is a file with a mass, a molar
mass and an exotherm direction, and its scans are the segments of it. Putting
the molar mass on the sample row rather than on every scan is the difference
between typing it once and typing it seven times.

Selection is shared with the plot in both directions: clicking a row selects
the curve, and clicking a curve highlights the row.

Two parts, with a line between them (Christian, round 22): the DATA on top -
each file, its segments, and under each scan what belongs to that trace (its
analyses, its own labels, its offset marker while the markers are shown) -
and below the line the DECORATORS, everything drawn on the figure that
belongs to no trace: the heat-flow arrow, the legend, free labels, pictures
and structures.

A label row can be DRAGGED onto a scan (or anything under one) to give the
label to that scan - parenting, round 23 - and onto the Decorators to free
it again. The window does the work (`MainWindow.parent_labels`).
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QStyle,
                               QStyledItemDelegate, QTreeWidget,
                               QTreeWidgetItem)

from ..core import model
from . import plot as plot_module

_ALARM = QColor(232, 76, 76)
_DIM = QColor(150, 150, 150)

#: The keys of the two rows that are not objects.
SEPARATOR = ("separator", 0)
DECORATORS = ("decorators", 0)


class _Rows(QStyledItemDelegate):
    """Every row as usual, except the separator, which is a line - and the
    row a dragged label would be dropped on, which is framed."""

    def paint(self, painter, option, index):
        if index.data(Qt.UserRole) != SEPARATOR:
            QStyledItemDelegate.paint(self, painter, option, index)
            tree = self.parent()
            target = getattr(tree, "_drop_item", None)
            if (target is not None and index.column() == 0
                    and index == tree.indexFromItem(target, 0)):
                painter.save()
                painter.setPen(QPen(option.palette.color(QPalette.Highlight),
                                    2))
                painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
                painter.restore()
            return
        painter.save()
        painter.setPen(QPen(option.palette.color(QPalette.Mid), 1))
        y = option.rect.center().y()
        painter.drawLine(option.rect.left() + 2, y, option.rect.right() - 6, y)
        painter.restore()


def first_line(text, limit=60):
    """A label's text as one row: its first line, and a mark if there is
    more (a label runs over several lines since round 20)."""
    lines = str(text).strip().splitlines() or [""]
    head = lines[0].strip()
    if len(lines) > 1:
        head += " ..."
    return head[:limit]


def decorators(doc):
    """What goes under Decorators, in order: the arrow, the legend, free
    labels, pictures, structures."""
    if doc is None:
        return []
    return ([doc.arrow, doc.legend]
            + [label for label in doc.labels if label.scan is None]
            + list(doc.images) + list(doc.structures))


class Outliner(QTreeWidget):
    """The data (files, scans, what hangs on each scan), then a line, then
    the decorators."""

    #: The user ticked or unticked something: (object, visible).
    visibility_changed = Signal(object, bool)
    #: A segment that was not on the plot was ticked: (sample, seg, on).
    segment_toggled = Signal(object, int, bool)
    selection_picked = Signal()
    activated_object = Signal(object)
    menu_for = Signal(object, object)          # object, global QPoint
    #: A sweep across the boxes began / ended: what it changes between the
    #: two is ONE undo step.
    sweep_started = Signal()
    sweep_finished = Signal()
    #: Label rows were dropped: (labels, the scan to give them to, or None
    #: to free them).
    parent_requested = Signal(object, object)

    def __init__(self, parent=None):
        QTreeWidget.__init__(self, parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Object", "State"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        # The names take the room there is and the state column is always
        # whole: it used to sit past a fixed 230-pixel first column, cut off
        # however wide the dock was (Christian, round 18).
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(40)
        self.setItemDelegate(_Rows(self))
        self.headerItem().setToolTip(0, "The figure's objects; tick to show.")
        self.headerItem().setToolTip(1, "Mass, molar mass, exotherm, "
                                        "offset, analyses shown.")
        self.doc = None
        self._filling = False
        #: While a sweep is live, the state it paints onto every box it
        #: passes (ORCA Workbench's, Blender's), else None.
        self._sweep = None
        # Label rows drag onto scans. The tree never moves its own rows:
        # a drop is a request to the window, and the rows are rebuilt.
        # Copy, not Move: after a MOVE, Qt deletes the dragged rows itself.
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setDropIndicatorShown(False)
        #: The row a drag is over and would drop on, framed by `_Rows`.
        self._drop_item = None
        self.itemChanged.connect(self._item_changed)
        self.itemSelectionChanged.connect(self._selection_changed)
        self.itemDoubleClicked.connect(self._double_clicked)
        self.customContextMenuRequested.connect(self._menu)

    # ----------------------------------------------------------------- fill
    def set_document(self, doc):
        self.doc = doc
        self.refill()

    def refill(self):
        """Rebuild the tree. Cheap: a figure has tens of rows, not thousands.

        Never re-entrant: `clear()` deletes the rows, and deleting a row from
        inside a signal that row is emitting is a use-after-free in Qt, not a
        Python error - the program simply disappears.
        """
        doc = self.doc
        if self._filling:
            return
        self._filling = True
        try:
            # A file or the Decorators is open unless it was CLOSED by hand;
            # a scan is closed unless it was opened. "Open unless anything
            # was open before" folded every new file away once the
            # Decorators existed on an empty figure.
            expanded = {self._key(item) for item in self._items()
                        if item.isExpanded()}
            collapsed = {self._key(item) for item in self._items()
                         if item.childCount() and not item.isExpanded()}
            self.clear()
            if doc is None:
                return
            for sample in doc.samples:
                row = QTreeWidgetItem(self)
                row.setText(0, sample.name)
                row.setText(1, self._sample_state(sample))
                row.setData(0, Qt.UserRole, ("sample", id(sample)))
                row.setFirstColumnSpanned(False)
                font = QFont(self.font())
                font.setBold(True)
                row.setFont(0, font)
                if sample.exo_source == "assumed":
                    row.setForeground(1, QBrush(_DIM))
                # EVERY segment of the file, not only the ones being drawn.
                # A run holds seven, and comparing the second or third
                # up-scan is routine, so the ones that are not shown yet have
                # to be reachable - they are the unticked rows.
                shown = {scan.seg: scan for scan in doc.scans
                         if scan.sample is sample}
                for seg in range(sample.segment_count()):
                    scan = shown.get(seg)
                    if scan is not None:
                        self._add_scan(row, scan)
                    else:
                        self._add_segment(row, sample, seg)
                row.setExpanded(("sample", id(sample)) not in collapsed)
                for k in range(row.childCount()):
                    child = row.child(k)
                    child.setExpanded(self._key(child) in expanded)
            if doc.samples:
                line = QTreeWidgetItem(self)
                line.setData(0, Qt.UserRole, SEPARATOR)
                line.setFlags(Qt.NoItemFlags)
                line.setFirstColumnSpanned(True)
            group = QTreeWidgetItem(self)
            group.setText(0, "Decorators")
            group.setData(0, Qt.UserRole, DECORATORS)
            font = QFont(self.font())
            font.setBold(True)
            group.setFont(0, font)
            group.setToolTip(0, "Drawn on the figure, belonging to no scan")
            for obj in decorators(doc):
                self._add_decorator(group, obj)
            group.setExpanded(DECORATORS not in collapsed)
            self._drop_item = None
            for item in self._items():
                for column in (0, 1):
                    if item.text(column):
                        item.setToolTip(column, item.text(column))
                # Only a label is dragged anywhere.
                key = self._key(item)
                if not key or key[0] != "label":
                    item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
        finally:
            self._filling = False

    def _add_decorator(self, parent, obj):
        """One row under Decorators: a name, and what it is."""
        if isinstance(obj, model.TextLabel):
            return self._add_label_row(parent, obj)
        item = QTreeWidgetItem(parent)
        if isinstance(obj, model.HeatFlowArrow):
            name, state = obj.name, "{} {}".format(obj.word, obj.direction)
        elif isinstance(obj, model.Legend):
            name = obj.name
            state = "{} entries".format(len(obj.entries(self.doc)))
        elif isinstance(obj, model.ImageArtist):
            number = self.doc.images.index(obj) + 1
            name = ("Picture {}".format(number) if len(self.doc.images) > 1
                    else "Picture")
            state = "picture"
        else:                            # a MoleculeArtist
            name, state = (obj.smiles or obj.name), "structure"
        item.setText(0, name)
        item.setText(1, state)
        if isinstance(obj, (model.ImageArtist, model.MoleculeArtist)):
            item.setForeground(1, QBrush(_DIM))
        item.setData(0, Qt.UserRole, (obj.kind, id(obj)))
        item.setCheckState(0, Qt.Checked if obj.visible else Qt.Unchecked)
        item.setSelected(obj.selected)
        return item

    def _add_scan(self, parent, scan):
        item = QTreeWidgetItem(parent)
        item.setText(0, scan.display_name())
        item.setData(0, Qt.UserRole, ("scan", id(scan)))
        item.setCheckState(0, Qt.Checked if scan.visible else Qt.Unchecked)
        # The plot's colour for it, which on the light theme is the same
        # hue darkened to read on white (`plot.for_light`).
        colour = (plot_module.for_light(scan.colour)
                  if plot_module.THEME == plot_module.THEME_LIGHT
                  else QColor(scan.colour))
        item.setForeground(0, QBrush(colour))
        state = []
        missing = (scan.missing_for(self.doc.y_unit, self.doc.x_axis)
                   if self.doc else None)
        if missing:
            state.append("NO {}".format(missing.upper()))
            item.setForeground(1, QBrush(_ALARM))
        if scan.offset:
            state.append("{:+.4g}".format(scan.offset))
        analyses = scan.analysis_objects
        if analyses:
            state.append("{}/{} analyses".format(
                len(scan.visible_analyses()), len(analyses)))
        item.setText(1, "  ".join(state))
        item.setSelected(scan.selected)
        # The analyses hang under their scan, each with its own box. This is
        # the "switch that one on" Christian asked for, and it is also where
        # an uncertain attribution is visible without opening anything.
        for analysis in analyses:
            self._add_analysis(item, analysis)
        for label in (self.doc.labels_for(scan) if self.doc else ()):
            self._add_label_row(item, label)
        if self.doc is not None and self.doc.offset_markers:
            self._add_marker_row(item, scan.marker)
        if scan.has_weight():
            self._add_weight_row(item, scan.weight)
        return item

    def _add_weight_row(self, parent, weight):
        """An SDT or TGA run's weight curve, against the second y axis: what
        stops it being drawn, in the alarm colour, like a scan's row; under
        it the file's analyses made on the weight, listed and not drawn."""
        item = QTreeWidgetItem(parent)
        item.setText(0, "Weight")
        item.setData(0, Qt.UserRole, ("weight", id(weight)))
        item.setCheckState(0, Qt.Checked if weight.visible else Qt.Unchecked)
        doc = self.doc
        unit = getattr(doc, "weight_unit", model.WEIGHT_PCT)
        missing = (weight.scan.weight_missing_for(unit, doc.x_axis)
                   if doc is not None else None)
        if missing:
            item.setText(1, "NO {}".format(missing.upper()))
            item.setForeground(1, QBrush(_ALARM))
        else:
            item.setText(1, "{} axis".format(unit))
            item.setForeground(1, QBrush(_DIM))
        item.setSelected(weight.selected)
        for analysis in weight.scan.weight_analyses:
            row = QTreeWidgetItem(item)
            row.setText(0, analysis.summary())
            row.setText(1, model.WEIGHT_ANALYSIS_NOTE)
            row.setForeground(1, QBrush(_DIM))
            # A key of its own shape, which `_object` knows nothing of: not
            # an object to select, show or open (the two-shape trap).
            row.setData(0, Qt.UserRole, ("weight_analysis", id(analysis)))
            row.setFlags(Qt.ItemIsEnabled)
            row.setToolTip(0, "Made in TRIOS on the weight curve. The "
                           "panel does not draw analyses on the weight yet.")
        return item

    def _add_marker_row(self, parent, marker):
        """The scan's offset marker, while the figure's markers are shown -
        it is only an object then (`Document.objects`)."""
        item = QTreeWidgetItem(parent)
        item.setText(0, marker.name)
        item.setData(0, Qt.UserRole, ("offset_marker", id(marker)))
        item.setCheckState(0, Qt.Checked if marker.visible else Qt.Unchecked)
        item.setText(1, "marker")
        item.setForeground(1, QBrush(_DIM))
        item.setSelected(marker.selected)
        return item

    def _add_label_row(self, parent, label):
        item = QTreeWidgetItem(parent)
        item.setText(0, first_line(label.text))
        item.setData(0, Qt.UserRole, ("label", id(label)))
        item.setCheckState(0, Qt.Checked if label.visible else Qt.Unchecked)
        item.setText(1, "note" if label.leader else "label")
        item.setForeground(1, QBrush(_DIM))
        item.setSelected(label.selected)
        return item

    def _add_analysis(self, parent, analysis):
        item = QTreeWidgetItem(parent)
        item.setText(0, analysis.summary())
        item.setData(0, Qt.UserRole, ("analysis", id(analysis)))
        item.setCheckState(0, Qt.Checked if analysis.visible else Qt.Unchecked)
        item.setSelected(analysis.selected)
        if not analysis.certain:
            item.setText(1, analysis.attribution)
            item.setForeground(1, QBrush(_DIM))
        elif not analysis.decoded:
            item.setText(1, "cursors only")
            item.setForeground(1, QBrush(_DIM))
        return item

    def _add_segment(self, parent, sample, seg):
        """A segment of the file that is not being drawn: tick it to add it.

        Named with the same `short_program` the drawn ones use, through a
        throwaway `Scan`, so "#3 heat 10 K/min" reads the same whether it is
        on the plot or waiting to be put there.
        """
        item = QTreeWidgetItem(parent)
        item.setText(0, model.Scan(0, sample, seg, "#888888").short_program())
        item.setData(0, Qt.UserRole, ("segment", id(sample), seg))
        item.setCheckState(0, Qt.Unchecked)
        item.setForeground(0, QBrush(_DIM))
        item.setText(1, "not shown")
        item.setForeground(1, QBrush(_DIM))
        return item

    def _sample_state(self, sample):
        bits = []
        bits.append("{:g} mg".format(sample.mass_g * 1000.0)
                    if sample.mass_g else "no mass")
        bits.append("M {:g}".format(sample.molar_mass) if sample.molar_mass
                    else "no M")
        bits.append("exo {}{}".format(
            sample.exo, "?" if sample.exo_source == "assumed" else ""))
        return "  ".join(bits)

    # --------------------------------------------------- sweeping the boxes
    # Press a box and drag down the list: every box the pointer passes takes
    # the state the first one was given - as in ORCA Workbench and Blender.
    # A tap-and-drag on a touchpad and a double-click-drag both start one.
    def _on_box(self, item, pos):
        """True when `pos` is on the tick box of `item`."""
        if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
            return False
        cell = self.visualItemRect(item)
        left = self.visualRect(self.indexFromItem(item, 0)).left()
        width = self.style().pixelMetric(QStyle.PM_IndicatorWidth) + 8
        return cell.top() <= pos.y() <= cell.bottom() and \
            left - 2 <= pos.x() <= left + width

    def _start_sweep(self, item):
        self._sweep = (Qt.Unchecked if item.checkState(0) == Qt.Checked
                       else Qt.Checked)
        self.sweep_started.emit()
        item.setCheckState(0, self._sweep)

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        item = self.itemAt(pos)
        if ev.button() == Qt.LeftButton and self._on_box(item, pos):
            self._start_sweep(item)
            ev.accept()
            return
        QTreeWidget.mousePressEvent(self, ev)

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position().toPoint()
        item = self.itemAt(pos)
        if ev.button() == Qt.LeftButton and self._on_box(item, pos):
            # The second press of a double-click on a box is a box press,
            # not "open the settings".
            if self._sweep is None:
                self._start_sweep(item)
            ev.accept()
            return
        QTreeWidget.mouseDoubleClickEvent(self, ev)

    def mouseMoveEvent(self, ev):
        if self._sweep is not None:
            item = self.itemAt(ev.position().toPoint())
            if (item is not None and item.flags() & Qt.ItemIsUserCheckable
                    and item.checkState(0) != self._sweep):
                item.setCheckState(0, self._sweep)
            ev.accept()
            return
        QTreeWidget.mouseMoveEvent(self, ev)

    def mouseReleaseEvent(self, ev):
        if self._sweep is not None:
            self._sweep = None
            # After the changes the sweep queued (they are deferred by a
            # zero timer, `_item_changed`), so they land inside the step.
            QTimer.singleShot(0, self.sweep_finished.emit)
            ev.accept()
            return
        QTreeWidget.mouseReleaseEvent(self, ev)

    # ------------------------------------------------ dragging labels over
    def dragged_labels(self):
        """The labels among the selected rows: what a drag carries."""
        out = []
        for item in self.selectedItems():
            obj = self._object(item)
            if isinstance(obj, model.TextLabel):
                out.append(obj)
        return out

    def drop_target(self, item):
        """`(True, scan)` for a row that gives a label to `scan` - the
        scan's own row or anything under it - `(True, None)` for the
        Decorators and what is under them (free the label), and
        `(False, None)` for anywhere else."""
        while item is not None:
            key = self._key(item)
            if key == DECORATORS:
                return True, None
            obj = self._object(item)
            if isinstance(obj, model.Scan):
                return True, obj
            item = item.parent()
        return False, None

    def drop_labels_on(self, item):
        """Hand the dragged labels to what `item` stands for. True when it
        was somewhere a label can go. The window is told after the drop has
        finished, since it rebuilds these rows."""
        ok, scan = self.drop_target(item)
        labels = self.dragged_labels()
        if not ok or not labels:
            return False
        QTimer.singleShot(0, lambda: self.parent_requested.emit(labels, scan))
        return True

    def _mark_drop(self, item):
        if item is not self._drop_item:
            self._drop_item = item
            self.viewport().update()

    def dragEnterEvent(self, ev):
        if ev.source() is self and self.dragged_labels():
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            return
        ev.ignore()

    def dragMoveEvent(self, ev):
        # The base class scrolls near the edges; whether the drop is
        # allowed is decided here.
        QTreeWidget.dragMoveEvent(self, ev)
        item = self.itemAt(ev.position().toPoint())
        ok, _scan = self.drop_target(item)
        if ev.source() is self and ok and self.dragged_labels():
            self._mark_drop(item)
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
        else:
            self._mark_drop(None)
            ev.ignore()

    def dragLeaveEvent(self, ev):
        self._mark_drop(None)
        QTreeWidget.dragLeaveEvent(self, ev)

    def dropEvent(self, ev):
        """Never the base class's: it would move the rows themselves."""
        item = self.itemAt(ev.position().toPoint())
        self._mark_drop(None)
        if ev.source() is self and self.drop_labels_on(item):
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
        else:
            ev.ignore()

    # ------------------------------------------------------------- plumbing
    def _items(self):
        out = []

        def walk(item):
            out.append(item)
            for k in range(item.childCount()):
                walk(item.child(k))

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        return out

    @staticmethod
    def _key(item):
        return item.data(0, Qt.UserRole)

    def _segment_of(self, item):
        """`(sample, seg)` for an unticked segment row, else None."""
        key = self._key(item)
        if not key or key[0] != "segment" or self.doc is None:
            return None
        for sample in self.doc.samples:
            if id(sample) == key[1]:
                return sample, key[2]
        return None

    def _object(self, item):
        doc = self.doc
        if doc is None or item is None:
            return None
        key = self._key(item)
        if not key:
            return None
        kind, ident = key[0], key[1]
        if kind in ("segment", "separator", "decorators"):
            return None                # not an object (a segment: not yet)
        if kind == "legend":
            return doc.legend
        if kind == "arrow":
            return doc.arrow
        if kind in ("image", "molecule"):
            for obj in (doc.images if kind == "image" else doc.structures):
                if id(obj) == ident:
                    return obj
        if kind == "offset_marker":
            for scan in doc.scans:
                if id(scan.marker) == ident:
                    return scan.marker
        if kind == "weight":
            for scan in doc.scans:
                if id(scan.weight) == ident:
                    return scan.weight
        if kind == "scan":
            for scan in doc.scans:
                if id(scan) == ident:
                    return scan
        if kind == "analysis":
            for analysis in doc.analyses():
                if id(analysis) == ident:
                    return analysis
        if kind == "label":
            for label in doc.labels:
                if id(label) == ident:
                    return label
        if kind == "sample":
            for sample in doc.samples:
                if id(sample) == ident:
                    return sample
        return None

    def sync_selection(self):
        """Follow the document's selection, without echoing it back."""
        self._filling = True
        try:
            for item in self._items():
                obj = self._object(item)
                item.setSelected(bool(getattr(obj, "selected", False)))
        finally:
            self._filling = False

    def _item_changed(self, item, column):
        """A box was ticked. Tell the window - but not until Qt has finished.

        **Deferred by a zero timer on purpose.** Acting at once means the
        window rebuilds this tree while Qt is still inside the click that
        ticked the box, so `clear()` deletes the very item the view is
        holding, and the program vanishes without a traceback. Christian hit
        exactly that: hide the only visible scan, then tick another segment.

        A zero-delay `singleShot` runs as soon as the event loop is free,
        which is after the click is finished and before anything is drawn.
        """
        if self._filling or column != 0:
            return
        wanted = item.checkState(0) == Qt.Checked
        segment = self._segment_of(item)
        if segment is not None:
            # An unticked segment becomes a scan when it is ticked. Ticking
            # it back off goes through the scan row, not this one.
            if wanted:
                sample, seg = segment
                QTimer.singleShot(0, lambda: self.segment_toggled.emit(
                    sample, seg, True))
            return
        obj = self._object(item)
        if obj is None or not hasattr(obj, "visible"):
            return
        if bool(obj.visible) != wanted:
            QTimer.singleShot(0, lambda: self.visibility_changed.emit(
                obj, wanted))

    def _selection_changed(self):
        if self._filling or self.doc is None:
            return
        chosen = []
        for item in self.selectedItems():
            obj = self._object(item)
            if isinstance(obj, model.Obj):
                chosen.append(obj)
            elif isinstance(obj, model.Sample):
                chosen.extend(obj.scans)
            elif self._key(item) == DECORATORS:
                chosen.extend(decorators(self.doc))
        self.doc.select_only(chosen)
        self.selection_picked.emit()

    def _double_clicked(self, item, _column):
        obj = self._object(item)
        if obj is not None:
            # Deferred for the same reason as `_item_changed`: the settings
            # dialog is modal, and opening one inside a click that is about
            # to rebuild these rows is the same trap.
            QTimer.singleShot(0, lambda: self.activated_object.emit(obj))

    def _menu(self, pos):
        item = self.itemAt(pos)
        self.menu_for.emit(self._object(item), self.viewport().mapToGlobal(pos))

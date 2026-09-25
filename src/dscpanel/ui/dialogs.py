"""Per-object settings, applied as they are touched.

Live-apply with a snapshot for Cancel, which is the PXRD window's rule and
the right one for anything judged by eye: a dialog you have to close before
you can see what it did makes a knob unusable. Cancel puts back what was
there when the dialog opened, because by then the object has already been
changed a dozen times.

`NumberBox` is MoloM's, for the same reason it exists there: Christian is on
a German locale, where Qt's decimal separator is a comma, so a typed "0.15"
is not a number and the box quietly keeps its old value. Both forms are taken
and the typed text is left alone while it is being typed.
"""

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

from ..core import model as units_module
from ..core import style
from ..core import units


class NumberBox(QDoubleSpinBox):
    """A spin box that reads "1.5" and "1,5" alike, and commits on Enter."""

    def __init__(self, parent=None):
        QDoubleSpinBox.__init__(self, parent)
        locale = QLocale(QLocale.C)
        locale.setNumberOptions(QLocale.OmitGroupSeparator)
        self.setLocale(locale)
        self.setKeyboardTracking(False)

    @staticmethod
    def _normalise(text):
        return str(text).strip().replace(",", ".")

    def validate(self, text, pos):
        state, _fixed, position = QDoubleSpinBox.validate(
            self, self._normalise(text), pos)
        return state, text, position

    def valueFromText(self, text):
        return QDoubleSpinBox.valueFromText(self, self._normalise(text))


class StyleNumber(QWidget):
    """A size that is either chosen HERE or taken from the house style.

    It always shows the value that is DRAWN. While it follows the default the
    box says "(default)" and the button is greyed; typing a number makes the
    size this object's own, and "Default" hands it back to the house style
    (`core/style.py`). `value()` is None for "follow", which is exactly what
    the object stores.
    """

    changed = Signal()

    def __init__(self, setting, own, inherited, parent=None,
                 reset_text="Default"):
        QWidget.__init__(self, parent)
        self.setting = setting
        self._own = own
        #: A callable, so the box follows a default that changes while it is
        #: open - the settings page edits the defaults live.
        self._inherited = inherited
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.box = NumberBox(self)
        self.box.setDecimals(setting.decimals)
        self.box.setRange(float(setting.low), float(setting.high))
        self.box.setSingleStep(float(setting.step))
        self.reset = QPushButton(reset_text, self)
        self.reset.setToolTip(
            "Follow the house style again (Edit > Settings), instead of a "
            "value chosen for this one.")
        row.addWidget(self.box, 1)
        row.addWidget(self.reset, 0)
        self._show()
        self.box.valueChanged.connect(self._typed)
        self.reset.clicked.connect(lambda _c=False: self._follow())

    def value(self):
        return self._own

    def refresh(self):
        """Show the inherited value again - the default under it changed."""
        self._show()

    def _show(self):
        shown = self._own if self._own is not None else self._inherited()
        self.box.blockSignals(True)
        self.box.setSuffix("" if self._own is not None else "  (default)")
        self.box.setValue(float(shown))
        self.box.blockSignals(False)
        self.reset.setEnabled(self._own is not None)

    def _typed(self, value):
        self._own = float(value)
        self._show()
        self.changed.emit()

    def _follow(self):
        self._own = None
        self._show()
        self.changed.emit()


class StyleChoice(QWidget):
    """A choice (the label alignment) that may follow the house style.

    The first entry is "default (...)", naming what that currently means, and
    stands for None; the rest are the choices themselves.
    """

    changed = Signal()

    def __init__(self, choices, own, describe_default, parent=None,
                 titles=None, allow_default=True):
        QWidget.__init__(self, parent)
        self._describe = describe_default
        self._allow_default = allow_default
        titles = titles or {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(self)
        if allow_default:
            self.combo.addItem("", None)
        for choice in choices:
            self.combo.addItem(titles.get(choice, choice), choice)
        row.addWidget(self.combo, 1)
        self.refresh()
        index = self.combo.findData(own) if own is not None else 0
        self.combo.setCurrentIndex(max(0, index))
        self.combo.currentIndexChanged.connect(
            lambda _i=0: self.changed.emit())

    def value(self):
        return self.combo.currentData()

    def set_value(self, value):
        index = self.combo.findData(value)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def refresh(self):
        if self._allow_default:
            self.combo.setItemText(0, "default ({})".format(self._describe()))


def _document_of(widget):
    """The document a dialog is about, from whichever window it belongs to.

    Needed for the figure's own style, which sits between an object and the
    user's defaults. None outside a window, which skips that level.
    """
    while widget is not None:
        doc = getattr(widget, "doc", None)
        if isinstance(doc, units_module.Document):
            return doc
        widget = widget.parentWidget()
    return None


def _style_number(dialog, obj, attr, reset_text="Default"):
    """The size field for `obj.attr`, following the house style."""
    setting = style.BY_KEY[style.key_for(obj, attr)]
    return StyleNumber(setting, getattr(obj, attr),
                       lambda: style.inherited(dialog.doc, obj, attr),
                       parent=dialog, reset_text=reset_text)


class ArtistTransform(QWidget):
    """The position block every artist gets: where it is, and from which point.

    One widget rather than the same four rows copied into each artist's
    dialog, because the position is a property of being an ARTIST - see
    `core.model.Artist`. `space` decides what the two numbers mean: a
    fraction of the plot, which keeps a caption in its corner whatever the
    view does, or the axes' own units, which pins it to a temperature. The
    numbers are CONVERTED when the space changes, so switching never moves
    anything.
    """

    def __init__(self, artist, plot, on_change=None, parent=None):
        QWidget.__init__(self, parent)
        self.artist = artist
        self.plot = plot
        self.on_change = on_change
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        self.space = QComboBox()
        self.space.addItem("fraction of the plot (0 to 1)",
                           units_module.SPACE_RELATIVE)
        self.space.addItem("the axes' own units", units_module.SPACE_DATA)
        self.space.setCurrentIndex(
            0 if artist.space == units_module.SPACE_RELATIVE else 1)
        form.addRow("Position in", self.space)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.x = NumberBox()
        self.y = NumberBox()
        for box in (self.x, self.y):
            box.setDecimals(4)
            box.setRange(-1e9, 1e9)
            box.setSingleStep(0.01)
            row_layout.addWidget(box)
        self.x.setValue(float(artist.x))
        self.y.setValue(float(artist.y))
        form.addRow("x, y", row)

        self.anchor = QComboBox()
        for name in units_module.ANCHORS:
            self.anchor.addItem(name, name)
        index = self.anchor.findData(artist.anchor)
        self.anchor.setCurrentIndex(max(0, index))
        self.anchor.setToolTip(
            "Which point of the artist sits on the position above.")
        form.addRow("Anchor", self.anchor)

        self.space.currentIndexChanged.connect(self._space_changed)
        self.x.valueChanged.connect(self._apply)
        self.y.valueChanged.connect(self._apply)
        self.anchor.currentIndexChanged.connect(self._apply)

    def _space_changed(self, _index=0):
        """Convert the stored position so the artist does not jump."""
        wanted = self.space.currentData()
        if wanted != self.artist.space and self.plot is not None:
            self.plot.convert_artist_space(self.artist, wanted)
        self.x.blockSignals(True)
        self.y.blockSignals(True)
        self.x.setValue(float(self.artist.x))
        self.y.setValue(float(self.artist.y))
        self.x.blockSignals(False)
        self.y.blockSignals(False)
        self._apply()

    def _apply(self, *_args):
        self.artist.space = self.space.currentData()
        self.artist.anchor = self.anchor.currentData()
        self.artist.x = float(self.x.value())
        self.artist.y = float(self.y.value())
        if self.on_change is not None:
            self.on_change()


class _LiveDialog(QDialog):
    """Common machinery: snapshot on open, restore on reject."""

    #: Attribute names this dialog edits, for the snapshot.
    FIELDS = ()

    def __init__(self, parent, obj, on_change=None):
        QDialog.__init__(self, parent)
        self.obj = obj
        self.on_change = on_change
        self.doc = _document_of(parent)
        self._snapshot = {name: getattr(obj, name) for name in self.FIELDS}
        # NOT MODAL. These dialogs apply as they are touched and are meant to
        # be worked beside: a dialog that blocks the plot blocks the
        # measurement cursors it is describing, which is exactly what
        # Christian hit when adjusting an analysis. `Qt.Tool` keeps it above
        # the window it belongs to without taking the focus away from it.
        self.setModal(False)
        self.setWindowFlag(Qt.Tool, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def _live(self, *_args):
        if self.on_change is not None:
            self.on_change()

    def reject(self):
        for name, value in self._snapshot.items():
            setattr(self.obj, name, value)
        self._live()
        QDialog.reject(self)

    def snapshot(self):
        """What the object looked like when this opened, for the undo step."""
        return dict(self._snapshot)


def _colour_button(parent, get_colour, set_colour):
    button = QPushButton(parent)
    button.setFixedWidth(64)

    def refresh():
        colour = QColor(get_colour())
        button.setStyleSheet(
            "background: {}; border: 1px solid #555;".format(colour.name()))

    def pick():
        colour = QColorDialog.getColor(QColor(get_colour()), parent,
                                       "Pick a colour")
        if colour.isValid():
            set_colour(colour.name())
            refresh()

    button.clicked.connect(lambda _c=False: pick())
    refresh()
    return button


class ScanSettings(_LiveDialog):
    """Everything about one scan, plus its sample's molar mass."""

    FIELDS = ("colour", "label", "offset", "line_width",
              "molar_mass_override")

    def __init__(self, parent, scan, unit, on_change=None):
        _LiveDialog.__init__(self, parent, scan, on_change)
        self.setWindowTitle("Settings for {}".format(scan.display_name()))
        self._sample_molar_mass = scan.sample.molar_mass
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.label = QLineEdit(scan.label or "")
        self.label.setPlaceholderText(scan.display_name())
        form.addRow("Label", self.label)

        form.addRow("Colour", _colour_button(
            self, lambda: scan.colour, self._set_colour))

        self.offset = NumberBox()
        self.offset.setDecimals(6)
        self.offset.setRange(-1e9, 1e9)
        self.offset.setValue(float(scan.offset))
        self.offset.setSuffix(" " + unit)
        form.addRow("Offset", self.offset)

        self.width = _style_number(self, scan, "line_width")
        form.addRow("Line width", self.width)

        # The analyses, one box each, off unless ticked. A run carries a
        # dozen and a figure wants one or two, so the list is the dialogue
        # rather than a single "show them all" switch. Double-click opens an
        # analysis's own settings.
        self.analyses = QListWidget(self)
        self.analyses.setMaximumHeight(120)
        for analysis in scan.analysis_objects:
            entry = QListWidgetItem(self._analysis_text(analysis))
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Checked if analysis.visible
                                else Qt.Unchecked)
            entry.setData(Qt.UserRole, analysis)
            self.analyses.addItem(entry)
        if not scan.analysis_objects:
            self.analyses.addItem("no analyses in the file for this scan")
            self.analyses.setEnabled(False)
        form.addRow("Analyses", self.analyses)

        # ------------------------------------------------- the molar mass
        mass = scan.sample.mass_g
        form.addRow("Sample mass", QLabel(
            "{:g} mg (from the file)".format(mass * 1000.0) if mass
            else "not in the file"))

        self.molar = NumberBox()
        self.molar.setDecimals(4)
        self.molar.setRange(0.0, 1e7)
        self.molar.setSpecialValueText("not given")
        self.molar.setSuffix(" g/mol")
        self.molar.setValue(float(scan.sample.molar_mass or 0.0))
        self.molar.setToolTip(
            "Needed for a W/mol axis, and for enthalpies in kJ/mol. There is "
            "no default: a guessed molar mass makes a plot that looks right "
            "and is wrong by whatever factor.")
        form.addRow("Molar mass (sample)", self.molar)

        self.own_molar = NumberBox()
        self.own_molar.setDecimals(4)
        self.own_molar.setRange(0.0, 1e7)
        self.own_molar.setSpecialValueText("use the sample's")
        self.own_molar.setSuffix(" g/mol")
        self.own_molar.setValue(float(scan.molar_mass_override or 0.0))
        form.addRow("Molar mass (this scan)", self.own_molar)

        note = QLabel("Every scan of this file shares the sample's molar "
                      "mass unless it is given its own.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        for box in (self.offset, self.molar, self.own_molar):
            box.valueChanged.connect(self._apply)
        self.width.changed.connect(self._apply)
        self.analyses.itemChanged.connect(self._analysis_ticked)
        self.analyses.itemDoubleClicked.connect(self._edit_analysis)
        self.resize(440, self.sizeHint().height())

    @staticmethod
    def _analysis_text(analysis):
        text = analysis.summary()
        if not analysis.certain:
            text += "   ({})".format(analysis.attribution)
        elif not analysis.decoded:
            text += "   (cursors only)"
        return text

    def _analysis_ticked(self, item):
        analysis = item.data(Qt.UserRole)
        if analysis is None:
            return
        analysis.visible = item.checkState() == Qt.Checked
        self._live()

    def _edit_analysis(self, item):
        """Open one analysis's own settings from this list."""
        analysis = item.data(Qt.UserRole)
        if analysis is None:
            return
        dialog = AnalysisSettings(self, analysis, on_change=self.on_change)
        # Shown, not `exec`ed: `exec` is modal whatever the dialog says, and
        # these are meant to be worked beside the plot. The row is refreshed
        # when it closes rather than on the next line.
        self._analysis_dialog = dialog
        dialog.finished.connect(
            lambda _result, it=item, an=analysis: self._analysis_edited(it, an))
        dialog.show()
        dialog.raise_()

    def _analysis_edited(self, item, analysis):
        item.setText(self._analysis_text(analysis))
        item.setCheckState(Qt.Checked if analysis.visible else Qt.Unchecked)
        self._live()

    def _set_colour(self, name):
        self.obj.colour = name
        self._live()

    def _apply(self, *_args):
        scan = self.obj
        scan.label = self.label.text().strip() or None
        scan.offset = float(self.offset.value())
        scan.line_width = self.width.value()
        scan.molar_mass_override = (float(self.own_molar.value())
                                    if self.own_molar.value() > 0 else None)
        scan.sample.molar_mass = (float(self.molar.value())
                                  if self.molar.value() > 0 else None)
        scan._cache_key = None
        self._live()

    def reject(self):
        self.obj.sample.molar_mass = self._sample_molar_mass
        _LiveDialog.reject(self)


class SampleSettings(_LiveDialog):
    """The substance: its molar mass, and which way its arrays point."""

    FIELDS = ("molar_mass", "exo")

    def __init__(self, parent, sample, on_change=None):
        _LiveDialog.__init__(self, parent, sample, on_change)
        self.setWindowTitle("Sample: {}".format(sample.name))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        form.addRow("File", QLabel(sample.path))
        form.addRow("Instrument", QLabel(sample.instrument or "unknown"))
        form.addRow("Sample mass", QLabel(
            "{:g} mg".format(sample.mass_g * 1000.0) if sample.mass_g
            else "not in the file"))

        self.molar = NumberBox()
        self.molar.setDecimals(4)
        self.molar.setRange(0.0, 1e7)
        self.molar.setSpecialValueText("not given")
        self.molar.setSuffix(" g/mol")
        self.molar.setValue(float(sample.molar_mass or 0.0))
        form.addRow("Molar mass", self.molar)

        self.exo = QComboBox()
        for value in (units.EXO_DOWN, units.EXO_UP):
            self.exo.addItem("exotherms point {}".format(value), value)
        self.exo.setCurrentIndex(0 if sample.exo == units.EXO_DOWN else 1)
        form.addRow("In this file", self.exo)

        note = QLabel(
            "Read from the file: {}. The arrays are stored in this "
            "convention, so changing it flips this sample's curves. An "
            "indium run settles it for good: its melting peak is "
            "endothermic.".format(sample.exo_source))
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.molar.valueChanged.connect(self._apply)
        self.exo.currentIndexChanged.connect(self._apply)

    def _apply(self, *_args):
        sample = self.obj
        sample.molar_mass = (float(self.molar.value())
                             if self.molar.value() > 0 else None)
        sample.exo = self.exo.currentData()
        for scan in sample.scans:
            scan._cache_key = None
        self._live()


class CaptionSettings(_LiveDialog):
    """An axis CAPTION: its words and its size, and nothing else.

    Separate from the axis's own settings on purpose. Christian: the tick
    settings should not be what a double-click on the label gives you - the
    label is a piece of text, the spine is the axis. Double-clicking the
    spine opens `AxisSettings`; this is what the caption opens.
    """

    FIELDS = ("label", "label_size", "label_along", "label_gap")

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle("{} axis caption".format(axis.which.upper()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.label = QLineEdit(axis.label or "")
        self.label.setPlaceholderText(axis.caption(doc))
        form.addRow("Text", self.label)

        self.size = _style_number(self, axis, "label_size")
        form.addRow("Size", self.size)

        note = QLabel(
            "Empty means the axis says what is on it. `*T*` sets a symbol in "
            "italic, `_{g}` lowers a subscript, and a backslash name writes "
            "a Greek letter - the same markup the analysis labels take. Drag "
            "the caption to move it; it stays in the margin.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        self.size.changed.connect(self._apply)

    def _apply(self, *_args):
        self.obj.label = self.label.text().strip() or None
        self.obj.label_size = self.size.value()
        self._live()


class AxisSettings(_LiveDialog):
    """An axis: what it says, how it is drawn, and whether it has a grid.

    The defaults are the DSC_Plotter template's - ticks inward, minor ticks,
    no grid - so a figure looks like the published ones before anything is
    touched.
    """

    FIELDS = ("label", "show_grid", "minor_ticks", "ticks_inward",
              "label_size", "tick_size", "label_along", "label_gap")

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle("{} axis".format(axis.which.upper()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.label = QLineEdit(axis.label or "")
        self.label.setPlaceholderText(axis.caption(doc))
        self.label.setToolTip(
            "Empty means the axis says what is on it. Double-clicking the "
            "caption itself opens just this field and its size.")
        form.addRow("Caption", self.label)

        self.label_size = _style_number(self, axis, "label_size")
        form.addRow("Caption size", self.label_size)

        self.tick_size = _style_number(self, axis, "tick_size")
        form.addRow("Number size", self.tick_size)

        self.grid = QCheckBox("Grid lines")
        self.grid.setChecked(bool(axis.show_grid))
        form.addRow("", self.grid)

        self.minor = QCheckBox("Minor ticks")
        self.minor.setChecked(bool(axis.minor_ticks))
        form.addRow("", self.minor)

        self.inward = QCheckBox("Ticks point inward")
        self.inward.setChecked(bool(axis.ticks_inward))
        form.addRow("", self.inward)

        note = QLabel("The caption can also be dragged; it stays in the "
                      "margin, so it cannot land on the data.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        for box in (self.label_size, self.tick_size):
            box.changed.connect(self._apply)
        for check in (self.grid, self.minor, self.inward):
            check.toggled.connect(self._apply)

    def _apply(self, *_args):
        axis = self.obj
        axis.label = self.label.text().strip() or None
        axis.label_size = self.label_size.value()
        axis.tick_size = self.tick_size.value()
        axis.show_grid = bool(self.grid.isChecked())
        axis.minor_ticks = bool(self.minor.isChecked())
        axis.ticks_inward = bool(self.inward.isChecked())
        self._live()


class LabelSettings(_LiveDialog):
    """A caption the user placed: its text, size and colour."""

    FIELDS = ("text", "colour", "size", "bold", "x", "y", "space",
              "anchor")

    def __init__(self, parent, label, on_change=None):
        _LiveDialog.__init__(self, parent, label, on_change)
        self.setWindowTitle("Label")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.text = QLineEdit(label.text)
        form.addRow("Text", self.text)

        self.size = _style_number(self, label, "size")
        form.addRow("Size", self.size)

        self.bold = QCheckBox("Bold")
        self.bold.setChecked(bool(label.bold))
        form.addRow("", self.bold)

        self.transform = ArtistTransform(label, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        form.addRow("Colour", _colour_button(
            self, lambda: (label.colour if label.colour != "auto"
                           else "#cccccc"), self._set_colour))
        self.auto = QCheckBox("Follow the theme")
        self.auto.setChecked(label.colour in (None, "", "auto"))
        form.addRow("", self.auto)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.text.textChanged.connect(self._apply)
        self.size.changed.connect(self._apply)
        self.bold.toggled.connect(self._apply)
        self.auto.toggled.connect(self._apply)

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _apply(self, *_args):
        label = self.obj
        label.text = self.text.text() or "Label"
        label.size = self.size.value()
        label.bold = bool(self.bold.isChecked())
        if self.auto.isChecked():
            label.colour = "auto"
        self._live()


class AnalysisSettings(_LiveDialog):
    """One analysis: what it says, where it is drawn, and how sure that is.

    The attribution is the reason this dialog exists at all. A `.tri` ties an
    analysis to its scan through the cached curve it was computed from, which
    is exact. A `.txt` export names only the STEP, and three segments of a run
    share a name, so there the attachment is the reader's best guess. This is
    where that is stated and, when it is wrong, corrected.
    """

    FIELDS = ("visible", "colour", "label", "label_size", "flush",
              "show_interval", "shade")

    def __init__(self, parent, analysis, on_change=None):
        _LiveDialog.__init__(self, parent, analysis, on_change)
        self.setWindowTitle(analysis.model_name)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        form.addRow("Model", QLabel(analysis.model_name))
        form.addRow("From", QLabel(
            "the file" if analysis.source == "file" else "this panel"))

        values = QListWidget(self)
        values.setMaximumHeight(130)
        for key, value in analysis.fields.items():
            if key in ("Model", "segment", "attribution", "prog"):
                continue
            values.addItem("{}: {}".format(key, value))
        form.addRow("Values", values)

        self.shown_on = QComboBox()
        for scan in analysis.scan.sample.scans:
            self.shown_on.addItem(scan.short_program(), scan)
        index = self.shown_on.findData(analysis.scan)
        self.shown_on.setCurrentIndex(max(0, index))
        form.addRow("Drawn on", self.shown_on)

        self.visible = QCheckBox("Draw this analysis")
        self.visible.setChecked(bool(analysis.visible))
        form.addRow("", self.visible)

        self.interval = QCheckBox("Mark the interval on the curve")
        self.interval.setChecked(bool(analysis.show_interval))
        self.interval.setToolTip(
            "The bracket along the curve that says which stretch this "
            "covers. Worth switching off where two analyses overlap.")
        form.addRow("", self.interval)

        self.size = _style_number(self, analysis, "label_size")
        form.addRow("Label size", self.size)

        # The template's `flush`: which edge of the text sits on the arrow.
        self.flush = StyleChoice(
            style.FLUSHES, analysis.flush,
            lambda: style.FLUSH_TITLES[style.flush_for(
                analysis, style.inherited(self.doc, analysis, "flush"))],
            parent=self, titles=style.FLUSH_TITLES)
        self.flush.setToolTip(
            "Which edge of the label sits on its arrow: left reads away to "
            "the right of the feature, right to the left, centred hangs over "
            "it. The default follows the analysis kind unless Edit > "
            "Settings says otherwise.")
        form.addRow("Alignment", self.flush)

        self.label = QLineEdit(analysis.label or "")
        self.label.setPlaceholderText(analysis.summary())
        form.addRow("Label", self.label)

        form.addRow("Colour", _colour_button(
            self, lambda: (analysis.colour if analysis.colour != "auto"
                           else analysis.scan.colour), self._set_colour))
        self.auto = QCheckBox("Follow the scan's colour")
        self.auto.setChecked(analysis.colour in (None, "", "auto"))
        form.addRow("", self.auto)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.note)
        self._describe()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.visible.toggled.connect(self._apply)
        self.interval.toggled.connect(self._apply)
        self.size.changed.connect(self._apply)
        self.flush.changed.connect(self._apply)
        self.label.textChanged.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self.shown_on.currentIndexChanged.connect(self._move)
        self.resize(460, self.sizeHint().height())

    def _describe(self):
        analysis = self.obj
        if analysis.source == "panel":
            self.note.setText(
                "Measured here, on this scan, between the two cursors listed "
                "above. Double-click its label without dragging to bring the "
                "cursors back and move the interval; double-click-drag the "
                "label to move it.")
        elif analysis.certain:
            self.note.setText(
                "The file ties this analysis to its scan through the cached "
                "curve it was computed from, so the attachment is exact.")
        else:
            self.note.setText(
                "Attribution: {}. This came from a source that names only "
                "the step, and several segments of a run share a name, so "
                "which scan it belongs to is a guess. It is drawn with a "
                "dashed tick and a question mark until it is confirmed here."
                .format(analysis.attribution))

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _move(self, _index=0):
        scan = self.shown_on.currentData()
        if scan is not None:
            self.obj.reassign(scan)
            self._describe()
            self._live()

    def _apply(self, *_args):
        analysis = self.obj
        analysis.visible = bool(self.visible.isChecked())
        analysis.show_interval = bool(self.interval.isChecked())
        analysis.label_size = self.size.value()
        analysis.flush = self.flush.value()
        analysis.label = self.label.text().strip() or None
        if self.auto.isChecked():
            analysis.colour = "auto"
        self._live()


class LegendSettings(_LiveDialog):
    """The key: how big, how spaced, framed or not, and where."""

    FIELDS = ("visible", "size", "show_frame", "sample", "spacing", "colour",
              "x", "y", "space", "anchor")

    def __init__(self, parent, legend, on_change=None):
        _LiveDialog.__init__(self, parent, legend, on_change)
        self.setWindowTitle("Legend")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.visible = QCheckBox("Show the legend")
        self.visible.setChecked(bool(legend.visible))
        form.addRow("", self.visible)

        self.size = _style_number(self, legend, "size")
        form.addRow("Text size", self.size)

        self.sample = NumberBox()
        self.sample.setDecimals(0)
        self.sample.setRange(6.0, 80.0)
        self.sample.setValue(float(legend.sample))
        self.sample.setToolTip("Length of the colour sample before a name.")
        form.addRow("Sample length", self.sample)

        self.spacing = NumberBox()
        self.spacing.setDecimals(2)
        self.spacing.setRange(0.8, 3.0)
        self.spacing.setSingleStep(0.05)
        self.spacing.setValue(float(legend.spacing))
        form.addRow("Line spacing", self.spacing)

        self.frame = QCheckBox("Box behind it")
        self.frame.setChecked(bool(legend.show_frame))
        form.addRow("", self.frame)

        self.transform = ArtistTransform(legend, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        note = QLabel("The legend names the scans that are DRAWN, in the "
                      "order they are listed, using each one's own label.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.visible.toggled.connect(self._apply)
        self.frame.toggled.connect(self._apply)
        for box in (self.sample, self.spacing):
            box.valueChanged.connect(self._apply)
        self.size.changed.connect(self._apply)

    def _apply(self, *_args):
        legend = self.obj
        legend.visible = bool(self.visible.isChecked())
        legend.show_frame = bool(self.frame.isChecked())
        legend.size = self.size.value()
        legend.sample = float(self.sample.value())
        legend.spacing = float(self.spacing.value())
        self._live()


class ArrowSettings(_LiveDialog):
    """The heat-flow arrow: what it says, and therefore what the axis does."""

    FIELDS = ("word", "direction", "length", "colour", "visible",
              "x", "y", "space", "anchor")

    def __init__(self, parent, arrow, on_change=None):
        _LiveDialog.__init__(self, parent, arrow, on_change)
        self.setWindowTitle("Heat-flow arrow")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.word = QComboBox()
        for value in units.ARROW_WORDS:
            self.word.addItem(value.capitalize(), value)
        self.word.setCurrentIndex(units.ARROW_WORDS.index(arrow.word))
        self.direction = QComboBox()
        for value in units.ARROW_DIRECTIONS:
            self.direction.addItem(value.capitalize(), value)
        self.direction.setCurrentIndex(
            units.ARROW_DIRECTIONS.index(arrow.direction))
        row_layout.addWidget(self.word)
        row_layout.addWidget(self.direction)
        form.addRow("Label", row)

        self.transform = ArtistTransform(arrow, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        self.length = NumberBox()
        self.length.setDecimals(2)
        self.length.setRange(0.04, 0.9)
        self.length.setSingleStep(0.02)
        self.length.setValue(float(arrow.length))
        form.addRow("Length", self.length)

        form.addRow("Colour", _colour_button(
            self, lambda: arrow.colour, self._set_colour))

        self.auto = QCheckBox("Follow the theme")
        self.auto.setChecked(arrow.colour in (None, "", "auto"))
        self.auto.setToolTip(
            "Pale on the dark theme, dark on the light one, so the same "
            "figure works in both. Unticking keeps the colour picked above.")
        form.addRow("", self.auto)

        self.visible = QCheckBox("Show the arrow")
        self.visible.setChecked(bool(arrow.visible))
        form.addRow("", self.visible)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.word.currentIndexChanged.connect(self._apply)
        self.direction.currentIndexChanged.connect(self._apply)
        self.length.valueChanged.connect(self._apply)
        self.visible.toggled.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self._describe()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _describe(self):
        self.note.setText(
            "\"{} {}\" means exotherms point {}. The curves and the y axis "
            "follow the label, so \"exo down\" and \"endo up\" are the same "
            "figure with a different word on the arrow.".format(
                self.obj.word, self.obj.direction, self.obj.orientation))

    def _apply(self, *_args):
        arrow = self.obj
        arrow.word = self.word.currentData()
        arrow.direction = self.direction.currentData()
        arrow.length = float(self.length.value())
        arrow.visible = bool(self.visible.isChecked())
        if self.auto.isChecked():
            arrow.colour = "auto"
        self._describe()
        self._live()

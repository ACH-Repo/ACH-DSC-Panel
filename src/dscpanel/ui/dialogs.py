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
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

import html
import os

from ..core import figure as figure_module
from ..core import labels
from ..core import measure
from ..core import model as units_module
from ..core import numbers
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


class RangeDialog(QDialog):
    """Two numbers, typed: MestReNova's `M` for the x range.

    Built to be typed through without the mouse. The FIRST number is
    selected when it opens, so typing replaces it; Tab goes to the second,
    selected in turn; Enter takes both. A comma is a decimal point, as in
    `NumberBox`. The two may come in either order, and the dialog does not
    close on a pair that is not a range.

    Built here and shown by the window (`MainWindow.ask_x_range`), so a
    test can fill it without a modal loop.
    """

    def __init__(self, title, unit, low, high, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        row = QHBoxLayout()
        self.low_edit = QLineEdit(_number_text(low), self)
        self.high_edit = QLineEdit(_number_text(high), self)
        for edit in (self.low_edit, self.high_edit):
            edit.setAlignment(Qt.AlignRight)
            edit.setMinimumWidth(80)
            edit.textEdited.connect(self._clear_mark)
        row.addWidget(self.low_edit)
        row.addWidget(QLabel("to", self))
        row.addWidget(self.high_edit)
        if unit:
            row.addWidget(QLabel(unit, self))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # Enter takes the pair from either box, never a button's own idea.
        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(buttons)
        self.setTabOrder(self.low_edit, self.high_edit)
        self.low_edit.setFocus(Qt.OtherFocusReason)
        self.low_edit.selectAll()

    @staticmethod
    def _read(edit):
        try:
            value = float(edit.text().strip().replace(",", "."))
        except ValueError:
            return None
        return value if value == value and abs(value) != float("inf") else None

    def values(self):
        """`(low, high)` in increasing order, or None if it is not a range."""
        low, high = self._read(self.low_edit), self._read(self.high_edit)
        if low is None or high is None or low == high:
            return None
        return (min(low, high), max(low, high))

    def _clear_mark(self, _text=""):
        for edit in (self.low_edit, self.high_edit):
            edit.setStyleSheet("")

    def accept(self):
        if self.values() is None:
            for edit in (self.low_edit, self.high_edit):
                if self._read(edit) is None or self.values() is None:
                    edit.setStyleSheet("border: 1px solid #d04040;")
            return
        QDialog.accept(self)


def _number_text(value):
    """A limit as it should be offered for editing: short, and exact enough."""
    return "{:.6g}".format(float(value))


def readable(root):
    """Every label in `root` can be selected and copied, and every tooltip
    wraps.

    Qt draws a plain-text tooltip on ONE line, however long, which is how
    some of them ran across the whole screen; a rich-text one wraps at a
    readable width. Labels become mouse-selectable only (not by keyboard,
    so Tab still goes from field to field).
    """
    for label in root.findChildren(QLabel):
        label.setTextInteractionFlags(label.textInteractionFlags()
                                      | Qt.TextSelectableByMouse)
    for widget in [root] + root.findChildren(QWidget):
        text = widget.toolTip()
        if text and not text.startswith("<qt>"):
            widget.setToolTip("<qt>{}</qt>".format(html.escape(text)))


def markup_html(text):
    """Figure markup (`*T*_{on}`, `\\Delta`) as rich text, for a preview."""
    from .plot import markup_runs
    out = []
    for run, italic, subscript in markup_runs(text):
        piece = html.escape(run)
        if italic:
            piece = "<i>{}</i>".format(piece)
        if subscript:
            piece = "<sub>{}</sub>".format(piece)
        out.append(piece)
    return "".join(out)


def _plot_of(widget):
    """The plot a dialog's object is drawn on, or None."""
    window = _window_of(widget)
    return getattr(window, "plot", None) if window is not None else None


def arrow_offset_rows(dialog, form):
    """"Arrow Offset" and "Shift by": the distance from the curve to a
    label on an arrow, typed absolutely or moved relatively. The same rows
    for an analysis and for a y-offset marker. Positive is ABOVE the curve,
    as up is more on the y axis; in figure units (px)."""
    dialog.arrow_offset = NumberBox()
    dialog.arrow_shift = NumberBox()
    for box in (dialog.arrow_offset, dialog.arrow_shift):
        box.setDecimals(1)
        box.setRange(-2000.0, 2000.0)
        box.setSingleStep(2.0)
        box.setSuffix(" px")
    dialog.arrow_default = QCheckBox("Default")
    row = QWidget(dialog)
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addWidget(dialog.arrow_offset, 1)
    line.addWidget(dialog.arrow_default, 0)
    dialog.arrow_offset.setToolTip("Distance from the curve to the label; "
                                   "positive is above.")
    dialog.arrow_default.setToolTip("The automatic distance.")
    dialog.arrow_shift.setToolTip("Adds to the arrow offset (Enter, or the "
                                  "arrows). A group moves together.")
    form.addRow("Arrow Offset", row)
    form.addRow("Shift by", dialog.arrow_shift)


def _window_of(widget):
    """The main window a dialog belongs to (for what only it can do: an
    undo step that recomputes an analysis), or None."""
    while widget is not None:
        if hasattr(widget, "retype_interval"):
            return widget
        widget = widget.parentWidget()
    return None


def enter_stays(dialog, ev):
    """Enter in a field COMMITS it and keeps the window open.

    These windows apply as they are touched, and their values are tuned
    against each other - the arrow's head against its tail, a size against
    a distance. Enter closing the window after every value meant reopening
    it for the next one (Christian, round 15). A spin box has already taken
    its value when the key reaches the window; this only stops the window
    from treating the same key as its OK button, and selects the field's
    text so the next number can be typed straight over it. A focused
    button still takes Enter. Returns True when the key was handled.
    """
    if ev.key() not in (Qt.Key_Return, Qt.Key_Enter):
        return False
    focus = dialog.focusWidget()
    if isinstance(focus, QPushButton):
        return False
    if isinstance(focus, QAbstractSpinBox):
        focus.interpretText()
        focus.selectAll()
    elif isinstance(focus, QLineEdit):
        focus.selectAll()
    ev.accept()
    return True


class StyleText(QWidget):
    """A number FORMAT (`%.1f`) that is chosen here or follows a default.

    Empty follows: the field then shows what it would be as grey text. A
    format that is not one (text around the number, two numbers) is marked
    and not taken - see `core/numbers.py` for why a unit may not be part of
    it. `value()` is None for "follow", as the object stores it.
    """

    changed = Signal()

    def __init__(self, own, inherited, parent=None, reset_text="Default",
                 describe=None):
        QWidget.__init__(self, parent)
        self._own = numbers.normalise(own)
        self._inherited = inherited
        self._describe = describe
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(self)
        self.edit.setToolTip(
            "Python format: %.1f, %.3g (significant figures). A unit "
            "converts: %.0f \u00b0F.")
        self.reset = QPushButton(reset_text, self)
        row.addWidget(self.edit, 1)
        row.addWidget(self.reset, 0)
        self._show()
        self.edit.textEdited.connect(self._typed)
        self.reset.clicked.connect(lambda _c=False: self._follow())

    def value(self):
        return self._own

    def set_value(self, value):
        self._own = numbers.normalise(value)
        self._show(force=True)
        self.changed.emit()

    def refresh(self):
        self._show()

    def _show(self, force=False):
        inherited = self._inherited() if self._inherited else ""
        shown = ((self._describe(inherited) if self._describe else inherited)
                 or "automatic")
        self.edit.setPlaceholderText("{}  (default)".format(shown))
        # Not while it is being typed in: the text there is the user's.
        if force or not self.edit.hasFocus():
            self.edit.setText(self._own or "")
            self.edit.setStyleSheet("")
        self.reset.setEnabled(self._own is not None)

    def _typed(self, text):
        if not text.strip():
            self.edit.setStyleSheet("")
            self._follow()
            return
        spec = numbers.normalise(text)
        if spec is None:
            self.edit.setStyleSheet("border: 1px solid #d04040;")
            return
        self.edit.setStyleSheet("")
        self._own = spec
        self.reset.setEnabled(True)
        self.changed.emit()

    def _follow(self):
        self._own = None
        self._show(force=True)
        self.changed.emit()


class FontChoice(QWidget):
    """A font FAMILY chosen here, or following a default.

    `value()` is the family, "" for the system's own, or None for "follow".
    """

    changed = Signal()

    def __init__(self, own, inherited, parent=None, reset_text="Default"):
        QWidget.__init__(self, parent)
        self._own = own
        self._inherited = inherited
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QFontComboBox(self)
        self.reset = QPushButton(reset_text, self)
        row.addWidget(self.combo, 1)
        row.addWidget(self.reset, 0)
        self._show()
        self.combo.currentFontChanged.connect(self._picked)
        self.reset.clicked.connect(lambda _c=False: self._follow())

    def value(self):
        return self._own

    def set_value(self, value):
        self._own = value
        self._show()
        self.changed.emit()

    def refresh(self):
        self._show()

    def _family_shown(self):
        family = self._own if self._own is not None else (
            self._inherited() if self._inherited else "")
        return family or QFont().family()

    def _show(self):
        self.combo.blockSignals(True)
        self.combo.setCurrentFont(QFont(self._family_shown()))
        self.combo.blockSignals(False)
        self.reset.setEnabled(self._own is not None)
        self.combo.setToolTip(
            "Chosen here" if self._own is not None
            else "Following the default: {}".format(self._family_shown()))

    def _picked(self, font):
        self._own = font.family()
        self._show()
        self.changed.emit()

    def _follow(self):
        self._own = None
        self._show()
        self.changed.emit()


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
        self.reset.setToolTip("Use the house style (Edit > Settings).")
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
        self.box.setSuffix(self.setting.suffix + (
            "" if self._own is not None else "  (default)"))
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


def _style_text(dialog, obj, attr, describe=None):
    """The number-format field for `obj.attr`, following the house style."""
    return StyleText(getattr(obj, attr),
                     lambda: style.inherited(dialog.doc, obj, attr) or "",
                     parent=dialog, describe=describe)


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
        self.at_x = NumberBox()
        self.at_y = NumberBox()
        for box in (self.at_x, self.at_y):
            box.setDecimals(4)
            box.setRange(-1e9, 1e9)
            box.setSingleStep(0.01)
            row_layout.addWidget(box)
        self.at_x.setValue(float(artist.x))
        self.at_y.setValue(float(artist.y))
        form.addRow("x, y", row)

        self.anchor = QComboBox()
        for name in units_module.ANCHORS:
            self.anchor.addItem(name, name)
        index = self.anchor.findData(artist.anchor)
        self.anchor.setCurrentIndex(max(0, index))
        self.anchor.setToolTip("The point of the object that sits on "
                               "its position.")
        self.rotation = None
        if getattr(artist, "can_rotate", False):
            self.rotation = NumberBox()
            self.rotation.setDecimals(1)
            self.rotation.setRange(-360.0, 360.0)
            self.rotation.setSuffix(" \u00b0")
            self.rotation.setValue(float(getattr(artist, "rotation", 0.0)))
            self.rotation.setToolTip("Counter-clockwise, about the anchor. "
                                     "R turns it by hand.")
            form.addRow("Rotation", self.rotation)
            self.rotation.valueChanged.connect(self._apply)
        self.space.setToolTip("Fraction of the plot, or axis units.")
        self.at_x.setToolTip("Position, in the space above.")
        self.at_y.setToolTip("Position, in the space above.")
        form.addRow("Anchor", self.anchor)

        self.space.currentIndexChanged.connect(self._space_changed)
        self.at_x.valueChanged.connect(self._apply)
        self.at_y.valueChanged.connect(self._apply)
        self.anchor.currentIndexChanged.connect(self._apply)

    def _space_changed(self, _index=0):
        """Convert the stored position so the artist does not jump."""
        wanted = self.space.currentData()
        if wanted != self.artist.space and self.plot is not None:
            self.plot.convert_artist_space(self.artist, wanted)
        self.at_x.blockSignals(True)
        self.at_y.blockSignals(True)
        self.at_x.setValue(float(self.artist.x))
        self.at_y.setValue(float(self.artist.y))
        self.at_x.blockSignals(False)
        self.at_y.blockSignals(False)
        self._apply()

    def _apply(self, *_args):
        self.artist.space = self.space.currentData()
        self.artist.anchor = self.anchor.currentData()
        self.artist.x = float(self.at_x.value())
        self.artist.y = float(self.at_y.value())
        if self.rotation is not None:
            self.artist.rotation = float(self.rotation.value())
        if self.on_change is not None:
            self.on_change()


class _LiveDialog(QDialog):
    """Common machinery: snapshot on open, restore on reject.

    One dialog can edit SEVERAL objects of its kind at once (`set_group`,
    Christian, round 14: select three onsets, open the settings, set the
    size of all three). It shows the object it was opened on and MIRRORS
    every change onto the others: whatever field of the shown object just
    changed is copied to the rest, and nothing else is touched, so their
    own values of every other field stay theirs. Fields that belong to one
    object alone (`INDIVIDUAL`: a label's text, a position) are not mirrored
    and their widgets (`GROUP_DISABLED`) are greyed out.
    """

    #: Attribute names this dialog edits, for the snapshot.
    FIELDS = ()
    #: Fields that are one object's own, never set for a group.
    INDIVIDUAL = ()
    #: Widgets (attribute names on the dialog, dotted for a nested one)
    #: greyed out while a group is edited.
    GROUP_DISABLED = ()

    def __init__(self, parent, obj, on_change=None):
        QDialog.__init__(self, parent)
        self.obj = obj
        self.on_change = on_change
        self.doc = _document_of(parent)
        self._snapshot = {name: getattr(obj, name) for name in self.FIELDS}
        #: The OTHER objects edited along with `obj`, and what they were.
        self.group = []
        self._group_snapshots = []
        self._last = dict(self._snapshot)
        # NOT MODAL. These dialogs apply as they are touched and are meant to
        # be worked beside: a dialog that blocks the plot blocks the
        # measurement cursors it is describing, which is exactly what
        # Christian hit when adjusting an analysis. `Qt.Tool` keeps it above
        # the window it belongs to without taking the focus away from it.
        self.setModal(False)
        self.setWindowFlag(Qt.Tool, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def set_group(self, others):
        """Edit `others` along with the object this was opened on."""
        self.group = [o for o in others if o is not self.obj]
        self._group_snapshots = [
            (o, {name: getattr(o, name) for name in self.FIELDS})
            for o in self.group]
        self._last = {name: getattr(self.obj, name) for name in self.FIELDS}
        for path in self.GROUP_DISABLED:
            widget = self
            for part in path.split("."):
                widget = getattr(widget, part, None)
            if widget is not None:
                widget.setEnabled(False)
                widget.setToolTip("Per object: not set for a group.")
        if self.group:
            self.setWindowTitle("{}  (and {} more)".format(
                self.windowTitle(), len(self.group)))
        return self

    def _mirror(self):
        """Copy what just changed on the shown object to the rest."""
        for name in self.FIELDS:
            value = getattr(self.obj, name)
            if value == self._last.get(name):
                continue
            self._last[name] = value
            if name in self.INDIVIDUAL:
                continue
            for other in self.group:
                setattr(other, name, value)

    def _live(self, *_args):
        if self.group:
            self._mirror()
        if self.on_change is not None:
            self.on_change()

    def keyPressEvent(self, ev):
        if enter_stays(self, ev):
            return
        QDialog.keyPressEvent(self, ev)

    def showEvent(self, ev):
        readable(self)
        QDialog.showEvent(self, ev)
        self.fit()

    def fit(self):
        """Grow to what the rows need at this width. A wrapped label that
        is filled in after the window was sized - an analysis's results, a
        problem under its label - was cut off."""
        layout = self.layout()
        if layout is None:
            return
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.activate()
        needed = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else self.sizeHint().height())
        if needed > self.height():
            self.resize(self.width(), needed)

    def reject(self):
        """Closed without OK - its X, Esc, Ctrl+W: KEEP what was changed.

        Christian: these apply as they are touched, and "a change is a
        change". Closing used to put everything back, which after a minute
        of adjusting by eye is exactly the loss nobody expects. Only the
        Revert button puts things back (`revert`); either way an undo step
        is made, so Ctrl+Z still takes the whole dialog back afterwards.
        """
        self.accept()

    def revert(self):
        """The Revert button: put back what the objects were when this
        opened."""
        for name, value in self._snapshot.items():
            setattr(self.obj, name, value)
        for other, saved in self._group_snapshots:
            for name, value in saved.items():
                setattr(other, name, value)
        self._last = dict(self._snapshot)
        if self.on_change is not None:
            self.on_change()
        QDialog.reject(self)

    def _buttons(self):
        """OK and Revert. OK closes; Revert undoes this dialog and closes."""
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        revert = buttons.button(QDialogButtonBox.Cancel)
        revert.setText("Revert")
        revert.setToolTip("Undo this window's changes and close. "
                          "Closing otherwise keeps them.")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.revert)
        return buttons

    def snapshot(self):
        """What the object looked like when this opened, for the undo step."""
        return dict(self._snapshot)

    def snapshots(self):
        """`[(obj, {field: value when opened}), ...]` for every object this
        dialog edits, the shown one first."""
        return ([(self.obj, dict(self._snapshot))]
                + [(o, dict(saved)) for o, saved in self._group_snapshots])


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

    FIELDS = ("colour", "label", "offset", "line_width", "keep",
              "molar_mass_override")
    INDIVIDUAL = ("label", "offset", "molar_mass_override")
    GROUP_DISABLED = ("label", "offset", "molar", "own_molar", "analyses")

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
        self.label.setToolTip("Name in the legend. Empty: the segment's "
                              "program.")
        form.addRow("Label", self.label)

        form.addRow("Colour", _colour_button(
            self, lambda: scan.colour, self._set_colour))

        self.offset = NumberBox()
        self.offset.setDecimals(6)
        self.offset.setRange(-1e9, 1e9)
        self.offset.setValue(float(scan.offset))
        self.offset.setSuffix(" " + unit)
        self.offset.setToolTip("Vertical offset, in the y unit.")
        form.addRow("Offset", self.offset)

        self.line_width = _style_number(self, scan, "line_width")
        form.addRow("Line width", self.line_width)

        # The template's x_truncate: hide the ends by POSITION along the
        # curve, never by temperature (a segment doubles back at its start).
        cut = QWidget(self)
        cut_row = QHBoxLayout(cut)
        cut_row.setContentsMargins(0, 0, 0, 0)
        self.cut_start = NumberBox()
        self.cut_end = NumberBox()
        for box, value in ((self.cut_start, scan.keep[0]),
                           (self.cut_end, 1.0 - scan.keep[1])):
            box.setDecimals(1)
            box.setRange(0.0, 49.0)
            box.setSingleStep(0.5)
            box.setSuffix(" %")
            box.setValue(round(100.0 * float(value), 1))
        cut_row.addWidget(QLabel("first"))
        cut_row.addWidget(self.cut_start, 1)
        cut_row.addWidget(QLabel("last"))
        cut_row.addWidget(self.cut_end, 1)
        cut.setToolTip("Hide the curve's ends, by share of its points. "
                       "Hidden ends are left out of fits, analyses and "
                       "exports.")
        form.addRow("Hide", cut)
        self.cut_note = QLabel("")
        self.cut_note.setStyleSheet("color: #9a9a9a;")
        form.addRow("", self.cut_note)
        self._describe_cut()

        # The analyses, one box each, off unless ticked. A run carries a
        # dozen and a figure wants one or two, so the list is the dialogue
        # rather than a single "show them all" switch. Double-click opens an
        # analysis's own settings.
        self.analyses = QListWidget(self)
        self.analyses.setMaximumHeight(120)
        self.analyses.setToolTip("Tick to show. Double-click for settings.")
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
        self.molar.setToolTip("Needed for W/mol and kJ/mol. Never "
                              "assumed.")
        form.addRow("Molar mass (sample)", self.molar)

        self.own_molar = NumberBox()
        self.own_molar.setDecimals(4)
        self.own_molar.setRange(0.0, 1e7)
        self.own_molar.setSpecialValueText("use the sample's")
        self.own_molar.setSuffix(" g/mol")
        self.own_molar.setValue(float(scan.molar_mass_override or 0.0))
        self.own_molar.setToolTip("Overrides the sample's, for this scan.")
        form.addRow("Molar mass (this scan)", self.own_molar)

        note = QLabel("Scans of one file share its molar mass unless "
                      "given their own.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        for box in (self.offset, self.molar, self.own_molar):
            box.valueChanged.connect(self._apply)
        self.line_width.changed.connect(self._apply)
        self.cut_start.valueChanged.connect(self._apply)
        self.cut_end.valueChanged.connect(self._apply)
        self.analyses.itemChanged.connect(self._analysis_ticked)
        self.analyses.itemDoubleClicked.connect(self._edit_analysis)
        self.resize(440, self.sizeHint().height())

    def _describe_cut(self):
        """Where the drawn part of the curve now starts and ends."""
        temperature = self.obj.temperature()
        if temperature is None or not len(temperature):
            self.cut_note.setText("")
            return
        k0, k1 = self.obj.kept_range(len(temperature))
        self.cut_note.setText(
            "drawn from {:.1f} to {:.1f} \u00b0C ({} of {} points)".format(
                float(temperature[k0]), float(temperature[k1 - 1]),
                k1 - k0, len(temperature)))

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
        scan.line_width = self.line_width.value()
        scan.keep = (round(self.cut_start.value() / 100.0, 6),
                     round(1.0 - self.cut_end.value() / 100.0, 6))
        self._describe_cut()
        scan.molar_mass_override = (float(self.own_molar.value())
                                    if self.own_molar.value() > 0 else None)
        scan.sample.molar_mass = (float(self.molar.value())
                                  if self.molar.value() > 0 else None)
        scan._cache_key = None
        self._live()

    def revert(self):
        self.obj.sample.molar_mass = self._sample_molar_mass
        _LiveDialog.revert(self)


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

        note = QLabel("Direction from the file: {}. Changing it flips "
                      "this sample's curves.".format(sample.exo_source))
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = self._buttons()
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

    FIELDS = ("label", "label_size", "label_along", "label_gap", "visible")
    INDIVIDUAL = ("label", "label_along")
    GROUP_DISABLED = ("label",)

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle("{} axis caption".format(axis.which.upper()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.shown = QCheckBox("Show")
        self.shown.setChecked(bool(axis.visible))
        self.shown.setToolTip("Draw the caption.")
        form.addRow("", self.shown)

        self.label = QLineEdit(axis.label or "")
        self.label.setPlaceholderText(axis.caption(doc))
        form.addRow("Text", self.label)

        self.text_size = _style_number(self, axis, "label_size")
        form.addRow("Size", self.text_size)

        self.gap = _style_number(self, axis, "label_gap")
        self.gap.setToolTip("Space between the numbers and the caption. "
                            "Dragging sets it too.")
        form.addRow("Distance", self.gap)

        note = QLabel("*T* italic, _{g} subscript, \\Delta Greek, LaTeX "
                      "between $...$. Drag the caption to move it.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.gap.changed.connect(self._apply)
        self.shown.toggled.connect(self._apply)

    def _apply(self, *_args):
        self.obj.label = self.label.text().strip() or None
        self.obj.label_size = self.text_size.value()
        self.obj.label_gap = self.gap.value()
        self.obj.visible = bool(self.shown.isChecked())
        self._live()


class AxisSettings(_LiveDialog):
    """The SPINE: its side, its ticks and their steps, the line opposite it,
    and the grid. Opened by double-clicking the axis line; its numbers
    (`NumberSettings`) and its caption (`CaptionSettings`) have their own
    windows (Christian, round 18).

    The defaults are Origin's closed frame on the DSC_Plotter template's
    ticks: inward, minor ticks, the opposite line with ticks and no numbers,
    no grid.
    """

    FIELDS = ("side", "ticks_inward", "tick_length", "minor_ticks",
              "minor_count", "minor_length", "major_step", "mirror",
              "mirror_ticks", "show_grid")

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle("{} axis".format(axis.which.upper()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.side = QComboBox()
        for side in (("bottom", "top") if axis.which == "x"
                     else ("left", "right")):
            self.side.addItem(side, side)
        self.side.setCurrentIndex(max(0, self.side.findData(axis.side)))
        self.side.setToolTip("Which side of the plot the axis is on.")
        form.addRow("Side", self.side)

        self.inward = QCheckBox("Ticks point inward")
        self.inward.setChecked(bool(axis.ticks_inward))
        self.inward.setToolTip("Into the plot, as the template draws them.")
        form.addRow("", self.inward)

        self.step = NumberBox()
        self.step.setDecimals(4)
        self.step.setRange(0.0, 1e6)
        self.step.setToolTip("Distance between numbered ticks, in the "
                             "axis unit.")
        self.step_auto = QCheckBox("Automatic")
        self.step_auto.setToolTip("A round step that fits the range.")
        step_row = QWidget(self)
        step_line = QHBoxLayout(step_row)
        step_line.setContentsMargins(0, 0, 0, 0)
        step_line.addWidget(self.step, 1)
        step_line.addWidget(self.step_auto, 0)
        form.addRow("Major step", step_row)

        self.tick_length = NumberBox()
        self.minor_length = NumberBox()
        for box in (self.tick_length, self.minor_length):
            box.setDecimals(1)
            box.setRange(0.0, 60.0)
            box.setSuffix(" px")
        self.tick_length.setToolTip("Length of the numbered ticks.")
        self.minor_length.setToolTip("Length of the minor ticks.")
        form.addRow("Major length", self.tick_length)

        self.minor = QCheckBox("Minor ticks")
        self.minor.setToolTip("Unnumbered ticks between the numbered ones.")
        form.addRow("", self.minor)
        self.minor_count = QSpinBox()
        self.minor_count.setRange(1, 20)
        self.minor_count.setToolTip("Minor intervals per major one: 5 puts "
                                    "four ticks between two numbers.")
        form.addRow("Minor intervals", self.minor_count)
        form.addRow("Minor length", self.minor_length)

        self.mirror = QCheckBox("Line on the opposite side")
        self.mirror.setToolTip("Close the frame of the plot.")
        form.addRow("", self.mirror)
        self.mirror_ticks = QCheckBox("Ticks on it (no numbers)")
        self.mirror_ticks.setToolTip("Origin's style: the opposite line "
                                     "ticked like this one.")
        form.addRow("", self.mirror_ticks)

        self.grid = QCheckBox("Grid lines")
        self.grid.setToolTip("Lines across the plot at the numbered ticks.")
        form.addRow("", self.grid)

        note = QLabel("The numbers and the caption have their own settings: "
                      "double-click them.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = self._buttons()
        layout.addWidget(buttons)
        self._show()

        self.side.currentIndexChanged.connect(self._apply)
        for check in (self.inward, self.minor, self.mirror,
                      self.mirror_ticks, self.grid, self.step_auto):
            check.toggled.connect(self._apply)
        for box in (self.step, self.tick_length, self.minor_length):
            box.valueChanged.connect(self._apply)
        self.minor_count.valueChanged.connect(self._apply)

    def _step_shown(self):
        """The step as it is drawn, for the box while it is automatic."""
        plot = _plot_of(self)
        axis = self.obj
        if plot is None:
            return 0.0
        lo, hi = plot.view_x() if axis.which == "x" else plot.view_y()
        return float(plot.tick_step(axis, lo, hi))

    def _show(self):
        axis = self.obj
        widgets = (self.inward, self.step, self.step_auto, self.tick_length,
                   self.minor, self.minor_count, self.minor_length,
                   self.mirror, self.mirror_ticks, self.grid)
        for widget in widgets:
            widget.blockSignals(True)
        self.inward.setChecked(bool(axis.ticks_inward))
        self.step_auto.setChecked(axis.major_step is None)
        self.step.setValue(float(axis.major_step or self._step_shown()))
        self.step.setEnabled(axis.major_step is not None)
        self.tick_length.setValue(float(axis.tick_length))
        self.minor.setChecked(bool(axis.minor_ticks))
        self.minor_count.setValue(int(axis.minor_count))
        self.minor_length.setValue(float(axis.minor_length))
        self.minor_count.setEnabled(bool(axis.minor_ticks))
        self.minor_length.setEnabled(bool(axis.minor_ticks))
        self.mirror.setChecked(bool(axis.mirror))
        self.mirror_ticks.setChecked(bool(axis.mirror_ticks))
        self.mirror_ticks.setEnabled(bool(axis.mirror))
        self.grid.setChecked(bool(axis.show_grid))
        for widget in widgets:
            widget.blockSignals(False)

    def _apply(self, *_args):
        axis = self.obj
        axis.side = self.side.currentData()
        axis.ticks_inward = bool(self.inward.isChecked())
        if self.step_auto.isChecked():
            axis.major_step = None
        else:
            axis.major_step = float(self.step.value()) or None
        axis.tick_length = float(self.tick_length.value())
        axis.minor_ticks = bool(self.minor.isChecked())
        axis.minor_count = int(self.minor_count.value())
        axis.minor_length = float(self.minor_length.value())
        axis.mirror = bool(self.mirror.isChecked())
        axis.mirror_ticks = bool(self.mirror_ticks.isChecked())
        axis.show_grid = bool(self.grid.isChecked())
        self._live()
        self._show()


class NumberSettings(_LiveDialog):
    """An axis's NUMBERS: shown or not, their size, their format. Opened by
    double-clicking them; the spine and the caption have their own."""

    FIELDS = ("show_numbers", "tick_size", "number_format")

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle("{} axis numbers".format(axis.which.upper()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.shown = QCheckBox("Show")
        self.shown.setChecked(bool(axis.show_numbers))
        self.shown.setToolTip("Draw the numbers; the ticks stay.")
        form.addRow("", self.shown)

        self.tick_size = _style_number(self, axis, "tick_size")
        form.addRow("Size", self.tick_size)

        # Not house style: an x axis in degrees and a y axis in W/g want
        # different digits, so "automatic" is the only shared default.
        self.number_format = StyleText(axis.number_format, lambda: "",
                                       parent=self)
        form.addRow("Format", self.number_format)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.shown.toggled.connect(self._apply)
        self.tick_size.changed.connect(self._apply)
        self.number_format.changed.connect(self._apply)

    def _apply(self, *_args):
        axis = self.obj
        axis.show_numbers = bool(self.shown.isChecked())
        axis.tick_size = self.tick_size.value()
        axis.number_format = self.number_format.value()
        self._live()


class FigureSettings(_LiveDialog):
    """This figure's size and the place of its axes box - saved with it.

    Christian: two session files (first up-scans, second up-scans) exported
    with the same settings must come out the same size, with their axes
    boxes the same size and in the same place, so that they sit side by side
    in Word without fiddling. In "an exact size" the MARGINS decide the axes
    box; the numbers and captions have to fit inside them, and this says
    when they do not.
    """

    FIELDS = figure_module.FigureLayout.FIELDS

    def __init__(self, parent, layout_obj, plot=None, on_change=None):
        _LiveDialog.__init__(self, parent, layout_obj, on_change)
        self.plot = plot
        self.setWindowTitle("Figure size and margins")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.mode = QComboBox()
        for mode in figure_module.MODES:
            self.mode.addItem(figure_module.MODE_TITLES[mode], mode)
        self.mode.setCurrentIndex(max(0, self.mode.findData(layout_obj.mode)))
        form.addRow("The figure has", self.mode)

        self.unit = QComboBox()
        for unit, title in ((figure_module.UNIT_CM, "centimetres"),
                            (figure_module.UNIT_IN, "inches")):
            self.unit.addItem(title, unit)
        self.unit.setCurrentIndex(max(0, self.unit.findData(layout_obj.unit)))
        form.addRow("Unit", self.unit)

        def pair(first, second, between="x"):
            row = QWidget(self)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(first, 1)
            line.addWidget(QLabel(between))
            line.addWidget(second, 1)
            return row

        def length():
            box = NumberBox()
            box.setDecimals(2)
            box.setRange(0.0, 200.0)
            box.setSingleStep(0.1)
            return box

        self.fig_w, self.fig_h = length(), length()
        form.addRow("Size (width x height)", pair(self.fig_w, self.fig_h))
        self.margin_l, self.margin_r = length(), length()
        self.margin_t, self.margin_b = length(), length()
        form.addRow("Margins left, right", pair(self.margin_l, self.margin_r,
                                                ","))
        form.addRow("Margins top, bottom", pair(self.margin_t, self.margin_b,
                                                ","))
        self.axes_w, self.axes_h = length(), length()
        self.axes_w.setToolTip("The axes box; the figure grows around "
                               "it.")
        self.axes_h.setToolTip(self.axes_w.toolTip())
        form.addRow("Axes box", pair(self.axes_w, self.axes_h))

        self.aspect_w, self.aspect_h = NumberBox(), NumberBox()
        for box in (self.aspect_w, self.aspect_h):
            box.setDecimals(2)
            box.setRange(0.1, 100.0)
        form.addRow("Aspect ratio", pair(self.aspect_w, self.aspect_h, ":"))

        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip("Pixels per inch of a PNG. SVG is exact.")
        form.addRow("PNG resolution", self.dpi)

        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #e05a5a;")
        layout.addWidget(self.warning)
        note = QLabel("Saved with the session. Same size and margins, "
                      "same axes box; exports come out at exactly this "
                      "size.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        self.make_default = QPushButton("Use for new figures")
        self.make_default.setToolTip("New figures start with this "
                                     "layout.")
        self.make_default.clicked.connect(lambda _c=False: self.set_default())
        buttons = self._buttons()
        row = QHBoxLayout()
        row.addWidget(self.make_default)
        row.addStretch(1)
        row.addWidget(buttons)
        layout.addLayout(row)

        self._show()
        for box in (self.fig_w, self.fig_h, self.margin_l, self.margin_r,
                    self.margin_t, self.margin_b, self.aspect_w,
                    self.aspect_h):
            box.valueChanged.connect(self._apply)
        self.axes_w.valueChanged.connect(self._axes_typed)
        self.axes_h.valueChanged.connect(self._axes_typed)
        self.dpi.valueChanged.connect(self._apply)
        self.mode.currentIndexChanged.connect(self._apply)
        self.unit.currentIndexChanged.connect(self._unit_changed)

    def _boxes(self):
        return (self.fig_w, self.fig_h, self.margin_l, self.margin_r,
                self.margin_t, self.margin_b, self.axes_w, self.axes_h,
                self.aspect_w, self.aspect_h, self.dpi)

    def _show(self):
        """Put the layout's numbers in the boxes, without writing back."""
        fig = self.obj
        for box in self._boxes():
            box.blockSignals(True)
        suffix = " " + fig.unit
        for box, value in ((self.fig_w, fig.width), (self.fig_h, fig.height),
                           (self.margin_l, fig.margin_left),
                           (self.margin_r, fig.margin_right),
                           (self.margin_t, fig.margin_top),
                           (self.margin_b, fig.margin_bottom)):
            box.setSuffix(suffix)
            box.setValue(float(value))
        axes_w, axes_h = fig.axes_size()
        for box, value in ((self.axes_w, axes_w), (self.axes_h, axes_h)):
            box.setSuffix(suffix)
            box.setValue(max(0.0, float(value)))
        self.aspect_w.setValue(float(fig.aspect_w))
        self.aspect_h.setValue(float(fig.aspect_h))
        self.dpi.setValue(int(fig.dpi))
        for box in self._boxes():
            box.blockSignals(False)
        size_mode = fig.mode == figure_module.MODE_SIZE
        for box in (self.fig_w, self.fig_h, self.margin_l, self.margin_r,
                    self.margin_t, self.margin_b, self.axes_w, self.axes_h,
                    self.dpi, self.unit):
            box.setEnabled(size_mode)
        for box in (self.aspect_w, self.aspect_h):
            box.setEnabled(fig.mode == figure_module.MODE_ASPECT)
        self._describe()

    def _describe(self):
        """What does not fit in its margin, in the layout's unit."""
        if self.plot is None:
            self.warning.setText("")
            return
        fig = self.obj
        lines = []
        for side, need, have in self.plot.overflow():
            to_unit = figure_module.PER_INCH[fig.unit] \
                / figure_module.DESIGN_DPI
            lines.append("The {} margin is {:.2f} {} and what it holds "
                         "needs {:.2f} {}: numbers or a caption will be cut "
                         "off.".format(side, have * to_unit, fig.unit,
                                       need * to_unit, fig.unit))
        if not fig.is_valid():
            lines.append("The margins leave no room for the axes box.")
        self.warning.setText("\n".join(lines))

    def _apply(self, *_args):
        fig = self.obj
        fig.mode = self.mode.currentData()
        fig.width = float(self.fig_w.value())
        fig.height = float(self.fig_h.value())
        fig.margin_left = float(self.margin_l.value())
        fig.margin_right = float(self.margin_r.value())
        fig.margin_top = float(self.margin_t.value())
        fig.margin_bottom = float(self.margin_b.value())
        fig.aspect_w = float(self.aspect_w.value())
        fig.aspect_h = float(self.aspect_h.value())
        fig.dpi = int(self.dpi.value())
        self._live()
        self._show()

    def _axes_typed(self, *_args):
        """An axes box typed directly: the figure grows round it."""
        self.obj.set_axes_size(float(self.axes_w.value()),
                               float(self.axes_h.value()))
        self._live()
        self._show()

    def _unit_changed(self, *_args):
        self.obj.set_unit(self.unit.currentData())
        self._live()
        self._show()

    def set_default(self):
        """This layout, for every NEW figure from now on."""
        style.set_figure_default(self.obj)
        try:
            style.save_preferences()
        except OSError:
            pass
        self.make_default.setText("New figures use this")


class LabelSettings(_LiveDialog):
    """A caption the user placed: its text, size and colour."""

    FIELDS = ("text", "colour", "size", "bold", "x", "y", "space",
              "anchor", "rotation")
    INDIVIDUAL = ("text", "x", "y", "space")
    GROUP_DISABLED = ("text", "transform.space", "transform.at_x",
                      "transform.at_y")

    def __init__(self, parent, label, on_change=None):
        _LiveDialog.__init__(self, parent, label, on_change)
        self.setWindowTitle("Label")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.text = QLineEdit(label.text)
        self.text.setToolTip("*T* italic, _{g} subscript, \\Delta Greek, "
                             "LaTeX between $...$.")
        form.addRow("Text", self.text)

        self.text_size = _style_number(self, label, "size")
        form.addRow("Size", self.text_size)

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

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.text.textChanged.connect(self._apply)
        self.text_size.changed.connect(self._apply)
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
        label.size = self.text_size.value()
        label.bold = bool(self.bold.isChecked())
        if self.auto.isChecked():
            label.colour = "auto"
        self._live()


class AnalysisSettings(_LiveDialog):
    """One analysis: what it is, its interval, and how it is labelled.

    The model and the interval are recomputed IN PLACE by the window
    (`MainWindow.change_model`, `retype_interval`), each as its own undo
    step, exactly as dragging a gizmo is; everything else here is styling
    and goes into this window's one step.
    """

    FIELDS = ("visible", "colour", "label", "label_size", "flush",
              "show_interval", "shade", "number_format", "label_dy")
    INDIVIDUAL = ("label",)
    GROUP_DISABLED = ("label", "model", "start", "end")

    def __init__(self, parent, analysis, on_change=None):
        _LiveDialog.__init__(self, parent, analysis, on_change)
        self.setWindowTitle(analysis.model_name)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.model = QComboBox()
        for entry in measure.MODELS:
            self.model.addItem(entry.title, entry.name)
        if self.model.findData(analysis.model_name) < 0:
            self.model.addItem(analysis.model_name, analysis.model_name)
        self.model.setCurrentIndex(self.model.findData(analysis.model_name))
        self.model.setToolTip("Analysis type. Changing it recomputes on the "
                              "same interval.")
        form.addRow("Model", self.model)

        self.source = QLabel("")
        self.source.setToolTip("Where the numbers were computed.")
        form.addRow("From", self.source)

        # The interval: two numbers, typed in any temperature unit.
        self.start = QLineEdit(self)
        self.end = QLineEdit(self)
        for box, word in ((self.start, "start"), (self.end, "end")):
            box.setToolTip("Interval {}. 98 is in the axis unit; 98 F, "
                           "371 K, 98 C convert.".format(word))
            box.editingFinished.connect(self._typed_interval)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)

        self.results = QLabel("")
        self.results.setWordWrap(True)
        self.results.setToolTip("Everything the analysis computed.")
        form.addRow("Results", self.results)

        # No "Drawn on": an analysis from a .txt export is offered under
        # every scan with its step name and is attributed by being shown on
        # the one it belongs to (`Sample.analyses_for`, round 17).

        self.visible = QCheckBox("Show")
        self.visible.setChecked(bool(analysis.visible))
        self.visible.setToolTip("Draw this analysis.")
        form.addRow("", self.visible)

        self.interval = QCheckBox("Show interval markers")
        self.interval.setChecked(bool(analysis.show_interval))
        self.interval.setToolTip("Dashes at the interval ends, on the "
                                 "curve.")
        form.addRow("", self.interval)

        self.text_size = _style_number(self, analysis, "label_size")
        self.text_size.setToolTip("Label size, pt.")
        form.addRow("Label size", self.text_size)

        # The template's `flush`: which edge of the text sits on the arrow.
        self.flush = StyleChoice(
            style.FLUSHES, analysis.flush,
            lambda: style.FLUSH_TITLES[style.flush_for(
                analysis, style.inherited(self.doc, analysis, "flush"))],
            parent=self, titles=style.FLUSH_TITLES)
        self.flush.setToolTip("Which edge of the label sits on its arrow.")
        form.addRow("Alignment", self.flush)

        arrow_offset_rows(self, form)

        # A TEMPLATE: the words are the user's, `{}` is the measurement
        # (`core/labels.py`), so the number can never go stale or be typed.
        self.label = QLineEdit(analysis.label or "")
        self.label.setPlaceholderText(labels.default_template(analysis))
        self.label.setToolTip("Your text; {} is the measured value. A unit "
                              "after it converts: {} \u00b0F.")
        form.addRow("Label", self.label)

        self.number_format = _style_text(self, analysis, "number_format")
        form.addRow("Number format", self.number_format)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setToolTip("The label as drawn.")
        form.addRow("Shows", self.preview)

        form.addRow("Colour", _colour_button(
            self, lambda: (analysis.colour if analysis.colour != "auto"
                           else analysis.scan.colour), self._set_colour))
        self.auto = QCheckBox("Same as scan")
        self.auto.setChecked(analysis.colour in (None, "", "auto"))
        self.auto.setToolTip("Use the scan's colour.")
        form.addRow("", self.auto)

        self.note = QLabel("Adjust the values as needed. Drag the crosshairs "
                           "to adjust the interval. Hover over a field for an "
                           "explanation.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.note)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.visible.toggled.connect(self._apply)
        self.interval.toggled.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.flush.changed.connect(self._apply)
        self.label.textChanged.connect(self._apply)
        self.number_format.changed.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self.model.currentIndexChanged.connect(self._model_chosen)
        self.arrow_offset.valueChanged.connect(self._typed_offset)
        self.arrow_default.toggled.connect(self._default_offset)
        self.arrow_shift.valueChanged.connect(self._shift_offset)
        self._refresh()
        self.resize(460, self.sizeHint().height())

    # ------------------------------------------------------------ showing
    def _unit(self):
        doc = self.doc
        return getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C

    def _refresh(self):
        """Everything that follows the analysis's numbers."""
        analysis = self.obj
        self.setWindowTitle(analysis.model_name + (
            "  (and {} more)".format(len(self.group)) if self.group else ""))
        self.source.setText("the file" if analysis.source == "file"
                            else "this panel")
        self.label.setPlaceholderText(labels.default_template(analysis))
        cursors = analysis.cursors()
        unit = self._unit()
        for box, index in ((self.start, 0), (self.end, 1)):
            if len(cursors) == 2:
                box.setText("{} {}".format(
                    numbers.write(units.from_celsius(cursors[index], unit),
                                  "%.2f"),
                    units.TEMPERATURE_LABEL.get(unit, unit)))
            box.setStyleSheet("")
        has_interval = len(cursors) == 2 and not self.group
        for widget in (self.start, self.end, self.model):
            widget.setEnabled(has_interval)
        found = labels.results(analysis, self.doc)
        self.results.setText("<br>".join(
            "{}: {}".format(html.escape(name), html.escape(text))
            for name, text in found) or "-")
        self._show_offset()
        self._show_preview()

    def _show_preview(self):
        """The label as it will be drawn, and anything wrong with it."""
        rendered = labels.render(self.obj, self.doc)
        lines = [markup_html(rendered.text)]
        for _kind, message in rendered.problems:
            lines.append("<span style='color:#e08030'>{}</span>".format(
                html.escape(message)))
        self.preview.setText("<br>".join(lines))
        if self.isVisible():
            self.fit()

    def adopt_measurement(self, old_label, new_label):
        """The analysis was re-measured while this was open (its gizmos were
        moved, or its interval typed): show the new numbers."""
        if new_label != old_label:
            if self.label.text() == (old_label or ""):
                self.label.blockSignals(True)
                self.label.setText(new_label or "")
                self.label.blockSignals(False)
            if self._snapshot.get("label") == old_label:
                self._snapshot["label"] = new_label
        self._refresh()

    # ------------------------------------------------------------ editing
    def _typed_interval(self):
        """Start or End typed: recompute on the new interval (the window
        makes it an undo step, as a gizmo drag does)."""
        cursors = self.obj.cursors()
        if len(cursors) != 2:
            return
        typed = []
        for box, old in ((self.start, cursors[0]), (self.end, cursors[1])):
            value = units.parse_temperature(box.text(), self._unit())
            if value is None:
                box.setStyleSheet("border: 1px solid #d04040;")
                return
            typed.append(value)
        if all(abs(a - b) < 5e-3 for a, b in zip(typed, cursors)):
            return
        window = _window_of(self)
        if window is None or not window.retype_interval(self.obj, *typed):
            self.start.setStyleSheet("border: 1px solid #d04040;")
            self.end.setStyleSheet("border: 1px solid #d04040;")
            return
        self._refresh()

    def _model_chosen(self, _index=0):
        name = self.model.currentData()
        if not name or name == self.obj.model_name:
            return
        window = _window_of(self)
        if window is None or not window.change_model(self.obj, name):
            self.model.blockSignals(True)
            self.model.setCurrentIndex(
                self.model.findData(self.obj.model_name))
            self.model.blockSignals(False)
            return
        self._refresh()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    # The label's distance from the curve: stored as the screen offset
    # (negative is above), shown the way the y axis reads, positive up.
    def _effective(self, analysis):
        if analysis.label_dy is not None:
            return float(analysis.label_dy)
        plot = _plot_of(self)
        return float(plot.effective_label_dy(analysis)) if plot else -46.0

    def _show_offset(self):
        boxes = (self.arrow_offset, self.arrow_default, self.arrow_shift)
        for box in boxes:
            box.blockSignals(True)
        self.arrow_offset.setValue(-self._effective(self.obj))
        self.arrow_default.setChecked(self.obj.label_dy is None)
        self.arrow_shift.setValue(0.0)
        for box in boxes:
            box.blockSignals(False)

    def _typed_offset(self, value):
        self.obj.label_dy = -float(value)
        self._live()
        self._show_offset()

    def _default_offset(self, on):
        self.obj.label_dy = None if on else self._effective(self.obj)
        self._live()
        self._show_offset()

    def _shift_offset(self, value):
        """Every analysis of the window, moved by the same amount."""
        if not value:
            return
        for analysis in [self.obj] + list(self.group):
            analysis.label_dy = self._effective(analysis) - float(value)
        self._last["label_dy"] = self.obj.label_dy   # moved, not mirrored
        self._live()
        self._show_offset()

    def _apply(self, *_args):
        analysis = self.obj
        analysis.visible = bool(self.visible.isChecked())
        analysis.show_interval = bool(self.interval.isChecked())
        analysis.label_size = self.text_size.value()
        analysis.flush = self.flush.value()
        analysis.label = self.label.text().strip() or None
        analysis.number_format = self.number_format.value()
        if self.auto.isChecked():
            analysis.colour = "auto"
        self._live()
        self._show_preview()


class LegendSettings(_LiveDialog):
    """The key: how big, how spaced, framed or not, and where."""

    FIELDS = ("visible", "size", "show_frame", "sample", "spacing", "colour",
              "x", "y", "space", "anchor", "rotation", "line_width")

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

        self.text_size = _style_number(self, legend, "size")
        form.addRow("Text size", self.text_size)

        self.sample = NumberBox()
        self.sample.setDecimals(0)
        self.sample.setRange(6.0, 80.0)
        self.sample.setValue(float(legend.sample))
        self.sample.setToolTip("Length of each colour sample.")
        form.addRow("Sample length", self.sample)

        self.spacing = NumberBox()
        self.spacing.setDecimals(2)
        self.spacing.setRange(0.8, 3.0)
        self.spacing.setSingleStep(0.05)
        self.spacing.setValue(float(legend.spacing))
        form.addRow("Line spacing", self.spacing)
        self.spacing.setToolTip("Row height, in lines.")

        self.line_width = NumberBox()
        self.line_width.setDecimals(2)
        self.line_width.setRange(0.0, 12.0)
        self.line_width.setSingleStep(0.25)
        self.line_width.setSpecialValueText("as the scans")
        self.line_width.setValue(float(legend.line_width or 0.0))
        self.line_width.setToolTip("Width of the colour samples; 0 uses "
                                   "each scan's own.")
        form.addRow("Line width", self.line_width)

        self.frame = QCheckBox("Box behind it")
        self.frame.setToolTip("A box behind the legend, for legibility.")
        self.frame.setChecked(bool(legend.show_frame))
        form.addRow("", self.frame)

        self.transform = ArtistTransform(legend, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        note = QLabel("Lists the shown scans, by their labels.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.visible.toggled.connect(self._apply)
        self.frame.toggled.connect(self._apply)
        for box in (self.sample, self.spacing, self.line_width):
            box.valueChanged.connect(self._apply)
        self.text_size.changed.connect(self._apply)

    def _apply(self, *_args):
        legend = self.obj
        legend.visible = bool(self.visible.isChecked())
        legend.show_frame = bool(self.frame.isChecked())
        legend.size = self.text_size.value()
        legend.sample = float(self.sample.value())
        legend.spacing = float(self.spacing.value())
        legend.line_width = (float(self.line_width.value())
                             if self.line_width.value() > 0 else None)
        self._live()


class OffsetMarkerSettings(_LiveDialog):
    """A y-offset marker: its size, format, colour, and where it points.

    NOT the scan's offset: that belongs to the scan's own settings. The
    marker only says what it is.
    """

    FIELDS = ("size", "colour", "visible", "at", "dy", "number_format")

    def __init__(self, parent, marker, on_change=None):
        _LiveDialog.__init__(self, parent, marker, on_change)
        self.plot = getattr(parent, "plot", None) or _plot_of(parent)
        self.setWindowTitle("Offset marker: {}".format(
            marker.scan.display_name()))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.visible = QCheckBox("Show")
        self.visible.setChecked(bool(marker.visible))
        self.visible.setToolTip("Draw this marker.")
        form.addRow("", self.visible)

        self.text_size = _style_number(self, marker, "size")
        form.addRow("Size", self.text_size)

        self.number_format = _style_text(self, marker, "number_format")
        form.addRow("Number format", self.number_format)

        self.at = NumberBox()
        self.at.setDecimals(2)
        self.at.setRange(-1e6, 1e6)
        self.at.setSuffix(" \u00b0C")
        self.at.setToolTip("Temperature to point at. For a group, lines "
                           "them up.")
        self.at_auto = QCheckBox("Against the y axis")
        self.at_auto.setToolTip("Left end of the curve as shown.")
        form.addRow("Points at", self.at)
        form.addRow("", self.at_auto)

        arrow_offset_rows(self, form)

        form.addRow("Colour", _colour_button(
            self, lambda: (marker.colour if marker.colour != "auto"
                           else "#cccccc"), self._set_colour))
        self.auto = QCheckBox("Follow the theme")
        self.auto.setChecked(marker.colour in (None, "", "auto"))
        self.auto.setToolTip("Light on dark, dark on light.")
        form.addRow("", self.auto)

        buttons = self._buttons()
        layout.addWidget(buttons)
        self._show_place()

        self.visible.toggled.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.number_format.changed.connect(self._apply)
        self.at.valueChanged.connect(self._typed_at)
        self.at_auto.toggled.connect(self._auto_at)
        self.arrow_offset.valueChanged.connect(self._typed_offset)
        self.arrow_default.toggled.connect(self._default_offset)
        self.arrow_shift.valueChanged.connect(self._shift_offset)
        self.auto.toggled.connect(self._apply)

    # The marker stores how far BELOW the curve its text starts; the
    # window says it the way the y axis does, positive up.
    def _effective(self, marker):
        if marker.dy is not None:
            return float(marker.dy)
        return float(self.plot.marker_dy(marker)) if self.plot else 0.0

    def _show_place(self):
        """The numbers as drawn, whether chosen or automatic."""
        marker = self.obj
        widgets = (self.at, self.at_auto, self.arrow_offset,
                   self.arrow_default, self.arrow_shift)
        for widget in widgets:
            widget.blockSignals(True)
        at = self.plot.marker_celsius(marker) if self.plot else None
        if at is None and marker.at and marker.at[0] == "T":
            at = marker.at[1]
        self.at.setValue(float(at or 0.0))
        self.at_auto.setChecked(marker.at is None)
        self.arrow_offset.setValue(-self._effective(marker))
        self.arrow_default.setChecked(marker.dy is None)
        self.arrow_shift.setValue(0.0)
        for widget in widgets:
            widget.blockSignals(False)

    def _typed_at(self, value):
        self.obj.at = ("T", float(value))
        self._apply()

    def _auto_at(self, on):
        if on:
            self.obj.at = None
        elif self.obj.at is None:
            self.obj.at = ("T", float(self.at.value()))
        self._apply()

    def _typed_offset(self, value):
        self.obj.dy = -float(value)
        self._apply()

    def _default_offset(self, on):
        self.obj.dy = None if on else self._effective(self.obj)
        self._apply()

    def _shift_offset(self, value):
        """Every marker of the window, moved by the same amount - not set
        to the same value, so a group keeps its differences."""
        if not value:
            return
        for marker in [self.obj] + list(self.group):
            marker.dy = self._effective(marker) - float(value)
        self._last["dy"] = self.obj.dy          # moved, not to be mirrored
        self._apply()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _apply(self, *_args):
        marker = self.obj
        marker.visible = bool(self.visible.isChecked())
        marker.size = self.text_size.value()
        marker.number_format = self.number_format.value()
        if self.auto.isChecked():
            marker.colour = "auto"
        self._live()
        self._show_place()


class ArrowSettings(_LiveDialog):
    """The heat-flow arrow: what it says, and therefore what the axis does,
    and its shape in points.

    The head's length, width and tip angle are tied - any two decide the
    third - so one of the angle and the width can be LOCKED: with the angle
    locked, a longer head is also a wider one; with the width locked, a
    longer head is a sharper one. Unlocked, the length and the width are
    kept and the angle is what follows.
    """

    FIELDS = ("word", "direction", "colour", "visible",
              "x", "y", "space", "anchor", "head_length", "head_width",
              "tail_length", "tail_width", "lock", "size")

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

        self.text_size = _style_number(self, arrow, "size")
        form.addRow("Text size", self.text_size)

        self.transform = ArtistTransform(arrow, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        def points(low, high, decimals=1, suffix=" pt"):
            box = NumberBox()
            box.setDecimals(decimals)
            box.setRange(low, high)
            box.setSingleStep(0.5)
            box.setSuffix(suffix)
            return box

        self.head_length = points(0.5, 200.0)
        self.head_width = points(0.5, 200.0)
        self.tip_angle = points(5.0, 170.0, suffix=" \u00b0")
        self.tail_length = points(0.0, 400.0)
        self.tail_width = points(0.5, 200.0)
        form.addRow("Head length", self.head_length)
        form.addRow("Head width", self.head_width)
        form.addRow("Tip angle", self.tip_angle)
        self.lock_angle = QCheckBox("Lock the tip angle")
        self.lock_width = QCheckBox("Lock the head width")
        locks = QWidget(self)
        locks_row = QHBoxLayout(locks)
        locks_row.setContentsMargins(0, 0, 0, 0)
        locks_row.addWidget(self.lock_angle)
        locks_row.addWidget(self.lock_width)
        form.addRow("", locks)
        form.addRow("Tail length", self.tail_length)
        form.addRow("Tail width", self.tail_width)
        self.head_length.setToolTip("Head length, pt.")
        self.head_width.setToolTip("Head width, pt. Tied to length and "
                                   "angle.")
        self.tip_angle.setToolTip("Angle at the point. Tied to length and "
                                  "width.")
        self.lock_angle.setToolTip("Keep the angle when the head is "
                                   "resized.")
        self.lock_width.setToolTip("Keep the width when the head is "
                                   "resized.")
        self.tail_length.setToolTip("Tail length, pt.")
        self.tail_width.setToolTip("Tail width, pt.")
        self.word.setToolTip("Exo or endo; the curves follow the label.")
        self.direction.setToolTip("Up or down; the curves follow the label.")
        self._show_shape()

        form.addRow("Colour", _colour_button(
            self, lambda: arrow.colour, self._set_colour))

        self.auto = QCheckBox("Follow the theme")
        self.auto.setChecked(arrow.colour in (None, "", "auto"))
        self.auto.setToolTip("Light on dark, dark on light.")
        form.addRow("", self.auto)

        self.visible = QCheckBox("Show the arrow")
        self.visible.setChecked(bool(arrow.visible))
        form.addRow("", self.visible)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.note)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.word.currentIndexChanged.connect(self._apply)
        self.direction.currentIndexChanged.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.visible.toggled.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self.head_length.valueChanged.connect(
            lambda v: self._head(self.obj.head_for_length(v)))
        self.head_width.valueChanged.connect(
            lambda v: self._head(self.obj.head_for_width(v)))
        self.tip_angle.valueChanged.connect(
            lambda v: self._head(self.obj.head_for_angle(v)))
        self.tail_length.valueChanged.connect(self._apply)
        self.tail_width.valueChanged.connect(self._apply)
        self.lock_angle.toggled.connect(
            lambda on: self._lock("angle", on))
        self.lock_width.toggled.connect(
            lambda on: self._lock("width", on))
        self._describe()

    def _show_shape(self):
        """Every dimension as it now is; the locked one greyed out."""
        arrow = self.obj
        boxes = (self.head_length, self.head_width, self.tip_angle,
                 self.tail_length, self.tail_width, self.lock_angle,
                 self.lock_width)
        for box in boxes:
            box.blockSignals(True)
        self.head_length.setValue(float(arrow.head_length))
        self.head_width.setValue(float(arrow.head_width))
        self.tip_angle.setValue(float(arrow.tip_angle))
        self.tail_length.setValue(float(arrow.tail_length))
        self.tail_width.setValue(float(arrow.tail_width))
        self.lock_angle.setChecked(arrow.lock == "angle")
        self.lock_width.setChecked(arrow.lock == "width")
        self.tip_angle.setEnabled(arrow.lock != "angle")
        self.head_width.setEnabled(arrow.lock != "width")
        for box in boxes:
            box.blockSignals(False)

    def _head(self, head):
        self.obj.head_length, self.obj.head_width = head
        self._show_shape()
        self._live()

    def _lock(self, which, on):
        """One lock at a time: ticking one unticks the other."""
        if on:
            self.obj.lock = which
        elif self.obj.lock == which:
            self.obj.lock = None
        self._show_shape()
        self._live()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _describe(self):
        self.note.setText(
            "\"{} {}\": exotherms point {}; the curves follow the label. "
            "Sizes in pt. S scales the whole arrow.".format(
                self.obj.word, self.obj.direction, self.obj.orientation))

    def _apply(self, *_args):
        arrow = self.obj
        arrow.word = self.word.currentData()
        arrow.direction = self.direction.currentData()
        arrow.size = self.text_size.value()
        arrow.tail_length = float(self.tail_length.value())
        arrow.tail_width = float(self.tail_width.value())
        arrow.visible = bool(self.visible.isChecked())
        if self.auto.isChecked():
            arrow.colour = "auto"
        self._describe()
        self._live()


class ExportDialog(QDialog):
    """Where the figure goes, and in which colours (Christian, round 18).

    The system's save dialog has no room for a choice of its own, so this
    is the export: a file (Browse opens the system dialog for it), and the
    colours - light, for a page, or as the theme on screen.
    """

    def __init__(self, parent, path, light=True, size_text=""):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Export the figure")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit(path, self)
        self.path_edit.setMinimumWidth(320)
        self.path_edit.setToolTip("A .svg or a .png file.")
        browse = QPushButton("Browse...", self)
        browse.setAutoDefault(False)
        browse.clicked.connect(lambda _c=False: self._browse())
        line.addWidget(self.path_edit, 1)
        line.addWidget(browse, 0)
        form.addRow("File", row)

        self.colours = QComboBox(self)
        self.colours.addItem("Light, for a page", True)
        self.colours.addItem("Same as the theme", False)
        self.colours.setCurrentIndex(0 if light else 1)
        self.colours.setToolTip("Light is dark ink on white; the theme is "
                                "what the screen shows.")
        form.addRow("Colours", self.colours)
        if size_text:
            form.addRow("Size", QLabel(size_text, self))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(
            self, "Export the figure", self.path_edit.text(),
            "SVG image (*.svg);;PNG image (*.png)")
        if path:
            self.path_edit.setText(path)

    def values(self):
        """`(path, light)`, or None without a file name."""
        path = self.path_edit.text().strip()
        if not path:
            return None
        if os.path.splitext(path)[1].lower() not in (".svg", ".png"):
            path += ".svg"
        return path, bool(self.colours.currentData())


#: The DSC_Plotter template's line colours, in its order (`colors` in its
#: driver): what the colour picker's basic colours start with.
PLOTTER_COLOURS = ("#0000ff", "#008000", "#ff0000", "#ffa500", "#ff00ff",
                   "#d2691e", "#00008b", "#005000", "#00ffff", "#008080",
                   "#800080", "#8a2be2", "#808080", "#800000", "#9acd32",
                   "#000000")
#: And after them: the panel's own screen colours, Tableau's ten,
#: Okabe and Ito's colour-blind-safe set, and greys.
MORE_COLOURS = ("#6ea8ff", "#ffb04e", "#7fd08a", "#e07b7b", "#c79bef",
                "#4fd0c8", "#d8d16a", "#f08ac0",
                "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
                "#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2",
                "#d55e00", "#cc79a7",
                "#ffffff", "#e0e0e0", "#c0c0c0", "#a0a0a0", "#606060",
                "#404040", "#202020")


def install_basic_colours():
    """The colour picker's 48 basic colours, read left to right and top to
    bottom: the plotter's first, in its order. Qt numbers the grid down
    its six rows first, so the reading order is mapped onto that."""
    colours = (PLOTTER_COLOURS + MORE_COLOURS)[:48]
    for order, name in enumerate(colours):
        row, column = divmod(order, 8)
        QColorDialog.setStandardColor(row + column * 6, QColor(name))
    return len(colours)

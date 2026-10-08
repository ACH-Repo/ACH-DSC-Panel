"""Per-object settings, applied as they are touched.

Live-apply with a snapshot for Cancel, which is the right rule for anything
judged by eye: a dialog you have to close before you can see what it did
makes a knob unusable. Cancel puts back what was there when the dialog
opened, because by then the object has already been changed a dozen times.

`NumberBox` exists because on a German locale Qt's decimal separator is a
comma, so a typed "0.15" is not a number and the box quietly keeps its old
value. Both forms are taken and the typed text is left alone while it is
being typed.
"""

from PySide6.QtCore import QLocale, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QValidator
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

#: How much of the screen's height a settings window may take before its
#: rows scroll (an integration's settings ran off a small screen). Small
#: ones never reach it.
SCREEN_SHARE = 0.85

import copy
import html
import os

from ..core import figure as figure_module
from ..core import labels
from ..core import measure
from ..core import molar
from ..core import model as units_module
from ..core import numbers
from ..core import style
from ..core import units
from .colour import MORE_COLOURS, PLOTTER_COLOURS
from .colour import get_colour as pick_colour
from .numbox import NumberBox, WholeBox


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

    def __init__(self, title, unit, low, high, parent=None, y=None,
                 y2=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        row = QHBoxLayout()
        self.low_edit = QLineEdit(_number_text(low), self)
        self.high_edit = QLineEdit(_number_text(high), self)
        for edit in (self.low_edit, self.high_edit):
            edit.setAlignment(Qt.AlignRight)
            edit.setMinimumWidth(80)
            edit.textEdited.connect(self._clear_mark)
        if y is not None:
            row.addWidget(QLabel("x", self))
        row.addWidget(self.low_edit)
        row.addWidget(QLabel("to", self))
        row.addWidget(self.high_edit)
        if unit:
            row.addWidget(QLabel(unit, self))
        # The y range, AFTER the x one: Tab reaches it only when wanted,
        # and Enter after the x pair leaves it as it is.
        self.y_low_edit = self.y_high_edit = None
        y_row = None
        if y is not None:
            y_unit, y_low, y_high = y
            y_row = QHBoxLayout()
            self.y_low_edit = QLineEdit(_number_text(y_low), self)
            self.y_high_edit = QLineEdit(_number_text(y_high), self)
            y_row.addWidget(QLabel("y", self))
            for edit in (self.y_low_edit, self.y_high_edit):
                edit.setAlignment(Qt.AlignRight)
                edit.setMinimumWidth(80)
                edit.textEdited.connect(self._clear_mark)
            y_row.addWidget(self.y_low_edit)
            y_row.addWidget(QLabel("to", self))
            y_row.addWidget(self.y_high_edit)
            if y_unit:
                y_row.addWidget(QLabel(y_unit, self))
        # The weight axis of an SDT run, last.
        self.y2_low_edit = self.y2_high_edit = None
        y2_row = None
        if y2 is not None:
            y2_unit, y2_low, y2_high = y2
            y2_row = QHBoxLayout()
            self.y2_low_edit = QLineEdit(_number_text(y2_low), self)
            self.y2_high_edit = QLineEdit(_number_text(y2_high), self)
            y2_row.addWidget(QLabel("mass", self))
            for edit in (self.y2_low_edit, self.y2_high_edit):
                edit.setAlignment(Qt.AlignRight)
                edit.setMinimumWidth(80)
                edit.textEdited.connect(self._clear_mark)
            y2_row.addWidget(self.y2_low_edit)
            y2_row.addWidget(QLabel("to", self))
            y2_row.addWidget(self.y2_high_edit)
            if y2_unit:
                y2_row.addWidget(QLabel(y2_unit, self))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # Enter takes the pair from either box, never a button's own idea.
        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        if y_row is not None:
            layout.addLayout(y_row)
        if y2_row is not None:
            layout.addLayout(y2_row)
        layout.addWidget(buttons)
        self.setTabOrder(self.low_edit, self.high_edit)
        if y_row is not None:
            self.setTabOrder(self.high_edit, self.y_low_edit)
            self.setTabOrder(self.y_low_edit, self.y_high_edit)
        if y2_row is not None:
            self.setTabOrder(self.y_high_edit or self.high_edit,
                             self.y2_low_edit)
            self.setTabOrder(self.y2_low_edit, self.y2_high_edit)
        self.low_edit.setFocus(Qt.OtherFocusReason)
        self.low_edit.selectAll()

    @staticmethod
    def _read(edit):
        return numbers.evaluate(edit.text())

    def values(self):
        """`(low, high)` in increasing order, or None if it is not a range."""
        return self._pair(self.low_edit, self.high_edit)

    def y_values(self):
        """The y pair like `values`, or None (no y row, or not a range)."""
        if self.y_low_edit is None:
            return None
        return self._pair(self.y_low_edit, self.y_high_edit)

    def y2_values(self):
        """The mass axis's pair like `values`, or None."""
        if self.y2_low_edit is None:
            return None
        return self._pair(self.y2_low_edit, self.y2_high_edit)

    def _pair(self, first, second):
        low, high = self._read(first), self._read(second)
        if low is None or high is None or low == high:
            return None
        return (min(low, high), max(low, high))

    def _edits(self):
        return [e for e in (self.low_edit, self.high_edit, self.y_low_edit,
                            self.y_high_edit, self.y2_low_edit,
                            self.y2_high_edit) if e is not None]

    def _clear_mark(self, _text=""):
        for edit in self._edits():
            edit.setStyleSheet("")

    def accept(self):
        pairs = [((self.low_edit, self.high_edit), self.values())]
        if self.y_low_edit is not None:
            pairs.append(((self.y_low_edit, self.y_high_edit),
                          self.y_values()))
        if self.y2_low_edit is not None:
            pairs.append(((self.y2_low_edit, self.y2_high_edit),
                          self.y2_values()))
        wrong = False
        for edits, value in pairs:
            if value is None:
                wrong = True
                for edit in edits:
                    edit.setStyleSheet("border: 1px solid #d04040;")
        if not wrong:
            QDialog.accept(self)


class PageSizeDialog(QDialog):
    """The figure's size in numbers: a double-click on a page handle.

    Width and height, in cm or inches. With "Keep the aspect ratio" on (the
    default) typing one fills in the other at the page's present
    proportions, so a figure is made exactly 8.5 cm wide without its shape
    changing; off, the two are free and the ratio follows them. Typed through
    like `RangeDialog`: the width is selected on opening, Tab goes to the
    height, Enter takes them. A comma is a decimal point.

    `least` is the smallest width and height, in cm, the margins leave room
    for: a smaller page is refused (marked red) rather than made.
    """

    def __init__(self, width, height, unit, parent=None, least=(0.0, 0.0)):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Figure size")
        self._unit = unit
        self._ratio = float(width) / max(1e-9, float(height))
        self._least_cm = (float(least[0]), float(least[1]))
        row = QHBoxLayout()
        self.width_edit = QLineEdit(_length_text(width), self)
        self.height_edit = QLineEdit(_length_text(height), self)
        for edit in (self.width_edit, self.height_edit):
            edit.setAlignment(Qt.AlignRight)
            edit.setMinimumWidth(70)
        self.unit_box = QComboBox(self)
        for choice in ("cm", "in"):
            self.unit_box.addItem(choice, choice)
        self.unit_box.setCurrentIndex(0 if unit == "cm" else 1)
        row.addWidget(QLabel("Width", self))
        row.addWidget(self.width_edit)
        row.addWidget(QLabel("x  Height", self))
        row.addWidget(self.height_edit)
        row.addWidget(self.unit_box)
        self.keep = QCheckBox("Keep the aspect ratio", self)
        self.keep.setChecked(True)
        self.keep.setToolTip("Typing one of the two fills in the other at "
                             "the page's present proportions.")
        self.ratio_note = QLabel(self)
        self.ratio_note.setStyleSheet("color: #9a9a9a;")
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.keep)
        layout.addWidget(self.ratio_note)
        layout.addWidget(buttons)
        self.width_edit.textEdited.connect(lambda _t: self._typed("width"))
        self.height_edit.textEdited.connect(lambda _t: self._typed("height"))
        self.unit_box.currentIndexChanged.connect(self._unit_changed)
        self.setTabOrder(self.width_edit, self.height_edit)
        self._show_ratio()
        self.width_edit.setFocus(Qt.OtherFocusReason)
        self.width_edit.selectAll()

    @staticmethod
    def _read(edit):
        value = numbers.evaluate(edit.text())
        return value if value is not None and 0 < value < 1e4 else None

    def unit(self):
        return self.unit_box.currentData()

    def values(self):
        """`(width, height, unit)`, or None while either is not a length."""
        width, height = self._read(self.width_edit), self._read(
            self.height_edit)
        if width is None or height is None:
            return None
        return width, height, self.unit()

    def _typed(self, which):
        """One of the two was typed in: with the ratio kept, the other
        follows; without, the ratio does."""
        for edit in (self.width_edit, self.height_edit):
            edit.setStyleSheet("")
        source = self.width_edit if which == "width" else self.height_edit
        other = self.height_edit if which == "width" else self.width_edit
        value = self._read(source)
        if value is None:
            return
        if self.keep.isChecked():
            other.setText(_length_text(value / self._ratio if which == "width"
                                       else value * self._ratio))
        else:
            width, height = (self._read(self.width_edit),
                             self._read(self.height_edit))
            if width and height:
                self._ratio = width / height
        self._show_ratio()

    def _unit_changed(self, _index=0):
        """Both numbers converted, so switching cm and in changes nothing."""
        new = self.unit()
        if new == self._unit:
            return
        factor = 2.54 if new == "cm" else 1.0 / 2.54
        for edit in (self.width_edit, self.height_edit):
            value = self._read(edit)
            if value is not None:
                edit.setText(_length_text(value * factor))
        self._unit = new

    def _show_ratio(self):
        self.ratio_note.setText("Aspect ratio {:.4g} : 1".format(self._ratio))

    def accept(self):
        values = self.values()
        wrong = []
        if values is None:
            wrong = [e for e in (self.width_edit, self.height_edit)
                     if self._read(e) is None]
        else:
            per_cm = 1.0 if values[2] == "cm" else 2.54
            if values[0] * per_cm <= self._least_cm[0]:
                wrong.append(self.width_edit)
            if values[1] * per_cm <= self._least_cm[1]:
                wrong.append(self.height_edit)
        for edit in wrong:
            edit.setStyleSheet("border: 1px solid #d04040;")
        if wrong:
            wrong[0].setToolTip("Smaller than the margins leave room for.")
            return
        QDialog.accept(self)


class PresetSaveDialog(QDialog):
    """Save the figure's look as a style preset: a name, and whether the
    size and margins go with it (`core/presets.py`)."""

    def __init__(self, parent=None, name="", with_layout=True, taken=()):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Save a style preset")
        self._taken = set(n.lower() for n in taken)
        self.name_edit = QLineEdit(name, self)
        self.name_edit.setPlaceholderText("thesis, poster, ACS column...")
        self.with_layout = QCheckBox("With the figure's size and margins",
                                     self)
        self.with_layout.setChecked(bool(with_layout))
        self.with_layout.setToolTip(
            "Then every figure given this preset has the same axes box.")
        self.replaces = QLabel("", self)
        self.replaces.setStyleSheet("color: #d0a040;")
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("", self.with_layout)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.replaces)
        layout.addWidget(buttons)
        self.name_edit.textChanged.connect(self._name_changed)
        self._name_changed()
        self.name_edit.setFocus(Qt.OtherFocusReason)
        self.name_edit.selectAll()

    def name(self):
        return self.name_edit.text().strip()

    def _name_changed(self, _text=""):
        self.replaces.setText("Replaces the preset of that name."
                              if self.name().lower() in self._taken else "")

    def accept(self):
        if not self.name():
            self.name_edit.setStyleSheet("border: 1px solid #d04040;")
            return
        QDialog.accept(self)


def _length_text(value):
    """A length offered for editing: to the hundredth of a millimetre."""
    return "{:.4g}".format(float(value)) if float(value) >= 100 else \
        "{:.3f}".format(float(value)).rstrip("0").rstrip(".")


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
    it for the next one. A spin box has already taken its value when the
    key reaches the window; this only stops the window
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
        x, y = self._shown_values()
        self.at_x.setValue(x)
        self.at_y.setValue(y)
        self._shown = (self.at_x.value(), self.at_y.value())
        form.addRow("x, y", row)
        self._form, self._place_row = form, row

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

    def hide_anchor(self):
        """No anchor to choose: a note's text sits on its arrow."""
        label = self._form.labelForField(self.anchor)
        if label is not None:
            label.setVisible(False)
        self.anchor.setVisible(False)

    def _hanging(self):
        """A label that hangs from its curve: x and y are where it IS,
        and typing them hangs it again from there."""
        return (self.plot is not None
                and bool(getattr(self.artist, "attached", False)))

    def _free_twin(self):
        """A free copy of a hanging label, in the space chosen: the numbers
        a free label at the same spot would have (in the axis's own unit,
        whatever that is - the plot converts, not this)."""
        twin = copy.copy(self.artist)
        twin.at = None
        twin.scan = None
        twin.parent_offset = None
        twin.leader = None
        twin.vline = None
        twin.space = self.space.currentData()
        return twin

    def _shown_values(self):
        artist = self.artist
        if not self._hanging():
            return float(artist.x), float(artist.y)
        rect = self.plot.plot_rect()
        px, py = self.plot.artist_point(artist, rect)
        twin = self._free_twin()
        self.plot.set_artist_point(twin, px, py, rect, clamp=False)
        return float(twin.x), float(twin.y)

    def _hang_at_typed(self):
        twin = self._free_twin()
        twin.x, twin.y = float(self.at_x.value()), float(self.at_y.value())
        rect = self.plot.plot_rect()
        px, py = self.plot.artist_point(twin, rect)
        # Hangs from there: the point along its curve and the distance from
        # it follow (`PlotWidget._place_attached`), as a drag does.
        self.plot.set_artist_point(self.artist, px, py, rect, clamp=False)

    def hide_position(self, anchor_too=False):
        """No page position to type: a label hanging from its curve is
        placed by its point and distance instead."""
        for widget in (self.space, self._place_row) + (
                (self.anchor,) if anchor_too else ()):
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(False)
            widget.setVisible(False)

    def _space_changed(self, _index=0):
        """Convert the stored position so the artist does not jump."""
        wanted = self.space.currentData()
        if wanted != self.artist.space and self.plot is not None:
            self.plot.convert_artist_space(self.artist, wanted)
        self.at_x.blockSignals(True)
        self.at_y.blockSignals(True)
        x, y = self._shown_values()
        self.at_x.setValue(x)
        self.at_y.setValue(y)
        self._shown = (self.at_x.value(), self.at_y.value())
        self.at_x.blockSignals(False)
        self.at_y.blockSignals(False)
        self._apply()

    def _apply(self, *_args):
        self.artist.space = self.space.currentData()
        self.artist.anchor = self.anchor.currentData()
        typed = (self.at_x.value(), self.at_y.value())
        if self._hanging():
            if typed != self._shown:
                self._hang_at_typed()
                self._shown = typed
        else:
            self.artist.x = float(typed[0])
            self.artist.y = float(typed[1])
        if self.rotation is not None:
            self.artist.rotation = float(self.rotation.value())
        if self.on_change is not None:
            self.on_change()


def screen_limit(widget):
    """The tallest a settings window may be on the screen it is on, in
    pixels, or None when there is no screen to ask."""
    screen = widget.screen() if hasattr(widget, "screen") else None
    if screen is None:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    return int(screen.availableGeometry().height() * SCREEN_SHARE)


def order_rows(form, first=(), last=(), owner=None):
    """Put the rows of `form` in order: those named in `first` at the top,
    in that order, those in `last` at the bottom, the rest between them as
    they were. A key is a row's label ("Colour") or "@" and the name of
    the attribute of `owner` holding its field ("@auto"); a key with no
    row is passed over. The widgets are MOVED, never rebuilt: what they
    hold, their signals and whether they are hidden stay as they are."""
    rows = []
    while form.rowCount():
        spanning = form.itemAt(0, QFormLayout.SpanningRole) is not None
        taken = form.takeRow(0)
        label = (taken.labelItem.widget()
                 if taken.labelItem is not None else None)
        item = taken.fieldItem
        field = None
        if item is not None:
            field = (item.widget() if item.widget() is not None
                     else item.layout())
        rows.append((label, field, spanning))
    chosen = set()

    def find(key):
        for index, (label, field, _spanning) in enumerate(rows):
            if index in chosen:
                continue
            if key.startswith("@"):
                hit = (owner is not None and field is not None
                       and getattr(owner, key[1:], None) is field)
            else:
                hit = isinstance(label, QLabel) and label.text() == key
            if hit:
                chosen.add(index)
                return index
        return None

    head = [i for i in (find(key) for key in first) if i is not None]
    tail = [i for i in (find(key) for key in last) if i is not None]
    middle = [i for i in range(len(rows)) if i not in chosen]
    for index in head + middle + tail:
        label, field, spanning = rows[index]
        if field is None:
            if label is not None:
                form.addRow(label)
        elif spanning:
            form.addRow(field)
        elif label is None:
            form.addRow("", field)
        else:
            form.addRow(label, field)


def clean_path(text):
    """A path as typed or pasted: the spaces round it and the quotes
    Windows puts round a path it copies ("Copy as path", Ctrl+Shift+C)
    taken off, a file:/// link made a path; "" for nothing."""
    text = (text or "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if text.lower().startswith("file:"):
        from PySide6.QtCore import QUrl
        text = QUrl(text).toLocalFile() or text
    return os.path.normpath(text) if text else ""


class SourceRow(QWidget):
    """A file's path in its settings (and its curves'): another one typed
    or pasted - the quotes Windows adds are dropped as it is pasted - and
    Enter, or found with Browse... It takes the file's place through the
    window (`_LiveDialog._source_chosen`, "Change the source file"); a
    path that is not a file is marked, and nothing happens."""

    chosen = Signal(str)

    def __init__(self, sample, parent=None):
        QWidget.__init__(self, parent)
        self.sample = sample
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit(sample.path)
        self.path.setToolTip(
            "The file it is read from. Type or paste another path (the "
            "quotes of Copy as path are dropped) and press Enter, or Browse: "
            "it takes this file's place - its curves keep their place, "
            "colour and labels. One undo step.")
        # Wide enough for the whole path (within reason), its start shown.
        self.path.setMinimumWidth(min(560, self.path.fontMetrics(
        ).horizontalAdvance(sample.path) + 24))
        self.path.setCursorPosition(0)
        self.browse = QPushButton("Browse...")
        self.browse.setToolTip("Find another file to take this one's place.")
        line.addWidget(self.path, 1)
        line.addWidget(self.browse)
        self._busy = False
        self.path.textChanged.connect(self._tidy)
        self.path.editingFinished.connect(self._typed)
        self.browse.clicked.connect(lambda _c=False: self._browse())

    def _tidy(self, text):
        """Quotes round a pasted path go at once."""
        bare = text.strip()
        if len(bare) >= 2 and bare[0] == bare[-1] and bare[0] in "\"'":
            self.path.blockSignals(True)
            self.path.setText(bare[1:-1].strip())
            self.path.blockSignals(False)

    def _typed(self):
        if self._busy:
            return
        path = clean_path(self.path.text())
        same = path and os.path.normcase(os.path.abspath(path)) == \
            os.path.normcase(os.path.abspath(self.sample.path))
        if not path or same:
            self.path.setStyleSheet("")
            return
        if not os.path.isfile(path):
            self.path.setStyleSheet("border: 1px solid #d04040;")
            self.path.setToolTip("No such file: {}".format(path))
            return
        self.path.setStyleSheet("")
        self._busy = True
        try:
            self.chosen.emit(path)
        finally:
            self._busy = False

    def _browse(self):
        window = _window_of(self)
        path = window.ask_source_path(self.sample) if window else ""
        if path:
            self.path.setText(os.path.normpath(path))
            self._typed()


class _LiveDialog(QDialog):
    """Common machinery: snapshot on open, restore on reject.

    One dialog can edit SEVERAL objects of its kind at once (`set_group`:
    select three onsets, open the settings, set the size of all three). It
    shows the object it was opened on and MIRRORS every change onto the
    others: whatever field of the shown object just
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
    #: True for an object with a place in the figure's stack: its window
    #: gets a Layer field (`_layer_row`), and its z is in FIELDS.
    LAYERED = False
    #: The order of the rows, top to bottom (Christian, 2026-10-05): what
    #: is most likely changed after the object is made, and what only this
    #: window can change, first - its text, its colour, the values typed
    #: here - then sizes and style; `LAST_ROWS` (Show, Layer: H, the
    #: outliner and Ctrl+PgUp do those too) at the bottom. A key is a
    #: row's label ("Colour") or "@" and the attribute holding its field
    #: ("@auto"); a key with no row is passed over, and the rows not named
    #: keep their order between the two. Applied by `_buttons`, which
    #: every window calls last (`order_rows`).
    FIRST_ROWS = ()
    LAST_ROWS = ()

    def __init__(self, parent, obj, on_change=None):
        QDialog.__init__(self, parent)
        if self.LAYERED and "z" not in type(self).FIELDS:
            self.FIELDS = tuple(type(self).FIELDS) + ("z",)
        # A colour that follows another's (`colour_from`) reverts and
        # undoes with the colour.
        if "colour" in self.FIELDS and "colour_from" not in self.FIELDS:
            self.FIELDS = tuple(self.FIELDS) + ("colour_from",)
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
        # goes wrong when adjusting an analysis. `Qt.Tool` keeps it above
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
        problem under its label - was cut off. Never past `SCREEN_SHARE` of
        the screen's height: beyond that the rows scroll
        (`_scroll_rows`)."""
        layout = self.layout()
        if layout is None:
            return
        if getattr(self, "_rows_area", None) is not None:
            self._fit_scrolled()
            return
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.activate()
        needed = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else self.sizeHint().height())
        limit = screen_limit(self)
        if limit is not None and needed > limit:
            self._scroll_rows()
            self._fit_scrolled()
            return
        if needed > self.height():
            self.resize(self.width(), needed)

    def _scroll_rows(self):
        """Put the rows in a scroll area, keeping the buttons (the last
        row, when it is a button box) below it, always in view."""
        layout = self.layout()
        buttons = None
        last = layout.itemAt(layout.count() - 1) if layout.count() else None
        if last is not None and isinstance(last.widget(), QDialogButtonBox):
            buttons = last.widget()
            layout.removeWidget(buttons)
        inner = QWidget()
        # Takes the layout, and its widgets, off this dialog.
        inner.setLayout(layout)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(area, 1)
        if buttons is not None:
            row = QHBoxLayout()
            row.setContentsMargins(9, 0, 9, 9)
            row.addWidget(buttons)
            outer.addLayout(row)
        self._rows_area = area
        self._rows_inner = inner
        # `fit` had pinned this window's minimum to the rows' full height
        # (SetMinimumSize on the layout now inside the area): let it go.
        self.setMinimumSize(0, 0)

    def _fit_scrolled(self):
        limit = screen_limit(self) or 600
        inner = self._rows_inner
        needed = inner.sizeHint().height() + 60
        bar = self._rows_area.verticalScrollBar().sizeHint().width()
        width = max(self.width(), inner.sizeHint().width() + bar + 4)
        self.resize(width, min(limit, needed))

    def reject(self):
        """Closed without OK - its X, Esc, Ctrl+W: KEEP what was changed.

        These apply as they are touched, and a change is a change.
        Putting everything back on closing would, after a minute of
        adjusting by eye, be exactly the loss nobody expects. Only the
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

    def _layer_row(self, form):
        """Layer: where the object is drawn in the stack, as a number -
        the same order Ctrl+PgUp and Ctrl+PgDown move it in."""
        self.layer = NumberBox()
        self.layer.setDecimals(1)
        self.layer.setRange(-10000.0, 10000.0)
        self.layer.setSingleStep(1.0)
        self.layer.setValue(float(units_module.z_of(self.obj)))
        self.layer.setToolTip("Higher is drawn on top. Ctrl+PgUp / PgDn "
                              "move it one place.")
        form.addRow("Layer", self.layer)
        self.layer.valueChanged.connect(self._set_layer)

    def _set_layer(self, value):
        self.obj.z = float(value)
        self._live()

    def _buttons(self):
        """OK and Revert. OK closes; Revert undoes this dialog and closes.

        Also where a window for an object in the stack gets its Layer row,
        at the end of its form: every such window builds its buttons last."""
        if self.LAYERED and not hasattr(self, "layer"):
            forms = self.findChildren(QFormLayout)
            if forms:
                self._layer_row(forms[0])
        self._order_rows()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        revert = buttons.button(QDialogButtonBox.Cancel)
        revert.setText("Revert")
        revert.setToolTip("Undo this window's changes and close. "
                          "Closing otherwise keeps them.")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.revert)
        return buttons

    def _source_chosen(self, path):
        """Another file in this one's place (`MainWindow.change_source`,
        its own undo step). This window closes FIRST - its step lands
        before the change - and opens again on the new file, every row of
        which may differ (its wavelength, its points, its title)."""
        window = _window_of(self)
        if window is None:
            return
        obj = self.obj
        sample = getattr(obj, "sample", obj)
        self.accept()
        window.change_source(sample, path)
        window.edit_object(obj)

    def row_order(self):
        """`(first, last)`, the keys `_order_rows` puts at the top and the
        bottom; a window whose order depends on its object overrides it."""
        return self.FIRST_ROWS, self.LAST_ROWS

    def _order_rows(self):
        first, last = self.row_order()
        if not first and not last:
            return
        forms = self.findChildren(QFormLayout)
        if forms:
            order_rows(forms[0], first, last, self)

    def snapshot(self):
        """What the object looked like when this opened, for the undo step."""
        return dict(self._snapshot)

    def snapshots(self):
        """`[(obj, {field: value when opened}), ...]` for every object this
        dialog edits, the shown one first."""
        return ([(self.obj, dict(self._snapshot))]
                + [(o, dict(saved)) for o, saved in self._group_snapshots])


class _HexBox(QLineEdit):
    """A colour as #rrggbb, to copy and paste between windows: a click
    selects all of it."""

    def focusInEvent(self, ev):
        QLineEdit.focusInEvent(self, ev)
        QTimer.singleShot(0, self.selectAll)


def _donor_name(obj):
    if hasattr(obj, "display_name"):
        return obj.display_name()
    text = getattr(obj, "text", None) or getattr(obj, "name", "")
    return "\"{}\"".format(text) if text else type(obj).__name__.lower()


def _colour_button(parent, get_colour, set_colour):
    """A colour row of a settings window: the swatch (the picker, dropper
    and all); the colour as #rrggbb right beside it, to copy, or to paste
    one in and press Enter, without opening anything; and, for the
    object's own colour, INHERIT - the next click on the figure names an
    object whose colour this one then FOLLOWS (`model.sync_colours`,
    saved with the session). Choosing a colour of its own ends that."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    button = QPushButton(row)
    button.setFixedWidth(64)
    hex_box = _HexBox(row)
    hex_box.setFixedWidth(84)
    hex_box.setToolTip("The colour as #rrggbb: copy it, or paste one in "
                       "and press Enter.")
    obj = getattr(parent, "obj", None)
    # Only the object's OWN colour follows (not, say, a note's arrow).
    follows = (obj is not None and hasattr(obj, "colour")
               and getattr(parent, "_set_colour", None) == set_colour)
    inherit = QPushButton("Inherit...", row) if follows else None
    layout.addWidget(button)
    layout.addWidget(hex_box)
    if inherit is not None:
        layout.addWidget(inherit)
    layout.addStretch(1)
    # core/model.py, imported here under that name
    doc_model = units_module

    def refresh():
        colour = QColor(get_colour())
        button.setStyleSheet(
            "background: {}; border: 1px solid #555;".format(colour.name()))
        if not hex_box.hasFocus():
            hex_box.setText(colour.name())
        if inherit is not None:
            donor = getattr(obj, "colour_from", None)
            inherit.setText("Inherits" if donor is not None
                            else "Inherit...")
            inherit.setToolTip(
                "Follows the colour of {} - click to stop following."
                .format(_donor_name(donor)) if donor is not None else
                "Click, then click the object on the figure whose colour "
                "this one follows from now on.")

    def own(name):
        """A colour of its own: no longer another's."""
        if follows:
            obj.colour_from = None
        set_colour(name)

    def live(name):
        own(name)
        refresh()

    def pick():
        # Live: the figure follows the wheel. Revert puts the colour back,
        # and a "Follow the theme" / "Same as scan" that was ticked.
        auto = getattr(parent, "auto", None)
        was_auto = auto is not None and auto.isChecked()
        colour = pick_colour(QColor(get_colour()), parent, "Pick a colour",
                             live=live)
        if colour.isValid():
            own(colour.name())
        elif was_auto:
            auto.setChecked(True)
        refresh()

    def typed():
        text = hex_box.text().strip()
        if text and not text.startswith("#"):
            text = "#" + text
        colour = QColor(text)
        if colour.isValid() and len(text) in (4, 7) and \
                colour.name() != QColor(get_colour()).name():
            own(colour.name())
        refresh()

    def inherit_clicked():
        if getattr(obj, "colour_from", None) is not None:
            obj.colour_from = None          # keeps the colour it has
            parent._live()
            refresh()
            return
        plot = getattr(parent.parentWidget(), "plot", None)
        if plot is None:
            return

        def chosen(donor):
            if (donor is None or donor is obj or not hasattr(donor, "colour")
                    or doc_model.inherits_from(donor, obj)):
                return
            obj.colour_from = donor
            colour = doc_model.own_colour(donor)
            if colour is not None:
                set_colour(colour)
            else:
                parent._live()
            refresh()

        plot.pick_object(chosen, "INHERIT a colour: click the object it "
                                 "follows - Esc gives up")

    button.clicked.connect(lambda _c=False: pick())
    hex_box.editingFinished.connect(typed)
    if inherit is not None:
        inherit.clicked.connect(lambda _c=False: inherit_clicked())
    refresh()
    row.swatch, row.hex, row.inherit = button, hex_box, inherit
    return row


class ScanSettings(_LiveDialog):
    """Everything about one scan, plus its sample's molar mass."""

    FIELDS = ("colour", "label", "offset", "line_width", "keep",
              "dtg_window")
    INDIVIDUAL = ("label", "offset")
    GROUP_DISABLED = ("label", "offset", "molar", "analyses",
                      "file_row")

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

        # A DTG's smoothing: the window of the local slope, in kelvin of
        # the ramp (`core/dtg.py`). Only a DTG has one.
        self.dtg_window = NumberBox()
        self.dtg_window.setDecimals(1)
        self.dtg_window.setRange(0.0, 100.0)
        self.dtg_window.setSingleStep(0.5)
        self.dtg_window.setSuffix(" K")
        self.dtg_window.setValue(float(getattr(scan, "dtg_window", 0.0)))
        self.dtg_window.setToolTip("Smoothing window of the derivative, in "
                                   "kelvin of the ramp. 0 is none.")
        self.dtg_window.valueChanged.connect(lambda _v: self._apply())
        if getattr(scan, "is_dtg", False):
            form.addRow("Smoothing", self.dtg_window)
        else:
            self.dtg_window.setVisible(False)

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
        sample = scan.sample
        self.file_row = SourceRow(sample, self)
        self.file_row.chosen.connect(self._source_chosen)
        form.addRow("File", self.file_row)

        # ------------------------------------------------- the molar mass
        sample = scan.sample
        if not sample.mass_g:
            said = "not in the file"
        elif sample.mass_source == "derived from the weight":
            said = sample.mass_text()
        else:
            said = "{:g} mg (from the file)".format(sample.mass_g * 1000.0)
        form.addRow("Sample mass", QLabel(said))

        self.molar = NumberBox()
        self.molar.setDecimals(4)
        self.molar.setRange(0.0, 1e7)
        self.molar.setSpecialValueText("not given")
        self.molar.setSuffix(" g/mol")
        self.molar.setValue(float(scan.sample.molar_mass or 0.0))
        self.molar.setToolTip("Needed for W/mol and kJ/mol. Never "
                              "assumed. Every scan of the file has it.")
        form.addRow("Molar mass", molar_row(self, self.molar, scan.sample))

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.label.textChanged.connect(self._apply)
        for box in (self.offset, self.molar):
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
        if getattr(scan, "is_dtg", False):
            scan.dtg_window = float(self.dtg_window.value())
        scan.sample.molar_mass = (float(self.molar.value())
                                  if self.molar.value() > 0 else None)
        scan._cache_key = None
        self._live()

    def revert(self):
        self.obj.sample.molar_mass = self._sample_molar_mass
        _LiveDialog.revert(self)


def molar_row(dialog, box, sample):
    """A molar mass box with its calculator beside it."""
    row = QWidget(dialog)
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addWidget(box, 1)
    button = QPushButton("Calculate...", row)
    button.setAutoDefault(False)
    button.setToolTip("From a sum formula, a SMILES or a composition "
                      "(Hbc)0.75+Zn(im)1.70(bim)0.30.")

    def calculate(_checked=False):
        calculator = MolarMassDialog(sample.composition or "", dialog)
        if calculator.exec() and calculator.mass() is not None:
            sample.composition = calculator.text() or None
            box.setValue(round(calculator.mass(), 4))

    button.clicked.connect(calculate)
    line.addWidget(button, 0)
    dialog.calculate_molar = calculate
    return row


class MolarMassDialog(QDialog):
    """The molar mass calculator: a sum formula (C6H6), a SMILES, or a
    composition of (key)coefficient parts joined by +, read the way that
    fits or as chosen, with the formula and the mass shown as it is typed.
    `core/molar.py` does the chemistry."""

    def __init__(self, text="", parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Molar mass")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.entry = QLineEdit(text, self)
        self.entry.setPlaceholderText("C6H6, O=C(O)c1ccccc1, or "
                                      "(Hbc)0.75+Zn(im)1.70(bim)0.30")
        self.entry.setToolTip("A sum formula (brackets, decimals, * for an "
                              "adduct), a SMILES, or a composition: "
                              "(key)coefficient parts joined by +.")
        form.addRow("From", self.entry)
        self.reading = QComboBox(self)
        for name in molar.READINGS:
            self.reading.addItem(molar.TITLES[name], name)
        self.reading.setToolTip("CO is carbon monoxide as a formula and "
                                "methanol as a SMILES: choose when it "
                                "matters.")
        form.addRow("Read as", self.reading)
        self.formula = QLabel("", self)
        self.formula.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Formula", self.formula)
        self.mass_text = QLabel("", self)
        self.mass_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Molar mass", self.mass_text)
        blocks = QLabel("Building blocks: " + ", ".join(
            molar.BUILDING_BLOCKS), self)
        blocks.setWordWrap(True)
        blocks.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(blocks)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        self.use = buttons.button(QDialogButtonBox.Ok)
        self.use.setText("Use")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.entry.textChanged.connect(lambda _t: self.work_out())
        self.reading.currentIndexChanged.connect(lambda _i: self.work_out())
        self._found = None
        self.work_out()
        self.resize(460, self.sizeHint().height())

    def text(self):
        return self.entry.text().strip()

    def work_out(self):
        text = self.text()
        if not text:
            self._found = None
            self.formula.setText("")
            self.mass_text.setText("")
            self.use.setEnabled(False)
            return None
        found = molar.calculate(text, self.reading.currentData())
        self._found = found
        if found.ok:
            self.formula.setText("{}  (read as {})".format(
                found.formula, molar.TITLES.get(found.read, found.read)))
            self.formula.setStyleSheet("")
            self.mass_text.setText("{:.2f} g/mol".format(found.mass))
        else:
            self.formula.setText(found.error or "")
            self.formula.setStyleSheet("color: #d04040;")
            self.mass_text.setText("")
        self.use.setEnabled(found.ok)
        return found

    def mass(self):
        found = self._found
        return found.mass if found is not None and found.ok else None


class _MarginsDialog(QDialog):
    """Four margins in numbers, left / right / top / bottom: the page's
    white margins or the data's inside the axes box. Built here, shown and
    applied by the window, one undo step."""

    TITLE = "Margins"
    SIDES = (("left", "Left"), ("right", "Right"), ("top", "Top"),
             ("bottom", "Bottom"))

    def __init__(self, values, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(self.TITLE)
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self.boxes = {}
        for side, words in self.SIDES:
            box = NumberBox(self)
            self._shape(box, side)
            box.setValue(float(values.get(side, 0.0)))
            box.valueChanged.connect(lambda _v: self._check())
            self.form.addRow(words, box)
            self.boxes[side] = box
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._extra(self.buttons)
        layout.addWidget(self.buttons)
        self._check()

    def _shape(self, box, side):
        pass

    def _extra(self, buttons):
        pass

    def _check(self):
        return True

    def values(self):
        return dict((side, float(box.value()))
                    for side, box in self.boxes.items())


class PageMarginsDialog(_MarginsDialog):
    """The page's white margins of an exact figure, in its unit, each no
    less than what it holds. More white space grows the page; the axes box
    keeps its size."""

    TITLE = "Page margins"

    def __init__(self, values, least, unit, parent=None):
        self.least = dict(least)
        self.unit = unit
        _MarginsDialog.__init__(self, values, parent)
        tighten = self.buttons.button(QDialogButtonBox.Reset)
        tighten.clicked.connect(lambda _c=False: self.tighten())
        self.note.setText("White space round the axes box. More grows the "
                          "page, less shrinks it; the axes box keeps its "
                          "size. Each is at least what it holds.")

    def _shape(self, box, side):
        box.setDecimals(2)
        box.setRange(float(self.least.get(side, 0.0)), 1000.0)
        box.setSingleStep(0.05)
        box.setSuffix(" " + self.unit)
        box.setToolTip("At least {:.2f} {}: less would cut off what it "
                       "holds.".format(self.least.get(side, 0.0), self.unit))

    def _extra(self, buttons):
        buttons.addButton(QDialogButtonBox.Reset).setText("Tighten")
        buttons.button(QDialogButtonBox.Reset).setToolTip(
            "Every margin down to what it holds.")

    def tighten(self):
        for side, box in self.boxes.items():
            box.setValue(float(self.least.get(side, 0.0)))


class DataMarginsDialog(_MarginsDialog):
    """The data's margins inside the axes box: the share of the axis left
    empty beyond the data on each side (the fit-margin arrows'). Two on one
    axis must leave the data some room."""

    TITLE = "Data margins"

    def _shape(self, box, side):
        box.setDecimals(3)
        box.setRange(0.0, 0.9)
        box.setSingleStep(0.01)
        box.setToolTip("The share of the axis left empty beyond the data: "
                       "0.1 is 10 %.")

    def _check(self):
        values = self.values()
        fine = (values["left"] + values["right"] < style.FIT_MOST
                and values["bottom"] + values["top"] < style.FIT_MOST)
        for pair in (("left", "right"), ("bottom", "top")):
            bad = sum(values[s] for s in pair) >= style.FIT_MOST
            for side in pair:
                self.boxes[side].setStyleSheet(
                    "border: 1px solid #d04040;" if bad else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(fine)
        self.note.setText("The share of each axis left empty beyond the "
                          "data: left 0.1 is the first tenth of the x "
                          "axis." if fine else
                          "Two margins of one axis leave the data no room.")
        return fine


class MolarMassPrompt(QDialog):
    """"Set the molar mass" (F3, a scan's menu): the number, and the
    calculator beside it."""

    def __init__(self, samples, parent=None):
        QDialog.__init__(self, parent)
        self.samples = list(samples)
        self.setWindowTitle("Molar mass")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        form.addRow("For", QLabel(", ".join(s.name for s in self.samples)))
        self.molar = NumberBox(self)
        self.molar.setDecimals(4)
        self.molar.setRange(0.0, 1e7)
        self.molar.setSpecialValueText("not given")
        self.molar.setSuffix(" g/mol")
        self.molar.setValue(float(self.samples[0].molar_mass or 0.0))
        self.molar.setToolTip("Needed for W/mol and kJ/mol. Never assumed.")
        form.addRow("Molar mass", molar_row(self, self.molar,
                                            self.samples[0]))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        value = float(self.molar.value())
        return value if value > 0 else None


class SampleSettings(_LiveDialog):
    """The substance: its molar mass, and which way its arrays point."""

    FIELDS = ("molar_mass", "exo")

    def __init__(self, parent, sample, on_change=None):
        _LiveDialog.__init__(self, parent, sample, on_change)
        self.setWindowTitle("Sample: {}".format(sample.name))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.file_row = SourceRow(sample, self)
        self.file_row.chosen.connect(self._source_chosen)
        form.addRow("File", self.file_row)
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
        self.molar.setToolTip("Needed for W/mol and kJ/mol. Never "
                              "assumed. Every scan of the file has it.")
        form.addRow("Molar mass", molar_row(self, self.molar, sample))

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


def axis_title(axis, part=""):
    """"X axis", "Y axis numbers", "Mass axis caption": the windows of an
    axis, the mass axis by its name rather than "Y2"."""
    name = ("Mass axis" if axis.which == "y2"
            else "{} axis".format(axis.which.upper()))
    return "{} {}".format(name, part) if part else name


class _SideRow(object):
    """"Side" in every window of an axis - its spine's, its numbers' and
    its caption's, so a double-click on the y caption offers one too. It
    shows the side the axis is DRAWN on and puts it on the one chosen,
    through the window: the mass axis takes the heat
    flow axis's side, so choosing its side changes that one."""

    def _side_row(self, form):
        axis = self.obj
        self.side = QComboBox()
        for side in (("bottom", "top") if axis.which == "x"
                     else ("left", "right")):
            self.side.addItem(side, side)
        plot = _plot_of(self)
        drawn = plot.axis_side(axis) if plot is not None else axis.side
        self.side.setCurrentIndex(max(0, self.side.findData(drawn)))
        self.side.setToolTip("Which side of the plot the axis is on: its "
                             "line, numbers and caption.")
        form.addRow("Side", self.side)
        self.side.currentIndexChanged.connect(lambda _i: self._side_chosen())

    def _side_chosen(self):
        window = _window_of(self)
        if window is not None:
            window.set_axis_side(self.obj, self.side.currentData())


class CaptionSettings(_SideRow, _LiveDialog):
    """An axis CAPTION: its words and its size, and nothing else.

    Separate from the axis's own settings on purpose: the tick settings
    should not be what a double-click on the label gives you - the
    label is a piece of text, the spine is the axis. Double-clicking the
    spine opens `AxisSettings`; this is what the caption opens.
    """

    FIELDS = ("label", "label_size", "label_along", "label_gap", "visible")
    INDIVIDUAL = ("label", "label_along")
    GROUP_DISABLED = ("label",)

    #: The order of its rows (`_LiveDialog.FIRST_ROWS`).
    FIRST_ROWS = ("Text", "@own_text", "Shows", "Size", "Distance", "Side")
    LAST_ROWS = ("@shown",)

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle(axis_title(axis, "caption"))
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
        self._side_row(form)

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


def axis_unit(doc, axis):
    """The unit an axis's numbers are in, for its range boxes."""
    if doc is None:
        return ""
    if axis.which == "x":
        if doc.x_axis != units_module.AXIS_TEMPERATURE:
            return "min"
        return units.TEMPERATURE_LABEL.get(doc.x_unit, doc.x_unit)
    if axis.which == "y2":
        return doc.weight_unit
    return doc.y_axis_unit()


class _RangeRows(object):
    """The Range and Locked rows of an axis's settings."""

    def _show_range(self):
        plot = _plot_of(self)
        shown = plot is not None and self.obj.which in plot.shown_view_axes()
        for widget in (self.low, self.high, self.locked):
            widget.setEnabled(shown)
            widget.blockSignals(True)
        if shown:
            lo, hi = plot.view_of(self.obj.which)
            self.low.setValue(float(lo))
            self.high.setValue(float(hi))
            self.locked.setChecked(plot.lock_of(self.obj.which) is not None)
        for widget in (self.low, self.high, self.locked):
            widget.blockSignals(False)

    def _typed_range(self):
        window = _window_of(self)
        lo, hi = float(self.low.value()), float(self.high.value())
        ok = hi > lo and window is not None and window.set_axis_range(
            self.obj, lo, hi)
        for box in (self.low, self.high):
            box.setStyleSheet("" if ok else "border: 1px solid #d04040;")
        if ok:
            self._show_range()

    def _lock_toggled(self, on):
        window = _window_of(self)
        if window is None:
            return
        if on:
            window.lock_axis(self.obj, float(self.low.value()),
                             float(self.high.value()))
        else:
            window.lock_axis(self.obj, False)
        self._show_range()


class AxisSettings(_SideRow, _RangeRows, _LiveDialog):
    """The SPINE: its side, its ticks and their steps, the line opposite it,
    and the grid. Opened by double-clicking the axis line; its numbers
    (`NumberSettings`) and its caption (`CaptionSettings`) have their own
    windows.

    The defaults are Origin's closed frame on the DSC_Plotter template's
    ticks: inward, minor ticks, the opposite line with ticks and no numbers,
    no grid.
    """

    FIELDS = ("ticks_inward", "tick_length", "minor_ticks",
              "minor_count", "minor_length", "major_step", "mirror",
              "mirror_ticks", "show_grid")

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle(axis_title(axis))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        # The RANGE, its minimum and maximum: what the axis shows now,
        # typed back as one view step; locked, F returns to it. Through the
        # window, never this dialog's snapshot.
        self.low = NumberBox()
        self.high = NumberBox()
        unit = axis_unit(doc, axis)
        for box in (self.low, self.high):
            box.setDecimals(4)
            box.setRange(-1e9, 1e9)
            if unit:
                box.setSuffix(" " + unit)
        self.low.setToolTip("The axis's minimum. A sum works: 50-10.")
        self.high.setToolTip("The axis's maximum.")
        range_row = QWidget(self)
        range_line = QHBoxLayout(range_row)
        range_line.setContentsMargins(0, 0, 0, 0)
        range_line.addWidget(self.low, 1)
        range_line.addWidget(QLabel("to"), 0)
        range_line.addWidget(self.high, 1)
        form.addRow("Range", range_row)
        self.locked = QCheckBox("Locked: F returns to this range")
        self.locked.setToolTip("Unticked, F fits the data.")
        form.addRow("", self.locked)
        self._show_range()
        self.low.valueChanged.connect(lambda _v: self._typed_range())
        self.high.valueChanged.connect(lambda _v: self._typed_range())
        self.locked.toggled.connect(self._lock_toggled)

        self._side_row(form)

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
        self.minor_count = WholeBox()
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
        if axis.which == "y2":
            # The mass axis alone closes the box like any y axis; with the
            # heat flow's drawn too, the far side is that axis's own.
            self.mirror.setToolTip("While it is the only y axis: the line "
                                   "on the other side, closing the box.")

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
        # Each axis its OWN range: the weight axis showed the heat flow's
        # step (0.1 W/g where it draws 5 %), and unticking Automatic
        # stored it.
        lo, hi = {"x": plot.view_x, "y2": plot.view_y2}.get(
            axis.which, plot.view_y)()
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


class NumberSettings(_SideRow, _LiveDialog):
    """An axis's NUMBERS: shown or not, their size, their format, and
    which of them are left out. Opened by double-clicking them; the spine
    and the caption have their own."""

    FIELDS = ("show_numbers", "tick_size", "number_format",
              "hidden_numbers", "hidden_context")
    # Values in one axis's unit: never copied to another axis.
    INDIVIDUAL = ("hidden_numbers", "hidden_context")
    GROUP_DISABLED = ("hidden_numbers",)

    def __init__(self, parent, axis, doc, on_change=None):
        _LiveDialog.__init__(self, parent, axis, on_change)
        self.doc = doc
        self.setWindowTitle(axis_title(axis, "numbers"))
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
        # The general tooltip speaks of units, which an axis's numbers
        # cannot carry (the unit is in the caption).
        self.number_format.edit.setToolTip(
            "How every number on this axis is written. %.0f: whole "
            "numbers (50). %.1f: one decimal (50.0). %.2f: two. %.2g: two "
            "significant figures (0.51, 1.2, 15). Empty: as few digits as "
            "the spacing of the ticks needs.")
        form.addRow("Format", self.number_format)
        #: What the axis writes now, with this format and without the
        #: hidden ones: the Format box's effect, seen before looking at
        #: the plot.
        self.written = QLabel(self)
        self.written.setWordWrap(True)
        form.addRow("Written", self.written)

        self.hidden_numbers = QLineEdit(self)
        self.hidden_numbers.setPlaceholderText("none")
        self.hidden_numbers.setToolTip(
            "Numbers NOT written on this axis - their ticks stay. Type "
            "them as the axis writes them, separated by ';', ', ' or a "
            "space: \"50\" leaves the 50 at the corner of the box out. "
            "Right-click a number on the plot to hide or show that one.")
        self._show_hidden()
        form.addRow("Hidden", self.hidden_numbers)
        self._side_row(form)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.shown.toggled.connect(self._apply)
        self.tick_size.changed.connect(self._apply)
        self.number_format.changed.connect(self._apply)
        self.hidden_numbers.textEdited.connect(self._hidden_typed)
        self._show_written()

    def _context(self):
        plot = _plot_of(self)
        return (plot.axis_context(self.obj.which) if plot is not None
                else None)

    def _show_hidden(self):
        """The hidden numbers that apply in the axis's unit now."""
        axis = self.obj
        values = (axis.hidden_numbers
                  if list(axis.hidden_context or []) == (self._context()
                                                         or [])
                  else [])
        self.hidden_numbers.setText("; ".join(
            "{:g}".format(round(float(v), 10) + 0.0) for v in values))

    def _show_written(self):
        plot = _plot_of(self)
        if plot is None or not self.obj.show_numbers:
            self.written.setText("(none)" if not self.obj.show_numbers
                                 else "")
            return
        texts = [text for _v, _at, text in plot.numbered_ticks(self.obj)]
        self.written.setText(", ".join(texts) or "(none)")

    def _apply(self, *_args):
        axis = self.obj
        axis.show_numbers = bool(self.shown.isChecked())
        axis.tick_size = self.tick_size.value()
        axis.number_format = self.number_format.value()
        self._live()
        self._show_written()

    def _hidden_typed(self, text):
        """Only when typed here: numbers hidden in another unit are kept
        while the rest of the window is used."""
        typed = numbers.values(text)
        if typed is None:
            self.hidden_numbers.setStyleSheet("border: 1px solid #d04040;")
            return
        self.hidden_numbers.setStyleSheet("")
        axis = self.obj
        # Replaced, never changed in place (the snapshot).
        axis.hidden_numbers = sorted(typed)
        axis.hidden_context = self._context() if typed else None
        self._live()
        self._show_written()


class FigureSettings(_LiveDialog):
    """This figure's size and the place of its axes box - saved with it.

    Two session files (first up-scans, second up-scans) exported
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

        self.dpi = WholeBox()
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
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.unit.currentIndexChanged.connect(self._unit_changed)

    def _mode_changed(self, *_args):
        """Going EXACT takes its numbers from the screen
        (`exact_from_screen`), not from the stored size, so the figure keeps
        its look: the stored one set every text out of proportion."""
        fig = self.obj
        wanted = self.mode.currentData()
        if (wanted == figure_module.MODE_SIZE and fig.mode != wanted
                and self.plot is not None and self.plot.doc is not None):
            for name, value in self.plot.exact_from_screen().items():
                setattr(fig, name, value)
            fig.mode = wanted
            fig.grown = {}
            self._live()
            self._show()
            return
        self._apply()

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
                         "needs {:.2f} {}: something drawn there will be "
                         "cut off.".format(side, have * to_unit, fig.unit,
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
              "anchor", "rotation", "leader", "leader_from", "leader_colour",
              "flush", "vline", "line_dashed", "at", "dx", "dy")
    INDIVIDUAL = ("text", "x", "y", "space", "leader", "vline", "at", "dx",
                  "dy")
    GROUP_DISABLED = ("text", "transform.space", "transform.at_x",
                      "transform.at_y")

    def __init__(self, parent, label, on_change=None):
        # A label that has followed its scan shows where it IS, not where
        # it was put (`PlotWidget.rebase`; nothing moves).
        plot = getattr(parent, "plot", None)
        if plot is not None:
            plot.rebase(label)
        _LiveDialog.__init__(self, parent, label, on_change)
        self.setWindowTitle("Label")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        # Several lines: Enter breaks one, Tab goes on to the next field.
        self.text = QPlainTextEdit(label.text)
        self.text.setTabChangesFocus(True)
        self.text.setFixedHeight(3 * self.fontMetrics().lineSpacing() + 14)
        self.text.setToolTip("*T* italic, _{g} subscript, \\Delta Greek, "
                             "LaTeX between $...$. Enter starts a new line.")
        form.addRow("Text", self.text)

        self.text_size = _style_number(self, label, "size")
        form.addRow("Size", self.text_size)

        self.bold = QCheckBox("Bold")
        self.bold.setChecked(bool(label.bold))
        form.addRow("", self.bold)

        self.transform = ArtistTransform(label, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        # A label that belongs to a scan hangs from its curve:
        # where along it, and how far from it - an analysis label's rows.
        self.hang_at = QLineEdit(self)
        self.hang_at.setToolTip("The temperature on its curve it hangs "
                                "from. 98 is in the axis unit; 98 F, 371 K "
                                "convert.")
        self.hang_dy = NumberBox()
        self.hang_dx = NumberBox()
        for box in (self.hang_dy, self.hang_dx):
            box.setDecimals(1)
            box.setRange(-2000.0, 2000.0)
            box.setSuffix(" px")
        self.hang_dy.setToolTip("How far above the curve (below: "
                                "negative). Drag it up and down.")
        self.hang_dx.setToolTip("How far to the right of its point.")
        form.addRow("On the curve at", self.hang_at)
        form.addRow("Distance", self.hang_dy)
        form.addRow("Sideways", self.hang_dx)
        self._hang_rows = (self.hang_at, self.hang_dy, self.hang_dx)
        self._show_hang()
        self.hang_at.editingFinished.connect(self._typed_hang_at)
        self.hang_dy.valueChanged.connect(self._typed_hang)
        self.hang_dx.valueChanged.connect(self._typed_hang)

        form.addRow("Colour", _colour_button(
            self, lambda: (label.colour if label.colour != "auto"
                           else label.scan.colour if label.scan is not None
                           else "#cccccc"), self._set_colour))
        # Automatic is its curve's colour for a label that belongs to one
        # (`PlotWidget.label_colour`), the theme's ink for a free one -
        # and says which.
        self.auto = QCheckBox("Same as parent" if label.scan is not None
                              else "Follow the theme")
        self.auto.setToolTip("The colour of the curve it belongs to."
                             if label.scan is not None
                             else "The theme's ink.")
        self.auto.setChecked(label.colour in (None, "", "auto"))
        form.addRow("", self.auto)

        # A NOTE is a label with an arrow to a point.
        self.leader = QCheckBox("Leader arrow (a note)")
        self.leader.setChecked(bool(label.leader))
        self.leader.setToolTip("An arrow from the text to a point. Select "
                               "the note and drag the ring at its tip; near "
                               "a curve it snaps onto it.")
        form.addRow("", self.leader)

        # The point it names, typed, as well as the text's place.
        tip = QWidget(self)
        row = QHBoxLayout(tip)
        row.setContentsMargins(0, 0, 0, 0)
        self.tip_x = QLineEdit(self)
        self.tip_x.setToolTip("The temperature it points at. 98 is in the "
                              "axis unit; 98 F, 371 K convert.")
        self.tip_y = QLineEdit(self)
        self.tip_y.setToolTip("The height it points at, in its axis's "
                              "unit.")
        self.tip_unit = QLabel("", self)
        row.addWidget(self.tip_x)
        row.addWidget(QLabel("at", self))
        row.addWidget(self.tip_y)
        row.addWidget(self.tip_unit)
        form.addRow("Points at", tip)
        self.leader_from = QComboBox()
        self.leader_from.addItem("Nearest edge", "auto")
        for name in units_module.ANCHORS:
            self.leader_from.addItem(name, name)
        self.leader_from.setCurrentIndex(max(0, self.leader_from.findData(
            label.leader_from)))
        self.leader_from.setToolTip("Where on the text the arrow starts.")
        form.addRow("Arrow from", self.leader_from)
        self.arrow_colour = _colour_button(
            self, lambda: (label.leader_colour
                           if label.leader_colour not in (None, "", "auto")
                           else (label.colour if label.colour != "auto"
                                 else "#cccccc")), self._set_leader_colour)
        form.addRow("Arrow colour", self.arrow_colour)
        self.leader_auto = QCheckBox("Same as text")
        self.leader_auto.setChecked(label.leader_colour in (None, "", "auto"))
        form.addRow("", self.leader_auto)
        self._note_rows = (tip, self.leader_from, self.arrow_colour,
                           self.leader_auto)
        # On its curve a note's arrow drops straight onto its point: no
        # point to type apart from where it hangs, no edge to leave from.
        self._tip_row = tip
        # A band marker has no arrow: its line already says where.
        if label.is_vline:
            self.leader.setVisible(False)
        self._show_tip()

        # A MARKER LINE's temperature, typed, and its style.
        self.line_at = QLineEdit(self)
        self.line_at.setToolTip("Where the line stands. 98 is in the axis "
                                "unit; 98 F, 371 K convert.")
        self.line_dashed = QCheckBox("Dashed")
        self.line_dashed.setChecked(bool(label.line_dashed))
        line = QWidget(self)
        line_row = QHBoxLayout(line)
        line_row.setContentsMargins(0, 0, 0, 0)
        line_row.addWidget(self.line_at)
        line_row.addWidget(self.line_dashed)
        form.addRow("Line at", line)
        form.labelForField(line).setVisible(label.is_vline)
        line.setVisible(label.is_vline)
        if label.is_vline and plot is not None:
            self.line_at.setText("{:.4g}".format(float(plot.to_axis(
                label.vline))))
        self.line_at.editingFinished.connect(self._typed_line)
        self.line_dashed.toggled.connect(self._apply)

        buttons = self._buttons()
        layout.addWidget(buttons)

        self.text.textChanged.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.bold.toggled.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self.leader.toggled.connect(self._leader_toggled)
        self.leader_from.currentIndexChanged.connect(self._apply)
        self.leader_auto.toggled.connect(self._apply)
        self.tip_x.editingFinished.connect(self._typed_tip)
        self.tip_y.editingFinished.connect(self._typed_tip)

    def row_order(self):
        """A band marker: its text, where its line stands, its colour. A
        note: its text, its colour, the point it names and its arrow. A
        label: its text, its colour, its size; "Leader arrow" turns it
        into a note, its rows below it. Layer last."""
        label = self.obj
        style = ("Size", "@bold", "Place", "On the curve at", "@hang_dy",
                 "@hang_dx")
        arrow = ("@leader", "Points at", "Arrow from", "@arrow_colour",
                 "@leader_auto")
        if label.is_vline:
            first = ("@text", "Line at", "Colour", "@auto") + style
        elif label.leader:
            first = ("@text", "Colour", "@auto") + arrow + style
        else:
            first = ("@text", "Colour", "@auto") + style + arrow
        return first, ("Layer",)

    def _show_hang(self):
        """The rows of a label hanging from its curve, shown only then."""
        label = self.obj
        on = bool(getattr(label, "attached", False))
        form = self.findChildren(QFormLayout)[0]
        # A label on a curve is placed like every other artist, by x and y
        # in the Place rows (`ArtistTransform`, which hangs it again where
        # it is typed). The point on the curve, a distance and a sideways
        # shift in px read as confusing in use: those rows are never
        # shown now.
        for widget in self._hang_rows:
            widget.setVisible(False)
            caption = form.labelForField(widget)
            if caption is not None:
                caption.setVisible(False)
        if not on:
            return
        if label.leader:
            self.transform.hide_anchor()
        plot = getattr(self.parent(), "plot", None)
        celsius = plot.attached_celsius(label) if plot is not None else None
        for widget in self._hang_rows:
            widget.blockSignals(True)
        if celsius is not None:
            unit = getattr(self.doc, "x_unit", units.TEMP_C)
            self.hang_at.setText("{} {}".format(
                numbers.write(float(plot.to_axis(celsius)), "%.2f"),
                units.TEMPERATURE_LABEL.get(unit, unit)))
        self.hang_dy.setValue(-float(plot.label_dy(label))
                              if plot is not None else 0.0)
        self.hang_dx.setValue(float(label.dx or 0.0))
        for widget in self._hang_rows:
            widget.blockSignals(False)

    def _typed_hang_at(self):
        label = self.obj
        plot = getattr(self.parent(), "plot", None)
        if not label.attached or plot is None:
            return
        doc = self.doc
        unit = getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C
        celsius = units.parse_temperature(self.hang_at.text(), unit)
        at = (plot.attach_at_celsius(label, celsius)
              if celsius is not None else None)
        if at is None:
            self.hang_at.setStyleSheet("border: 1px solid #d04040;")
            return
        self.hang_at.setStyleSheet("")
        if tuple(at) != tuple(label.at):
            label.at = tuple(at)
            self._live()

    def _typed_hang(self, _value=0.0):
        label = self.obj
        if not label.attached:
            return
        label.dy = -float(self.hang_dy.value())
        if not label.leader:
            label.dx = float(self.hang_dx.value())
        self._live()

    def _typed_line(self):
        label = self.obj
        if not label.is_vline:
            return
        doc = self.doc
        unit = getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C
        celsius = units.parse_temperature(self.line_at.text(), unit)
        if celsius is None:
            self.line_at.setStyleSheet("border: 1px solid #d04040;")
            return
        self.line_at.setStyleSheet("")
        if abs(float(celsius) - float(label.vline)) > 1e-9:
            label.vline = float(celsius)
            self._live()

    def _set_leader_colour(self, name):
        self.obj.leader_colour = name
        self.leader_auto.setChecked(False)
        self._live()

    def _show_tip(self):
        """The point a note names, in the axes' units; the note rows only
        while it is a note."""
        label = self.obj
        plot = getattr(self.parent(), "plot", None)
        on = bool(label.leader) and not label.is_vline
        # SHOWN only while it is a note (they were greyed out); on its
        # curve a note's arrow drops straight onto its point, so there is
        # no point to type and no edge to leave from.
        form = self.findChildren(QFormLayout)[0]
        for widget in self._note_rows:
            shown = on and not (label.attached and widget in (
                self._tip_row, self.leader_from))
            widget.setVisible(shown)
            caption = form.labelForField(widget)
            if caption is not None:
                caption.setVisible(shown)
        if not on or plot is None:
            self.tip_x.setText("")
            self.tip_y.setText("")
            return
        self.tip_x.setText("{:.4g}".format(float(plot.to_axis(
            label.leader[0]))))
        self.tip_y.setText("{:.5g}".format(float(label.leader[1])
                                           + label.follow()))
        self.tip_unit.setText(plot._typed_unit(label, "y"))

    def _typed_tip(self):
        """The point typed: a temperature in any unit, a height in the
        axis's."""
        label = self.obj
        if not label.leader:
            return
        doc = self.doc
        unit = getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C
        celsius = units.parse_temperature(self.tip_x.text(), unit)
        height = numbers.evaluate(self.tip_y.text())
        if celsius is None or height is None:
            box = self.tip_x if celsius is None else self.tip_y
            box.setStyleSheet("border: 1px solid #d04040;")
            return
        self.tip_x.setStyleSheet("")
        self.tip_y.setStyleSheet("")
        new = [float(celsius), float(height) - label.follow()]
        if new != list(label.leader):
            label.leader = new
            self._live()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _leader_toggled(self, on):
        """On: an arrow down and to the left of the text, to be dragged
        where it belongs. Off: a plain label again."""
        label = self.obj
        plot = getattr(self.parent(), "plot", None)
        if not on:
            label.leader = None
        elif not label.leader and plot is not None:
            rect = plot.plot_rect()
            box = plot.rotated_bounds(label, plot.artist_box(label, rect),
                                      rect)
            tip = QPointF(box.center().x(), box.bottom() + 36.0)
            label.leader = plot.leader_value(label, tip, rect)
        self._show_tip()
        if self.isVisible():
            self.fit()
        self._live()

    def _apply(self, *_args):
        label = self.obj
        label.text = self.text.toPlainText() or "Label"
        label.size = self.text_size.value()
        label.bold = bool(self.bold.isChecked())
        if self.auto.isChecked():
            label.colour = "auto"
        label.leader_from = self.leader_from.currentData() or "auto"
        if self.leader_auto.isChecked():
            label.leader_colour = "auto"
        label.line_dashed = bool(self.line_dashed.isChecked())
        self._live()


class AnalysisSettings(_LiveDialog):
    """One analysis: what it is, its interval, and how it is labelled.

    The model and the interval are recomputed IN PLACE by the window
    (`MainWindow.change_model`, `retype_interval`), each as its own undo
    step, exactly as dragging a gizmo is; everything else here is styling
    and goes into this window's one step.
    """

    FIELDS = ("visible", "colour", "label", "label_size", "flush",
              "show_interval", "interval_size", "construction", "shade",
              "mass_line",
              "shading",
              "show_peak",
              "number_format",
              "unit", "label_dy")
    INDIVIDUAL = ("label",)
    GROUP_DISABLED = ("label", "model", "start", "end")

    #: The order of its rows (`_LiveDialog.FIRST_ROWS`).
    FIRST_ROWS = ("Label", "Shows", "Colour", "@auto", "Number format", "Unit",
                  "Model", "@source", "@start", "@end", "Results", "Peak (Tp)",
                  "Lines", "@lines_note", "@mass_line", "Label size",
                  "Alignment",
                  "@interval", "Marker length", "@shade", "Shading")
    LAST_ROWS = ("@visible", "Layer")

    def __init__(self, parent, analysis, on_change=None):
        _LiveDialog.__init__(self, parent, analysis, on_change)
        self.setWindowTitle(analysis.model_name)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.model = QComboBox()
        # The models of ITS curve: a heat flow's, or a mass's.
        for entry in measure.models_for(analysis.scan):
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
        entry = measure.by_name(analysis.model_name)
        #: One temperature (a mass at a temperature) or an interval.
        self.one_cursor = bool(entry is not None and entry.needs == 1)
        if self.one_cursor:
            form.labelForField(self.start).setText("At")
            self.start.setToolTip("The temperature. 98 is in the axis unit; "
                                  "98 F, 371 K, 98 C convert.")
            form.labelForField(self.end).setVisible(False)
            self.end.setVisible(False)

        self.results = QLabel("")
        self.results.setWordWrap(True)
        self.results.setToolTip("Everything the analysis computed.")
        form.addRow("Results", self.results)

        # No "Drawn on": an analysis from a .txt export is offered under
        # every scan with its step name and is attributed by being shown on
        # the one it belongs to (`Sample.analyses_for`).

        self.visible = QCheckBox("Show")
        self.visible.setChecked(bool(analysis.visible))
        self.visible.setToolTip("Draw this analysis.")
        form.addRow("", self.visible)

        self.interval = QCheckBox("Show interval markers")
        self.interval.setChecked(bool(analysis.show_interval))
        self.interval.setToolTip("Dashes at the interval ends, on the "
                                 "curve.")
        form.addRow("", self.interval)
        self.interval_size = _style_number(self, analysis, "interval_size")
        self.interval_size.setToolTip("Half the length of each dash.")
        form.addRow("Marker length", self.interval_size)

        # The shading of an integration, and whether it lets things show
        # through. Only an integration is shaded.
        self.shade = QCheckBox("Shade the area")
        self.shade.setChecked(bool(analysis.shade))
        self.shade.setToolTip("Fill the integrated area between the curve "
                              "and its baseline.")
        # Translucent, or opaque in the colour the translucent fill makes
        # over the page; the house style's until chosen, like "Lines".
        self.opaque = StyleChoice(
            style.SHADINGS, getattr(analysis, "shading", None),
            lambda: style.SHADING_TITLES.get(
                style.inherited(self.doc, self.obj, "shading"), ""),
            parent=self, titles=style.SHADING_TITLES)
        self.opaque.setEnabled(bool(analysis.shade))
        self.opaque.setToolTip("Opaque: the colour the translucent shading "
                               "makes over the background, so nothing "
                               "behind it shows through.")
        integration = "Integration" in analysis.model_name
        form.addRow("", self.shade)
        form.addRow("Shading", self.opaque)
        # Its peak temperature in the label as well.
        self.peak = StyleChoice(
            style.PEAKS, getattr(analysis, "show_peak", None),
            lambda: style.PEAK_TITLES.get(
                style.inherited(self.doc, self.obj, "show_peak"), ""),
            parent=self, titles=style.PEAK_TITLES)
        self.peak.setToolTip("The peak temperature after the enthalpy: "
                             "*T*_{p} = 124 \u00b0C. {Tp} in the label "
                             "puts it anywhere.")
        form.addRow("Peak (Tp)", self.peak)
        for box in (self.shade, self.opaque, self.peak):
            box.setVisible(integration)
        form.labelForField(self.opaque).setVisible(integration)
        form.labelForField(self.peak).setVisible(integration)

        # The lines of an onset, endset or Tg, following the house style
        # until chosen, like the alignment below. Only those have lines.
        self.lines = StyleChoice(
            style.LINES, analysis.construction,
            lambda: style.LINES_TITLES.get(
                style.inherited(self.doc, self.obj, "construction"), ""),
            parent=self, titles=style.LINES_TITLES)
        self.lines.setToolTip("Tangent construction, chords to the point, "
                              "or none.")
        form.addRow("Lines", self.lines)
        # Why there are no tangents to draw, when there are none: one line.
        self.lines_note = QLabel("")
        self.lines_note.setWordWrap(True)
        self.lines_note.setStyleSheet("color: #9a9a9a;")
        self.lines_note.setVisible(False)
        form.addRow("", self.lines_note)
        # A dashed line across the axes at the m% of its point - only an
        # analysis with a point on a mass curve has one.
        self.mass_line = QCheckBox("Mass line")
        self.mass_line.setChecked(bool(getattr(analysis, "mass_line",
                                               False)))
        self.mass_line.setToolTip(
            "A dashed line across the plot at the m% of this point, its "
            "value at the left edge (house style: Mass lines).")
        form.addRow("", self.mass_line)
        self.mass_line.setVisible(analysis.has_mass_line)

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

        # Which unit the number is in: the axes' until chosen. A per-mole
        # one needs the molar mass, and says so rather than guessing.
        self.unit = QComboBox()
        self.unit.addItem("As the axes", None)
        for name in labels.units_of(analysis.quantity):
            self.unit.addItem(name, name)
        found = self.unit.findData(analysis.unit)
        self.unit.setCurrentIndex(found if found >= 0 else 0)
        self.unit.setToolTip("The unit of the number. kJ/mol and J/mol need "
                             "the molar mass.")
        form.addRow("Unit", self.unit)

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
        self.mass_line.toggled.connect(self._apply)
        self.interval_size.changed.connect(self._apply)
        self.shade.toggled.connect(self._apply)
        self.opaque.changed.connect(self._apply)
        self.peak.changed.connect(self._apply)
        self.lines.changed.connect(self._apply)
        self.text_size.changed.connect(self._apply)
        self.flush.changed.connect(self._apply)
        self.label.textChanged.connect(self._apply)
        self.number_format.changed.connect(self._apply)
        self.unit.currentIndexChanged.connect(self._apply)
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
        self._show_lines()
        self._show_offset()
        self._show_preview()

    def _show_lines(self):
        """Lines only for an onset, endset or Tg; and, where tangents are
        asked for and there are none to draw, why - in one line."""
        analysis = self.obj
        self.lines.setEnabled(analysis.marks_a_point)
        self.lines.refresh()
        note = measure.lines_note(analysis, self.doc)
        self.lines_note.setText(note)
        self.lines_note.setVisible(bool(note))

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
        boxes = ((self.start, self.start) if self.one_cursor
                 else (self.start, self.end))
        for box in boxes:
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
        analysis.mass_line = bool(self.mass_line.isChecked())
        analysis.interval_size = self.interval_size.value()
        analysis.shade = bool(self.shade.isChecked())
        analysis.shading = self.opaque.value()
        analysis.show_peak = self.peak.value()
        self.opaque.setEnabled(analysis.shade)
        analysis.construction = self.lines.value()
        analysis.label_size = self.text_size.value()
        analysis.flush = self.flush.value()
        analysis.label = self.label.text().strip() or None
        analysis.number_format = self.number_format.value()
        analysis.unit = self.unit.currentData()
        if self.auto.isChecked():
            analysis.colour = "auto"
        self._live()
        self._show_lines()
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

    #: The order of its rows (`_LiveDialog.FIRST_ROWS`).
    FIRST_ROWS = ("Number format", "Colour", "@auto", "Points at", "@at_auto",
                  "Size")
    LAST_ROWS = ("@visible",)

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

    #: The order of its rows (`_LiveDialog.FIRST_ROWS`).
    FIRST_ROWS = ("Label", "Colour", "@auto")
    LAST_ROWS = ("@visible",)

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
    """Where the figure goes, and in which colours.

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


def install_basic_colours():
    """The colour picker's 48 basic colours, read left to right and top to
    bottom: the DSC_Plotter template's first, in its order. Qt numbers
    the grid down its six rows first, so the reading order is mapped onto
    that."""
    colours = (PLOTTER_COLOURS + MORE_COLOURS)[:48]
    for order, name in enumerate(colours):
        row, column = divmod(order, 8)
        QColorDialog.setStandardColor(row + column * 6, QColor(name))
    return len(colours)


class ImageSettings(_LiveDialog):
    """A picture on the figure: shown or not, its width, where it sits."""

    FIELDS = ("width", "visible", "x", "y", "space", "anchor", "rotation")

    def __init__(self, parent, image, on_change=None):
        _LiveDialog.__init__(self, parent, image, on_change)
        self.setWindowTitle("Image")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.shown = QCheckBox("Show")
        self.shown.setChecked(bool(image.visible))
        self.shown.setToolTip("Draw the image.")
        form.addRow("", self.shown)

        self.picture_width = NumberBox()
        self.picture_width.setDecimals(1)
        self.picture_width.setRange(4.0, 4000.0)
        self.picture_width.setSuffix(" px")
        self.picture_width.setValue(float(image.width))
        self.picture_width.setToolTip("Drawn width; the height keeps the "
                                      "picture's proportions. S scales it "
                                      "by hand.")
        form.addRow("Width", self.picture_width)

        self.transform = ArtistTransform(image, getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        buttons = self._buttons()
        layout.addWidget(buttons)
        self.shown.toggled.connect(self._apply)
        self.picture_width.valueChanged.connect(self._apply)

    def _apply(self, *_args):
        self.obj.visible = bool(self.shown.isChecked())
        self.obj.width = float(self.picture_width.value())
        self._live()


class MoleculeSettings(_LiveDialog):
    """A skeletal structure: its SMILES, its bonds and labels, its colour,
    and where it sits. The sizes start at the ACS 1996 document style's."""

    FIELDS = ("visible", "colour", "bond_length", "bond_width", "label_size",
              "upright_labels", "x", "y", "space", "anchor", "rotation",
              "smiles", "atoms", "bonds", "label_font", "colour_by_element")
    INDIVIDUAL = ("x", "y", "space", "smiles", "atoms", "bonds")
    GROUP_DISABLED = ("smiles_edit", "transform.space", "transform.at_x",
                      "transform.at_y")

    #: The order of its rows (`_LiveDialog.FIRST_ROWS`).
    FIRST_ROWS = ("SMILES", "Colour", "@auto", "@by_element", "Bond length",
                  "Bond width", "Label size", "Label font", "@upright")
    LAST_ROWS = ("@shown", "Place", "Layer")

    def __init__(self, parent, molecule, on_change=None):
        _LiveDialog.__init__(self, parent, molecule, on_change)
        self.setWindowTitle("Structure")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.shown = QCheckBox("Show")
        self.shown.setChecked(bool(molecule.visible))
        self.shown.setToolTip("Draw the structure.")
        form.addRow("", self.shown)

        self.smiles_edit = QLineEdit(molecule.smiles, self)
        self.smiles_edit.setToolTip("Type another SMILES and press Enter to "
                                    "redraw it (needs RDKit).")
        form.addRow("SMILES", self.smiles_edit)

        def size(low, high, step, suffix):
            box = NumberBox()
            box.setDecimals(2)
            box.setRange(low, high)
            box.setSingleStep(step)
            box.setSuffix(suffix)
            return box

        self.bond_length = size(2.0, 400.0, 1.0, " px")
        self.bond_length.setValue(float(molecule.bond_length))
        self.bond_length.setToolTip("Bond length; ACS style is 19.2 px "
                                    "(0.2 inch).")
        form.addRow("Bond length", self.bond_length)
        self.bond_width = size(0.1, 20.0, 0.1, " px")
        self.bond_width.setValue(float(molecule.bond_width))
        self.bond_width.setToolTip("Line width of the bonds; ACS style is "
                                   "0.8 px (0.6 pt).")
        form.addRow("Bond width", self.bond_width)
        self.label_size = size(3.0, 72.0, 0.5, " pt")
        self.label_size.setValue(float(molecule.label_size))
        self.label_size.setToolTip("Size of the element labels.")
        form.addRow("Label size", self.label_size)

        self.label_font = FontChoice(
            molecule.label_font,
            lambda: (style.inherited(self.doc, molecule, "label_font")
                     or style.figure_value(self.doc, "font_family") or ""),
            parent=self)
        self.label_font.setToolTip("The element labels' typeface; Default "
                                   "is the house style's (Settings, "
                                   "Structure labels).")
        form.addRow("Label font", self.label_font)

        self.by_element = QCheckBox("Colour by element")
        self.by_element.setChecked(bool(molecule.colour_by_element))
        self.by_element.setToolTip("N blue, O red, S yellow...; the bonds "
                                   "keep the colour below.")
        form.addRow("", self.by_element)

        self.upright = QCheckBox("Labels stay upright when rotated")
        self.upright.setChecked(bool(molecule.upright_labels))
        self.upright.setToolTip("Off: the labels turn with the structure.")
        form.addRow("", self.upright)

        form.addRow("Colour", _colour_button(
            self, lambda: (molecule.colour if molecule.colour != "auto"
                           else "#cccccc"), self._set_colour))
        self.auto = QCheckBox("Follow the theme")
        self.auto.setChecked(molecule.colour in (None, "", "auto"))
        self.auto.setToolTip("Light on dark, dark on light.")
        form.addRow("", self.auto)

        self.transform = ArtistTransform(molecule,
                                         getattr(parent, "plot", None),
                                         on_change=self._live, parent=self)
        form.addRow("Place", self.transform)

        buttons = self._buttons()
        layout.addWidget(buttons)
        self.shown.toggled.connect(self._apply)
        for box in (self.bond_length, self.bond_width, self.label_size):
            box.valueChanged.connect(self._apply)
        self.upright.toggled.connect(self._apply)
        self.by_element.toggled.connect(self._apply)
        self.label_font.changed.connect(self._apply)
        self.auto.toggled.connect(self._apply)
        self.smiles_edit.editingFinished.connect(self._new_smiles)

    def _new_smiles(self):
        from ..core import chem
        text = self.smiles_edit.text().strip()
        if text == self.obj.smiles:
            return
        drawing = chem.layout(text)
        if drawing is None:
            self.smiles_edit.setStyleSheet("border: 1px solid #d04040;")
            return
        self.smiles_edit.setStyleSheet("")
        self.obj.smiles = text
        self.obj.atoms = drawing["atoms"]
        self.obj.bonds = drawing["bonds"]
        self._live()

    def _set_colour(self, name):
        self.obj.colour = name
        if hasattr(self, "auto"):
            self.auto.setChecked(False)
        self._live()

    def _apply(self, *_args):
        molecule = self.obj
        molecule.visible = bool(self.shown.isChecked())
        molecule.bond_length = float(self.bond_length.value())
        molecule.bond_width = float(self.bond_width.value())
        molecule.label_size = float(self.label_size.value())
        molecule.upright_labels = bool(self.upright.isChecked())
        molecule.colour_by_element = bool(self.by_element.isChecked())
        molecule.label_font = self.label_font.value() or None
        if self.auto.isChecked():
            molecule.colour = "auto"
        self._live()


# The windows of objects with a place in the figure's stack show it: a
# Layer field (`_LiveDialog._layer_row`).
for _kind in (ScanSettings, AnalysisSettings, LabelSettings, LegendSettings,
              ArrowSettings, OffsetMarkerSettings, ImageSettings,
              MoleculeSettings):
    _kind.LAYERED = True

class DetailsDialog(QDialog):
    """"Details..." of a file: where it is, how big, its dates and a
    fingerprint of its contents, and what its run records - what tells two
    files of one name apart, two of these side by side. For a file the
    session could not read: where it was and what is kept of it, with the
    two ways to look for it (`locate`, `find`: callables, else None)."""

    def __init__(self, parent, title, rows, locate=None, find=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        #: `[(what, value), ...]` as shown.
        self.rows = [(str(what), str(value)) for what, value in rows]
        for what, value in self.rows:
            shown = QLabel(value, self)
            shown.setWordWrap(True)
            shown.setMinimumWidth(360)
            form.addRow(what, shown)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        for text, act in (("Locate...", locate), ("Find in a folder...",
                                                  find)):
            if act is None:
                continue
            button = buttons.addButton(text, QDialogButtonBox.ActionRole)
            button.setAutoDefault(False)
            button.clicked.connect(
                lambda _c=False, act=act: self._then(act))
        copy_all = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        copy_all.setAutoDefault(False)
        copy_all.setToolTip("All of it as text, a line per row.")
        copy_all.clicked.connect(lambda _c=False: self.copy())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        readable(self)

    def text(self):
        return "\n".join("{}: {}".format(what, value)
                         for what, value in self.rows)

    def copy(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text())

    def _then(self, act):
        """Close, then look: the look opens dialogs of its own."""
        self.accept()
        QTimer.singleShot(0, act)


class FoundFilesDialog(QDialog):
    """What a search under a folder found for the files a session could not
    read: for each, the files named like it, the likeliest chosen - or
    "Leave it missing". Each one's size and date are on its tooltip."""

    def __init__(self, parent, folder, hits, stopped=""):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Missing files found")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        intro = QLabel("Under {}{}: take these in their places?".format(
            folder, stopped), self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        #: `[(saved path, combo box), ...]`.
        self.boxes = []
        for name, saved, found in hits:
            if not found:
                form.addRow(name, QLabel("nothing like it", self))
                continue
            box = QComboBox(self)
            for score, path in found:
                try:
                    shown = os.path.relpath(path, folder)
                except ValueError:
                    shown = path
                box.addItem("{}   {:.0%}".format(shown, score), path)
                box.setItemData(box.count() - 1, _file_line(path),
                                Qt.ToolTipRole)
            box.addItem("Leave it missing", "")
            form.addRow(name, box)
            self.boxes.append((saved, box))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Take them")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        readable(self)

    def chosen(self):
        """`{saved path: file}` for every file given one."""
        return dict((saved, box.currentData()) for saved, box in self.boxes
                    if box.currentData())


def _file_line(path):
    """"12,345 bytes, modified 2025-10-09 14:02" - or the path alone."""
    import time
    try:
        info = os.stat(path)
    except OSError:
        return path
    return "{}\n{:,} bytes, modified {}".format(
        path, info.st_size,
        time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime)))


# Qt calls the handlers here by itself; an error in one is logged and
# survived rather than the end of the program (`core/log.py`).
from ..core import log as _log
_log.guard_classes(globals(), __name__)

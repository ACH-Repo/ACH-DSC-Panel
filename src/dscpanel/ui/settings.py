"""Edit > Settings: the house style, for every figure and for this one.

MoloM's settings page, cut down to what a figure needs. Two columns, because
Christian asked for two things at once: defaults that persist between
sessions, and a way to override them for one particular save file.

* **Default** is the user's own house style. It lives on this computer
  (`core/style.py`, `preferences.json`), is written when the page is closed
  with OK, and is what every figure falls back on.
* **This figure** belongs to the open document and is saved in its session
  file. Empty ("default") means "whatever the default says"; a value here
  wins for this figure alone. The change is one undo step.

A size set in an object's OWN settings (double-click a label) wins over both
columns, because that was a decision about that one object.

Below them, **Handling**: how the program responds to the hand - the pick
distance. It has a Default and nothing else, because it is about the person
at the trackpad and not about any figure.

Live, like every dialog here: the plot follows each change as it is made, and
Cancel puts back what was there when the page opened - both columns.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout,
                               QLabel, QVBoxLayout)

from ..core import style
from .dialogs import NumberBox, StyleChoice, StyleNumber


class SettingsDialog(QDialog):
    """The house style, as a two-column table."""

    def __init__(self, window):
        QDialog.__init__(self, window)
        self.setWindowTitle("Settings")
        # Not modal, like the object dialogs and like MoloM's page: a size is
        # judged by looking at the plot, and a modal page hides it.
        self.setModal(False)
        self.setWindowFlag(Qt.Tool, True)
        self.main = window
        self.doc = window.doc
        self._saved_defaults = style.preferences()
        self._saved_figure = dict((s.key, getattr(self.doc.style, s.key))
                                  for s in style.FIGURE_SETTINGS)
        self.defaults = {}
        self.figure = {}

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        layout.addLayout(grid)
        for column, text in ((1, "Default"), (2, "This figure")):
            head = QLabel("<b>{}</b>".format(text))
            grid.addWidget(head, 0, column)
        handling = [s for s in style.SETTINGS if not s.figure]
        rows = list(style.FIGURE_SETTINGS) + ([None] if handling else [])             + handling
        for row, setting in enumerate(rows, start=1):
            if setting is None:
                head = QLabel("<b>Handling</b>")
                head.setContentsMargins(0, 10, 0, 0)
                grid.addWidget(head, row, 0)
                continue
            name = QLabel(setting.title)
            if setting.note:
                name.setToolTip(setting.note)
            grid.addWidget(name, row, 0)
            key = setting.key
            if setting.kind == "choice":
                default = StyleChoice(setting.choices, style.preference(key),
                                      lambda: "", parent=self,
                                      titles=style.FLUSH_TITLES,
                                      allow_default=False)
                default.changed.connect(
                    lambda k=key: self._default_changed(k))
                own = StyleChoice(
                    setting.choices, getattr(self.doc.style, key),
                    (lambda k=key: style.FLUSH_TITLES.get(
                        style.preference(k), style.preference(k))),
                    parent=self, titles=style.FLUSH_TITLES)
            else:
                default = NumberBox(self)
                default.setDecimals(setting.decimals)
                default.setRange(float(setting.low), float(setting.high))
                default.setSingleStep(float(setting.step))
                default.setSuffix(setting.suffix)
                default.setValue(float(style.preference(key)))
                default.valueChanged.connect(
                    lambda _v=0.0, k=key: self._default_changed(k))
                own = None
                if setting.figure:
                    own = StyleNumber(setting, getattr(self.doc.style, key),
                                      (lambda k=key: style.preference(k)),
                                      parent=self)
            self.defaults[key] = default
            grid.addWidget(default, row, 1)
            if setting.note and not setting.figure:
                default.setToolTip(setting.note)
            if own is not None:
                own.changed.connect(lambda k=key: self._figure_changed(k))
                self.figure[key] = own
                grid.addWidget(own, row, 2)

        note = QLabel(
            "Default is kept on this computer and used by every figure. This "
            "figure is saved in its session file and wins over the default. "
            "A size chosen in an object's own settings (double-click it) "
            "wins over both.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).setText(
            "Built-in defaults")
        buttons.button(QDialogButtonBox.RestoreDefaults).setToolTip(
            "Put the Default column back to what the program shipped with.")
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            lambda _c=False: self.restore_builtin())
        layout.addWidget(buttons)
        self.resize(560, self.sizeHint().height())

    # ------------------------------------------------------------ editing
    def default_value(self, key):
        widget = self.defaults[key]
        if isinstance(widget, StyleChoice):
            return widget.value()
        return float(widget.value())

    def set_default(self, key, value):
        """Change one default as if it had been typed. For the button, and
        for tests."""
        widget = self.defaults[key]
        inner = widget.combo if isinstance(widget, StyleChoice) else widget
        inner.blockSignals(True)
        if isinstance(widget, StyleChoice):
            widget.set_value(value)
        else:
            widget.setValue(float(value))
        inner.blockSignals(False)
        self._default_changed(key)

    def _default_changed(self, key):
        style.set_preference(key, self.default_value(key))
        # The "This figure" column shows the default wherever it follows it.
        if key in self.figure:
            self.figure[key].refresh()
        self._live()

    def _figure_changed(self, key):
        setattr(self.doc.style, key, self.figure[key].value())
        self._live()

    def restore_builtin(self):
        for setting in style.SETTINGS:
            self.set_default(setting.key, setting.default)

    def _live(self):
        self.main._live_change()

    # ----------------------------------------------------------- finishing
    def accept(self):
        """Keep both columns: the defaults on disk, the figure on the stack.

        Written defensively: this runs in a Qt slot, where an exception is an
        abort rather than a traceback, and a read-only settings folder is not
        a reason to lose the figure.
        """
        try:
            style.save_preferences()
        except OSError as exc:
            self.main.note.setText("Could not save the defaults: {}".format(
                exc))
        changes = []
        for key, old in self._saved_figure.items():
            new = getattr(self.doc.style, key)
            if new != old:
                setattr(self.doc.style, key, old)
                changes.append((self.doc.style, key, new))
        if changes and self.main.doc is self.doc:
            self.main.undo.set_props(changes, "figure style")
        else:
            self._live()
        QDialog.accept(self)

    def reject(self):
        style.restore_preferences(self._saved_defaults)
        for key, old in self._saved_figure.items():
            setattr(self.doc.style, key, old)
        self._live()
        QDialog.reject(self)

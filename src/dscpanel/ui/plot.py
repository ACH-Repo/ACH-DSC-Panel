"""The painted plot: MoloM's PXRD window, taught what a DSC scan is.

The navigation, the pixmap cache and the per-column decimation come straight
from `molom/ui/pxrd_panel.py` and are deliberately key for key the same: `Z`
cycles zoom, `P` cycles pan, `Esc` leaves the mode, `F` or `Home` resets,
right-click opens the menu for whatever is under the cursor. Christian uses
that window daily and the point of this one is that his hands already know it.

What is NOT the same, and why:

* **The stack is continuous.** PXRD swaps two patterns' places in a stack of
  slots. A DSC scan is dragged to wherever it should sit, in W/g, and the
  offset it was given is drawn beside it as a number with an arrow. There are
  no slots to swap.
* **Nothing is normalised.** PXRD scales every pattern to 100 and hides the y
  numbers. Here the y axis carries real units and real numbers, because the
  baseline of a DSC trace is part of the measurement (see `core/units.py`).
* **x is not sorted.** A cooling segment runs from 250 to 30, and every
  segment reverses direction a few times at its ends. `searchsorted` is
  wrong here, so the visible range is taken with a MASK, the curve is split
  into the runs that are actually in view, and each run is decimated by
  consecutive pixel column - which tolerates reversals because it groups
  neighbours rather than sorted values.
* **Objects are selected and transformed.** Click to select, Shift+click to
  add, `G` to grab with typed numbers and `Esc` to cancel: the Blender
  handling MoloM's viewport has, in a plot. The heat-flow arrow is an object
  too, so it is dragged the same way.
* **A scan that cannot be drawn is still there.** On a per-mole axis a scan
  with no molar mass is drawn as a dashed placeholder at its own offset with
  a blinking red label, not left out and not quietly plotted in some other
  unit. It can still be selected, right-clicked and given its M.
"""

import contextlib
import math
import re
import time

import numpy as np

from PySide6.QtCore import (QPoint, QPointF, QRect, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core import figure as figure_module
from ..core import labels, model, numbers, style, units

#: The two ways this program draws.
#:
#: `blender-default` is the screen theme: pale ink on a dark ground, the same
#: choice MoloM and its PXRD window make. `light` is the same plot on white,
#: which is what a document or a paper wants - and what every export uses,
#: because a dark figure does not survive being dropped into a page.
#:
#: Everything that has a colour reads it from here, so a third theme is a
#: dictionary and not a hunt through the drawing code.
THEME_DARK = "blender-default"
THEME_LIGHT = "light"

THEMES = {
    THEME_DARK: {
        "_BG": QColor(38, 38, 38),
        # Round the figure when it is shown at a fixed size or aspect: the
        # page edge has to be visible, or its size means nothing on screen.
        "_SURROUND": QColor(26, 26, 26),
        "_AXIS": QColor(150, 150, 150),
        "_GRID": QColor(58, 58, 58),
        "_TEXT": QColor(205, 205, 205),
        "_TEXT_DIM": QColor(150, 150, 150),
        "_INK": QColor(228, 228, 228),      # the arrow and other artists
        "_CURSOR": QColor(240, 200, 90),
        "_BAND": QColor(240, 200, 90, 60),
        "_BAND_EDGE": QColor(240, 200, 90),
        "_SELECT": QColor(255, 170, 60),
        "_ALARM": QColor(232, 76, 76),
    },
    THEME_LIGHT: {
        "_BG": QColor(255, 255, 255),
        "_SURROUND": QColor(170, 170, 170),
        "_AXIS": QColor(40, 40, 40),
        "_GRID": QColor(226, 226, 226),
        "_TEXT": QColor(20, 20, 20),
        "_TEXT_DIM": QColor(60, 60, 60),
        "_INK": QColor(26, 26, 26),
        "_CURSOR": QColor(190, 130, 20),
        "_BAND": QColor(190, 130, 20, 50),
        "_BAND_EDGE": QColor(190, 130, 20),
        "_SELECT": QColor(220, 120, 20),
        "_ALARM": QColor(200, 30, 30),
    },
}

#: The theme in force. Module state rather than a parameter threaded through
#: forty paint calls; `themed()` swaps it for the duration of an export.
THEME = THEME_DARK
globals().update(THEMES[THEME_DARK])

#: Trace colours are brought down to this relative luminance on a light
#: ground. The number is MoloM's, measured against tab10 / ColorBrewer /
#: Okabe-Ito rather than taken from the WCAG floor, which is darker than any
#: of them. The palette is chosen for a dark background and none of it prints.
PAPER_LUMA = 0.42


def set_theme(name):
    """Switch the palette. Returns the name that is now in force."""
    global THEME
    if name not in THEMES:
        return THEME
    THEME = name
    globals().update(THEMES[name])
    return THEME


def for_light(colour):
    """`colour`, darkened enough to read on white, hue kept.

    Scaling the three channels by one factor preserves the hue, which is the
    thing that tells two traces apart; a colour already dark enough is left
    exactly as it is, which protects one the user picked by hand.
    """
    colour = QColor(colour)
    luma = (0.2126 * colour.redF() + 0.7152 * colour.greenF()
            + 0.0722 * colour.blueF())
    if luma <= PAPER_LUMA:
        return colour
    factor = PAPER_LUMA / max(luma, 1e-6)
    return QColor.fromRgbF(colour.redF() * factor, colour.greenF() * factor,
                           colour.blueF() * factor)

#: Room for the y numbers, which this plot has and the PXRD one does not.
_LEFT = 66
_RIGHT = 14
_TOP = 12
_BOTTOM = 42

CURVE_WIDTH = 1.0
SELECTED_EXTRA = 1.0

#: One wheel notch, Mestrenova's step and ORCA Workbench's.
WHEEL_STEP = 1.2
#: Trackpads report pixels and wheels report eighths of a degree; both are
#: brought to "notches" before either is believed. MoloM's `core/input_map`
#: owns these two numbers there, and they are the same two here.
PANE_STEP_PIXELS = 60.0
PANE_WHEEL_UNITS = 120.0

#: How far the cursor must travel before a press becomes a drag. Cumulative
#: from the press: a trackpad delivers one or two pixels per event, so a
#: per-event threshold never trips.
DRAG_SLOP = 4

#: A burst of wheel, swipe or pinch events is ONE undo step, and it ends
#: when the fingers have been still this long.
VIEW_SETTLE_MS = 450

#: The template's `add_yoffset_markers`: the label hangs this fraction of
#: the plot's height BELOW its curve (`yoff_label=-0.03`).
OFFSET_MARKER_DROP = 0.03
#: An unplaced marker points this far (figure units) in from the left end
#: of its curve, or from the y axis when the curve runs past it: tight
#: against the axis (Christian, round 14).
OFFSET_MARKER_INSET = 6.0

#: Figure units per typographic point: the figure is 96 units per inch.
PT = 96.0 / 72.0

#: Tried in order after the house style's family, when that one is not on
#: the machine: Bahnschrift, the default, ships with Windows 10 and 11 and
#: with nothing else, so a Mac or Linux gets the nearest plain sans.
FALLBACK_FAMILIES = ("Segoe UI", "Helvetica Neue", "Arial",
                     "Liberation Sans", "DejaVu Sans")

#: Half the length of the dash at each bound of an analysis's interval,
#: centred on the trace. Small on purpose: it marks where the stretch ends,
#: it is not an annotation in its own right.
INTERVAL_TICK = 4.0

#: The blink for a scan that is missing its molar mass: two flashes, then a
#: long pause. Tuned to be noticeable in the corner of the eye and NOT to
#: strobe: 10 ticks of 160 ms is 1.6 s of which 0.64 s is lit, then 3.2 s of
#: nothing.
BLINK_MS = 160
BLINK_ON = (0, 1, 3, 4)
BLINK_PERIOD = 30


class Trace(object):
    """One scan, prepared for one particular view.

    Built fresh by `rebuild`, thrown away when anything changes. It holds the
    converted arrays so that painting, hit-testing and exporting all read the
    same numbers.
    """

    __slots__ = ("scan", "x", "y", "colour", "missing", "px", "py",
                 "hidden", "first")

    def __init__(self, scan, x, y, colour, missing=None, hidden=(), first=0):
        self.scan = scan
        #: The KEPT samples only (see `Scan.keep`): everything that fits,
        #: picks, arranges or measures reads these.
        self.x = x
        self.y = y
        #: The truncated ends as `[(x, y), ...]`, drawn dashed on hover.
        self.hidden = list(hidden)
        #: Where `x[0]` sits in the segment's own arrays, so a sample picked
        #: here can be named in the file's terms (an analysis's `span`).
        self.first = int(first)
        self.colour = QColor(colour)
        #: What stops this scan being drawn, or None. A trace with a reason
        #: has no arrays and is drawn as a placeholder.
        self.missing = missing
        #: The screen points last drawn, kept for hit-testing so that what
        #: the cursor picks is what the eye sees.
        self.px = None
        self.py = None

    @property
    def name(self):
        return self.scan.display_name()


@contextlib.contextmanager
def themed(_plot, name):
    """Draw in another theme for the duration, then put the old one back.

    Used by the exports, which are always light: it restores in a `finally`,
    so an exception mid-paint cannot leave the window drawn for paper.
    """
    previous = THEME
    set_theme(name)
    try:
        yield
    finally:
        set_theme(previous)


def paper_palette(plot, light=True):
    """Backwards-compatible alias: the light theme, for an export."""
    return themed(plot, THEME_LIGHT if light else THEME)


class PlotWidget(QWidget):
    """The plot. Owns the view and the gestures; the document owns the data."""

    hovered = Signal(str)
    mode_changed = Signal(str)
    view_changed = Signal()
    #: (object under the cursor or None, global position)
    context_menu = Signal(object, QPoint)
    selection_changed = Signal()
    #: A gesture finished and these property changes should become one undo
    #: step: [(obj, name, value), ...], and a label for the menu.
    transform_done = Signal(list, str)
    #: Double-click on an object: the window opens its settings.
    activated = Signal(object)
    #: Two cursors are down and Enter was pressed: (scan, x0, x1, analysis
    #: being edited or None, span or None). Both temperatures are in the
    #: FILE's Celsius; the span, when the cursors came from the curve, is
    #: the two sample indices they sit on.
    measure_ready = Signal(object, float, float, object, object)
    #: A zoom or pan finished: (view before, view after, "zoom"/"pan"/"fit"),
    #: for the window to put on the undo stack. See `commit_view`.
    view_committed = Signal(object, object, str)

    #: BOX first (Christian, round 10). The PXRD window starts horizontal,
    #: which suits a spectrum of peaks; on a DSC stack the feature is a
    #: region in both directions, so the first Z is the box.
    ZOOM_CYCLE = ("zoom_box", "zoom_h", "zoom_v", None)
    PAN_CYCLE = ("pan_h", "pan_v", "pan_free", None)
    MODE_TEXT = {
        "zoom_h": "ZOOM horizontal - drag a range (Esc exits)",
        "zoom_v": "ZOOM vertical - drag a range (Esc exits)",
        "zoom_box": "ZOOM box - drag a rectangle (Esc exits)",
        "pan_h": "PAN horizontal - drag (Esc exits)",
        "pan_v": "PAN vertical - drag (Esc exits)",
        "pan_free": "PAN free - drag (Esc exits)",
    }
    #: What the status line says when no tool is armed. Box select is the
    #: resting state, so Esc always lands somewhere useful.
    SELECT_TEXT = ("SELECT - drag a curve to analyse, a label to move it, "
                   "empty space for a box (Shift adds); G moves scans")
    #: While a double-click-drag is marking an interval on a curve.
    INTERVAL_TEXT = "ANALYSE - release to choose what to compute (Esc cancels)"
    MODE_CURSOR = {"zoom_h": Qt.SizeHorCursor, "zoom_v": Qt.SizeVerCursor,
                   "zoom_box": Qt.CrossCursor, "pan_h": Qt.SizeHorCursor,
                   "pan_v": Qt.SizeVerCursor, "pan_free": Qt.SizeAllCursor}

    def __init__(self, document=None, parent=None):
        QWidget.__init__(self, parent)
        #: The font the figure starts from; the house style's family is set
        #: on a copy of it (`figure_font`).
        self._base_font = QFont(self.font())
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.doc = document
        self.traces = []
        self.y_margin = 0.06
        self._view_x = None
        self._view_y = None
        self._cursor = None
        self._mode = None
        self._drag = None           # a navigation drag (zoom band / pan)
        self._move = None           # a transform: mouse drag or G
        self._box = None            # a box selection being dragged
        self._measure = None        # cursors being placed on a scan
        self._interval = None       # a drag along a curve, marking a stretch
        self._press = None          # a press near an object, not yet a drag
        self._view_burst = None     # (view before, label) while zooming
        self._view_settle = QTimer(self)
        self._view_settle.setSingleShot(True)
        self._view_settle.setInterval(VIEW_SETTLE_MS)
        self._view_settle.timeout.connect(self.commit_view)
        self._flash = None          # (text, started) - "Saved" and the like
        self._axis_hit = None       # 'caption' or 'spine'
        self._cursor_handles = []   # [(index, QRect)] while measuring
        self._cursor_drag = None    # a measure cursor being dragged
        self._cache = None
        self._cache_key = None
        self._label_boxes = []      # [(trace, QRect)] from the last render
        self._analysis_boxes = []   # [(Analysis, QRect)] from the last render
        self._marker_boxes = []     # [(OffsetMarker, QRectF)], likewise
        #: (object clicked, what was selected before) when a click narrowed
        #: a selection - undone if the click becomes a double-click.
        self._click_restore = None
        #: A live `S` scale, or None.
        self._scale = None
        self._axis_boxes = []       # [(Axis, QRect)] for the captions
        self._text_boxes = []       # [(TextLabel, QRect)]
        self._blink = 0
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(BLINK_MS)
        self._blink_timer.timeout.connect(self._tick_blink)
        #: Set only while painting into an export device, where the sampling
        #: resolution is a choice rather than the screen's.
        self._columns_override = None

    # --------------------------------------------------------------- content
    def set_document(self, doc):
        self.doc = doc
        self.rebuild(keep_view=False)

    def rebuild(self, keep_view=True):
        """Rebuild every trace from the document, then redraw."""
        traces = []
        doc = self.doc
        if doc is not None:
            for scan in doc.scans:
                if not scan.visible:
                    continue
                x, y = scan.curve(doc.x_axis, doc.y_unit, doc.exo,
                                  getattr(doc, 'x_unit', units.TEMP_C))
                missing = (None if x is not None
                           else scan.missing_for(doc.y_unit, doc.x_axis))
                if x is None:
                    traces.append(Trace(scan, x, y, scan.colour, missing))
                    continue
                k0, k1 = scan.kept_range(len(x))
                # Each hidden end overlaps the kept part by one sample, so
                # the dashed line meets the solid one instead of a gap.
                hidden = []
                if k0 > 0:
                    hidden.append((x[:k0 + 1], y[:k0 + 1]))
                if k1 < len(x):
                    hidden.append((x[k1 - 1:], y[k1 - 1:]))
                traces.append(Trace(scan, x[k0:k1], y[k0:k1], scan.colour,
                                    None, hidden, k0))
        self.traces = traces
        if not keep_view:
            self._view_x = self._view_y = None
        self._sync_blink()
        self.invalidate()

    def invalidate(self):
        self._sync_font()
        self._cache = None
        self.update()

    def figure_font(self):
        """The figure's font: the house style's FAMILY, at the base size.

        Every text on the figure starts from this and sets only its own
        size (and italic, per character, through the markup), so one
        setting changes the typeface of all of it."""
        font = QFont(self._base_font)
        family = (style.figure_value(self.doc, "font_family")
                  if self.doc is not None else "")
        if family:
            font.setFamilies([family] + [f for f in FALLBACK_FAMILIES
                                         if f != family])
            font.setStyleHint(QFont.SansSerif)
        return font

    def _sync_font(self):
        """The widget's own font follows the figure's, so that measuring
        the margins (which reads `self.font()`) sees the same typeface."""
        font = self.figure_font()
        if font != self.font():
            self.setFont(font)

    def style_of(self, obj, attr):
        """The value `obj.attr` is drawn with, the house style filling in.

        Every size and alignment the drawing uses is read HERE rather than
        off the object, because None on the object means "not chosen" - see
        `core/style.py`.
        """
        return style.value(self.doc, obj, attr)

    def drawable(self):
        return [t for t in self.traces if t.missing is None]

    # ---------------------------------------------------------------- ranges
    def data_x(self):
        lows, highs = [], []
        for trace in self.drawable():
            if trace.x is not None and len(trace.x):
                lows.append(float(np.nanmin(trace.x)))
                highs.append(float(np.nanmax(trace.x)))
        if not lows:
            return (0.0, 100.0)
        lo, hi = min(lows), max(highs)
        return (lo, hi) if hi > lo else (lo, lo + 1.0)

    def data_y(self):
        lows, highs = [], []
        for trace in self.drawable():
            if trace.y is not None and len(trace.y):
                lows.append(float(np.nanmin(trace.y)))
                highs.append(float(np.nanmax(trace.y)))
        for trace in self.traces:
            if trace.missing is not None:
                lows.append(float(trace.scan.offset))
                highs.append(float(trace.scan.offset))
        if not lows:
            return (-1.0, 1.0)
        lo, hi = min(lows), max(highs)
        if hi <= lo:
            lo, hi = lo - 0.5, hi + 0.5
        pad = (hi - lo) * float(self.y_margin)
        return (lo - pad, hi + pad)

    def view_x(self):
        return self._view_x or self.data_x()

    def view_y(self):
        return self._view_y or self.data_y()

    def set_view_x(self, lo, hi):
        if hi > lo:
            self._view_x = (float(lo), float(hi))
            self.invalidate()
            self.view_changed.emit()

    def set_view_y(self, lo, hi):
        if hi > lo:
            self._view_y = (float(lo), float(hi))
            self.invalidate()
            self.view_changed.emit()

    # ----------------------------------------------------------- view history
    # Zoom and pan are on the undo stack (Christian, round 9: "if I zoom in on
    # a feature several times, I want to go back with Ctrl+Z"). The plot
    # decides what ONE step is and hands it over as `view_committed`; the
    # window puts it on the stack beside everything else.
    def view_state(self):
        """The framing, as the undo stack keeps it.

        The limits as stored - None meaning "fitted to the data" - plus the
        axes they are in, because a framing in W/g says nothing about an mW
        axis."""
        doc = self.doc
        context = ((doc.x_axis, doc.y_unit, getattr(doc, "x_unit", ""))
                   if doc is not None else None)
        return {"x": self._view_x, "y": self._view_y, "context": context}

    def restore_view(self, state):
        """Go back to a framing. One taken on other axes (the unit changed
        since) is meaningless as numbers, so it goes back to the fit."""
        self._view_settle.stop()
        self._view_burst = None
        if state.get("context") != self.view_state()["context"]:
            self._view_x = self._view_y = None
        else:
            self._view_x, self._view_y = state["x"], state["y"]
        self.invalidate()
        self.view_changed.emit()

    def _view_begin(self, label):
        """A view gesture is starting (or continuing): remember where from."""
        if self._view_burst is None:
            self._view_burst = (self.view_state(), label)

    def _view_touched(self, label):
        """One event of a wheel or pinch burst. The burst is one step, and it
        ends when the fingers have been still for `VIEW_SETTLE_MS`."""
        self._view_begin(label)
        self._view_settle.start()

    def commit_view(self):
        """End the view gesture in progress and hand it over as one step.

        Called by the settle timer, by the end of a zoom box or a pan drag,
        and by the window before an undo or redo - so a Ctrl+Z pressed while
        the fingers are still settling undoes the zoom, rather than undoing
        the step before it and then throwing the redo history away when the
        zoom lands on the stack afterwards.
        """
        self._view_settle.stop()
        burst, self._view_burst = self._view_burst, None
        if burst is None:
            return False
        before, label = burst
        after = self.view_state()
        if (before["x"], before["y"]) == (after["x"], after["y"]):
            return False
        self.view_committed.emit(before, after, label)
        return True

    def at_home_x(self):
        return self._view_x is None or _close(self._view_x, self.data_x())

    def at_home_y(self):
        return self._view_y is None or _close(self._view_y, self.data_y())

    def reset_view(self):
        """`F`: x first, then y. Staged, the way the PXRD window does it -
        one key that puts everything back at once cannot say "just the x
        range, please"."""
        if self.at_home_x() and self.at_home_y():
            return False
        self._view_begin("fit")
        if not self.at_home_x():
            self._view_x = None
        else:
            self._view_y = None
        self.invalidate()
        self.view_changed.emit()
        self.commit_view()
        return True

    def fit(self):
        self._view_begin("fit")
        self._view_x = self._view_y = None
        self.invalidate()
        self.view_changed.emit()
        self.commit_view()

    # --------------------------------------------------------------- mapping
    # ------------------------------------------------------------------ page
    #: Pane pixels kept round a figure shown at a fixed size or aspect.
    PAGE_PAD = 14

    def layout_mode(self):
        """How the figure is sized: `core/figure.py`'s window, aspect, size."""
        doc = self.doc
        layout = getattr(doc, "figure", None) if doc is not None else None
        if layout is None or not layout.is_valid():
            return figure_module.MODE_WINDOW
        return layout.mode

    def canvas_size(self):
        """The figure's own size, in drawing units (96 per inch).

        The pane itself; the largest rectangle of the aspect ratio that fits
        in it; or the EXACT physical size - which does not depend on the pane
        at all, so an export comes out the same whatever the window is doing.
        """
        mode = self.layout_mode()
        width, height = float(self.width()), float(self.height())
        if mode == figure_module.MODE_SIZE:
            return self.doc.figure.size_px()
        if mode == figure_module.MODE_ASPECT:
            layout = self.doc.figure
            ratio = float(layout.aspect_w) / float(layout.aspect_h)
            room_w = max(10.0, width - 2 * self.PAGE_PAD)
            room_h = max(10.0, height - 2 * self.PAGE_PAD)
            if room_w / room_h > ratio:
                return room_h * ratio, room_h
            return room_w, room_w / ratio
        return width, height

    def page(self):
        """`(dx, dy, k)`: where the figure's corner sits in the pane, and how
        many pane pixels one drawing unit takes. A figure of exact size is
        scaled to fit the pane; the drawing inside it is not re-laid-out."""
        mode = self.layout_mode()
        if mode == figure_module.MODE_WINDOW:
            return 0.0, 0.0, 1.0
        canvas_w, canvas_h = self.canvas_size()
        width, height = float(self.width()), float(self.height())
        k = 1.0
        if mode == figure_module.MODE_SIZE:
            k = max(0.05, min((width - 2 * self.PAGE_PAD) / canvas_w,
                              (height - 2 * self.PAGE_PAD) / canvas_h))
        return (width - canvas_w * k) / 2.0, (height - canvas_h * k) / 2.0, k

    def to_figure(self, pos):
        """A point in the pane, in the figure's drawing units."""
        dx, dy, k = self.page()
        return QPointF((pos.x() - dx) / k, (pos.y() - dy) / k)

    def to_widget(self, point):
        """A point of the figure, in the pane's pixels."""
        dx, dy, k = self.page()
        return QPointF(point.x() * k + dx, point.y() * k + dy)

    def _slop(self):
        """`DRAG_SLOP` screen pixels, in drawing units."""
        return DRAG_SLOP / self.page()[2]

    def margins(self):
        """`(left, right, top, bottom)`, in drawing units.

        EXACT for a figure of exact size: the axes box goes where the margins
        put it and nowhere else, and the numbers and captions live inside
        them (`overflow` says what does not fit). Two figures with the same
        size and margins then have the same axes box to the hundredth of a
        millimetre, whatever their numbers say - Christian's two stacks side
        by side in Word.

        Otherwise sized to the FONTS: the numbers and captions decide how
        much room the plot gives them, on whichever side each axis is.
        """
        doc = self.doc
        if doc is None:
            return 34.0, float(_RIGHT), float(_TOP), 26.0
        if self.layout_mode() == figure_module.MODE_SIZE:
            return doc.figure.margins_px()
        return self.needed_margins()

    def needed_margins(self):
        """What the numbers and captions need on each side, in drawing
        units: the automatic margins, and what an exact one is checked
        against."""
        doc = self.doc
        sides = {"left": 8.0, "right": float(_RIGHT), "top": float(_TOP),
                 "bottom": 8.0}
        for axis in (doc.axes["x"], doc.axes["y"]):
            side = self.axis_side(axis)
            sides[side] = max(sides[side], self.axis_reach(axis))
        return sides["left"], sides["right"], sides["top"], sides["bottom"]

    def overflow(self):
        """`[(side, needed, set), ...]` in drawing units, for each margin of
        a figure of exact size that is too narrow for what it holds."""
        if self.doc is None or self.layout_mode() != figure_module.MODE_SIZE:
            return []
        out = []
        for side, need, have in zip(("left", "right", "top", "bottom"),
                                    self.needed_margins(), self.margins()):
            if need > have + 0.5:
                out.append((side, need, have))
        return out

    @staticmethod
    def axis_side(axis):
        side = getattr(axis, "side", None)
        if axis.which == "x":
            return side if side in ("bottom", "top") else "bottom"
        return side if side in ("left", "right") else "left"

    def axis_reach(self, axis):
        """How far an axis's ticks, numbers and caption reach out from the
        axes box, in drawing units."""
        reach = self.tick_extent(axis)
        if axis.visible:
            font = QFont(self.font())
            font.setPointSizeF(self.style_of(axis, "label_size"))
            reach += self.caption_gap(axis) + QFontMetrics(font).height() + 4
        return reach + 2.0

    def caption_gap(self, axis):
        """Pixels between an axis's numbers and its caption."""
        return float(_clamp(self.style_of(axis, "label_gap"), 0.0, 80.0))

    def _tick_out(self, axis):
        """How far ticks pointing OUT of the box reach into the margin."""
        return (0.0 if axis.ticks_inward
                else float(getattr(axis, "tick_length", 7.0)))

    def tick_extent(self, axis):
        """How far an axis's ticks and numbers reach out from it, in drawing
        units: the numbers' height beside the x axis, the widest of them
        beside the y axis - the edge a caption keeps its distance from."""
        out = self._tick_out(axis)
        if not getattr(axis, "show_numbers", True):
            return out + 3.0
        font = QFont(self.font())
        font.setPointSizeF(self.style_of(axis, "tick_size"))
        metrics = QFontMetrics(font)
        if axis.which == "x":
            return out + 3.0 + metrics.height()
        return out + 8.0 + self._widest_y_number(metrics)

    def tick_step(self, axis, lo, hi):
        """The spacing of an axis's numbered ticks: the axis's own
        `major_step`, or a round number that gives about eight (x) or six
        (y). A step so small it would draw hundreds falls back to the
        automatic one."""
        which = getattr(axis, "which", "x")
        chosen = getattr(axis, "major_step", None)
        if chosen and chosen > 0 and (hi - lo) / float(chosen) <= 200:
            return float(chosen)
        return _nice_step(hi - lo, 8 if which == "x" else 6)

    def _widest_y_number(self, metrics):
        lo, hi = self.view_y()
        step = self.tick_step(self.doc.axes["y"] if self.doc else None,
                              lo, hi)
        widest = 0
        value = math.ceil(lo / step) * step
        while value <= hi + 1e-9:
            widest = max(widest, metrics.horizontalAdvance(
                self.tick_text(self.doc.axes["y"] if self.doc else None,
                               value, "y")))
            value += step
        return float(widest)

    @staticmethod
    def tick_text(axis, value, which):
        """An axis number: the axis's own format, or as few digits as the
        tick spacing needs."""
        spec = getattr(axis, "number_format", None)
        if spec:
            return numbers.write(value, spec)
        return "{:g}".format(round(value, 6 if which == "x" else 10))

    def plot_rect(self):
        """The axes box, in drawing units - FRACTIONAL, so an exact margin
        stays exact rather than being rounded to a whole unit (a quarter of
        a millimetre, six pixels at 600 dpi)."""
        left, right, top, bottom = self.margins()
        canvas_w, canvas_h = self.canvas_size()
        return QRectF(left, top, max(10.0, canvas_w - left - right),
                      max(10.0, canvas_h - top - bottom))

    def x_to_px(self, value, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_x()
        return rect.left() + (value - lo) / max(hi - lo, 1e-12) * rect.width()

    def px_to_x(self, px, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_x()
        return lo + (px - rect.left()) / max(1.0, rect.width()) * (hi - lo)

    def y_to_px(self, value, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_y()
        return (rect.top() + rect.height()
                * (1.0 - (value - lo) / max(hi - lo, 1e-12)))

    def px_to_y(self, px, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_y()
        return lo + (1.0 - (px - rect.top()) / max(1.0, rect.height())) * (hi - lo)

    def y_per_px(self, rect=None):
        rect = rect or self.plot_rect()
        lo, hi = self.view_y()
        return (hi - lo) / max(1.0, rect.height())

    # ------------------------------------------------------------ navigation
    def cycle_mode(self, cycle):
        current = self._mode if self._mode in cycle else None
        index = cycle.index(current) if current in cycle else -1
        self.set_mode(cycle[(index + 1) % len(cycle)])

    def set_mode(self, mode):
        self._drag = None
        self._mode = mode
        self._box = None
        self._sync_pointer()
        self.mode_changed.emit(self.MODE_TEXT.get(mode, self.SELECT_TEXT))
        self.update()

    def mode(self):
        return self._mode

    def _sync_pointer(self):
        """Hide the system pointer where the reticle is standing in for it.

        Two pointers on one plot is one too many, and the reticle IS the
        pointer in plain select mode. A zoom or pan mode brings its own
        cursor back, and so does the area outside the axes, where there is no
        reticle to take over.
        """
        if self._mode:
            self.setCursor(self.MODE_CURSOR.get(self._mode, Qt.ArrowCursor))
            return
        inside = (self._cursor is not None
                  and self.plot_rect().contains(self._cursor))
        if inside and self._measure is not None:
            # The reticle is not drawn while cursors or gizmos are up, so
            # the system pointer must be: hidden, it left nothing on screen
            # to aim at a gizmo with (Christian, round 15). Over a handle
            # it says the handle moves sideways.
            over = (self._cursor_drag is not None
                    or self.cursor_at(self._cursor) is not None)
            self.setCursor(Qt.SizeHorCursor if over else Qt.CrossCursor)
            return
        self.setCursor(Qt.BlankCursor if inside else Qt.ArrowCursor)

    def wheelEvent(self, ev):
        """Trackpad first, which is the machine this is used on.

        * **Two fingers = pan.** A swipe moves the view by the distance the
          fingers moved, in both directions, because that is what dragging a
          sheet of paper does. With Shift the axes swap, so a horizontal pan
          is available on a trackpad that only reports vertical scrolling.
        * **Pinch = zoom.** A Windows precision touchpad sends a pinch as
          Ctrl+wheel, so Ctrl+wheel zooms BOTH axes about the cursor. (A
          native pinch gesture, where Qt delivers one, arrives in `event`
          below and lands in the same place.)
        * **A mouse wheel scales y about y = 0**, and Ctrl+wheel zooms both
          about the cursor. Zero is the one height that never moves
          (Christian, round 13): a stack is built upwards from it, so the
          scans grow and shrink without the baseline wandering off.

        The view is what moves. The data is never scaled: in the PXRD window
        the plain wheel scales intensity, and that gesture must not exist
        here, because a DSC curve whose height changed under the hand is a
        curve whose W/g axis is a lie.
        """
        mods = ev.modifiers()
        pixels = ev.pixelDelta()
        angles = ev.angleDelta()
        if not pixels.isNull():
            dx, dy = float(pixels.x()), float(pixels.y())
        else:
            # This touchpad reports notches rather than pixels, so they are
            # converted to a distance instead of being read as "a mouse
            # wheel". Treating them as a wheel is what made a two-finger
            # swipe zoom when it should have panned.
            dx = angles.x() / PANE_WHEEL_UNITS * PANE_STEP_PIXELS
            dy = angles.y() / PANE_WHEEL_UNITS * PANE_STEP_PIXELS
        if mods & Qt.ControlModifier:
            # Pinch, which Windows delivers as Ctrl+wheel: zoom both axes
            # about the cursor.
            notches = (dy or dx) / PANE_STEP_PIXELS
            if notches:
                self._view_touched("zoom")
                self.zoom_at(self.to_figure(ev.position()),
                             WHEEL_STEP ** notches, both=True)
        elif mods & Qt.ShiftModifier:
            # Shift turns the swipe into a PAN, and an omnidirectional one:
            # both components are used as they arrive, so the canvas follows
            # the fingers instead of being locked to an axis.
            if dx or dy:
                self._view_touched("pan")
                self.pan_by(-dx, -dy)
        elif dy or dx:
            # The plain swipe scales the y axis, the gesture Christian reaches
            # for constantly on a stack, about y = 0 rather than the cursor:
            # zero stays where it is and only the scale changes. It moves
            # the VIEW's limits and never the data.
            self._view_touched("zoom")
            self.scale_y(WHEEL_STEP ** ((dy or dx) / PANE_STEP_PIXELS))
        ev.accept()

    def event(self, ev):
        """Catch a native pinch, where the platform sends one - and, while
        S or R is live, claim every key before the window's shortcuts see
        it: M there chooses a pivot, not the x range."""
        # getattr: Qt sends events while the widget is still being built.
        if (getattr(self, "_scale", None) is not None
                and ev.type() == ev.Type.ShortcutOverride):
            ev.accept()
            return True
        try:
            is_gesture = ev.type() == ev.Type.NativeGesture
        except AttributeError:
            is_gesture = False
        if is_gesture and ev.gestureType() == Qt.ZoomNativeGesture:
            self._view_touched("zoom")
            self.zoom_at(self.to_figure(ev.position()),
                         1.0 + float(ev.value()), both=True)
            return True
        return QWidget.event(self, ev)

    def zoom_at(self, pos, factor, both=False):
        """Zoom the view about the cursor: y always, x as well when `both`."""
        if factor <= 0:
            return
        lo, hi = self.view_y()
        anchor = self.px_to_y(pos.y())
        span = (hi - lo) / factor
        frac = (anchor - lo) / max(hi - lo, 1e-12)
        self.set_view_y(anchor - span * frac, anchor + span * (1 - frac))
        if both:
            lo, hi = self.view_x()
            anchor = self.px_to_x(pos.x())
            span = (hi - lo) / factor
            frac = (anchor - lo) / max(hi - lo, 1e-12)
            self.set_view_x(anchor - span * frac, anchor + span * (1 - frac))

    def scale_y(self, factor):
        """Scale the y axis about y = 0: zero keeps its place on screen."""
        if factor <= 0:
            return
        lo, hi = self.view_y()
        self.set_view_y(lo / factor, hi / factor)

    def pan_by(self, dx_px, dy_px):
        """Move the view by a distance in PIXELS."""
        rect = self.plot_rect()
        x0, x1 = self.view_x()
        y0, y1 = self.view_y()
        dx = dx_px / max(1.0, rect.width()) * (x1 - x0)
        dy = -dy_px / max(1.0, rect.height()) * (y1 - y0)
        self._view_x = (x0 + dx, x1 + dx)
        self._view_y = (y0 + dy, y1 + dy)
        self.invalidate()
        self.view_changed.emit()

    # ------------------------------------------------------------- selection
    def pick_radius(self):
        """How close, in pixels, the pointer must be to an object to mean it.

        The user's own setting (Edit > Settings, "Pick distance"): it decides
        what a press lands on - and so whether a drag acts on an object or
        draws a box - and a trackpad and a mouse want different numbers.
        """
        # In PANE pixels, whatever the figure's scale on screen.
        return float(style.preference("pick_radius")) / self.page()[2]

    def objects_at(self, pos, radius=None):
        """What is under or NEAR the cursor, nearest first.

        Everything within the pick distance counts, measured to the drawn
        curve or to the edge of a label's box, and the nearest wins; a tie
        (the pointer inside two things) goes to whatever is drawn on top -
        artists over analysis labels over curves. It used to be exact boxes
        in a fixed order, which made a label a much smaller target than a
        curve, and "near" meant something different for each kind.

        The axis captions and spines keep their own exact bands: they sit in
        the margin, and a generous radius there would swallow the corner of
        the plot where a box select starts.
        """
        doc = self.doc
        if doc is None:
            return []
        radius = self.pick_radius() if radius is None else float(radius)
        # Either flavour of point: a mouse event carries a QPointF, a
        # rectangle's centre a QPoint, and both are handed to this.
        point = QPointF(pos.x(), pos.y())
        hits = []                  # (distance, rank, obj, axis hit or None)

        def near(obj, box, rank):
            gap = _rect_distance(QRectF(box), point)
            if gap <= radius:
                hits.append((gap, rank, obj, None))

        if doc.arrow.visible:
            near(doc.arrow, self._arrow_rect(), 0)
        legend_box = self.rotated_bounds(doc.legend, self.legend_rect())
        if legend_box is not None:
            near(doc.legend, legend_box, 1)
        for label, box in self._text_boxes:
            near(label, box, 2)
        for analysis, box in self._analysis_boxes:
            near(analysis, box, 3)
        for marker, box in self._marker_boxes:
            near(marker, box, 3)
        for axis, box in self._axis_boxes:
            gap = _rect_distance(QRectF(box), point)
            if gap <= 4.0:
                hits.append((gap, 4, axis, "caption"))
        for which in ("x", "y"):
            axis = doc.axes.get(which)
            if axis is None or not axis.visible:
                continue
            if self.axis_spine_rect(which).contains(point):
                hits.append((0.0, 5, axis, "spine"))
            elif self.axis_numbers_rect(which).contains(point):
                hits.append((0.0, 5, axis, "numbers"))
        for trace, box in self._label_boxes:
            if QRectF(box).contains(point):
                hits.append((0.0, 6, trace.scan, None))
        trace, gap = self._nearest_trace(point)
        if trace is not None and gap <= radius:
            hits.append((gap, 7, trace.scan, None))
        hits.sort(key=lambda hit: (hit[0], hit[1]))
        found = []
        for _gap, _rank, obj, axis_hit in hits:
            if obj in found:
                continue
            if axis_hit is not None and not any(
                    isinstance(o, model.Axis) for o in found):
                self._axis_hit = axis_hit
            found.append(obj)
        return found

    def object_at(self, pos):
        found = self.objects_at(pos)
        return found[0] if found else None

    def _nearest_trace(self, pos):
        """`(trace, distance)` for the drawn curve nearest the cursor.

        Measured against the points that were actually drawn (`px`/`py` from
        the last render), which is what makes this correct for a cooling
        segment: there is no "the y at this x" when x doubles back, but there
        is always a nearest drawn point.
        """
        best, best_gap = None, 1e30
        for trace in self.traces:
            if trace.px is None or not len(trace.px):
                if trace.missing is not None:
                    gap = abs(self.y_to_px(trace.scan.offset) - pos.y())
                    if gap < best_gap:
                        best, best_gap = trace, gap
                continue
            gap = float(np.min(np.hypot(trace.px - pos.x(),
                                        trace.py - pos.y())))
            if gap < best_gap:
                best, best_gap = trace, gap
        return best, best_gap

    def _trace_at(self, pos):
        """The trace whose drawn curve is within the pick distance, or None."""
        trace, gap = self._nearest_trace(pos)
        return trace if gap <= self.pick_radius() else None

    def drag_target(self, pos):
        """What a press-and-drag starting at `pos` acts on, or None.

        `("interval", scan)` on a CURVE - marking a stretch of it to analyse;
        `("move", obj)` on anything drawn on the figure that moves; None
        everywhere else, and there the drag draws a box. The name readout
        beside a hovered curve and an axis SPINE are not targets: there is no
        curve under the pointer to mark, and a spine does not move.
        """
        obj = self.object_at(pos)
        if obj is None:
            return None
        if isinstance(obj, model.Scan):
            trace = self._trace_at(pos)
            if trace is not None and trace.scan is obj:
                return ("interval", obj)
            return None
        if self._frame_part(obj):
            return None
        if self._fields_of(obj):
            return ("move", obj)
        return None

    def select_in_box(self, start, end, add=False):
        """Select everything inside the dragged rectangle.

        A trace counts as inside when any of the points that were DRAWN for
        it falls in the box, which is the same "what you see is what you
        pick" rule the click uses. A box smaller than the drag slop is a
        click on empty space, and clears the selection.
        """
        doc = self.doc
        if doc is None:
            return []
        box = QRectF(QPointF(min(start.x(), end.x()), min(start.y(), end.y())),
                     QPointF(max(start.x(), end.x()), max(start.y(), end.y())))
        if box.width() < self._slop() and box.height() < self._slop():
            if not add:
                doc.select_all(False)
            self.selection_changed.emit()
            self.update()
            return []
        chosen = []
        for trace in self.traces:
            if trace.px is None or not len(trace.px):
                if trace.missing is not None:
                    y = self.y_to_px(trace.scan.offset)
                    if box.top() <= y <= box.bottom():
                        chosen.append(trace.scan)
                continue
            inside = ((trace.px >= box.left()) & (trace.px <= box.right())
                      & (trace.py >= box.top()) & (trace.py <= box.bottom()))
            if bool(inside.any()):
                chosen.append(trace.scan)
        if doc.arrow.visible and box.intersects(QRectF(self._arrow_rect())):
            chosen.append(doc.arrow)
        for marker, marker_box in self._marker_boxes:
            if box.intersects(QRectF(marker_box)):
                chosen.append(marker)
        if add:
            for obj in chosen:
                obj.selected = True
        else:
            doc.select_only(chosen)
        self.selection_changed.emit()
        self.update()
        return chosen

    def select_at(self, pos, add=False):
        obj = self.object_at(pos)
        doc = self.doc
        if doc is None:
            return None
        if obj is not None and self._frame_part(obj):
            return None
        if obj is None:
            if not add:
                doc.select_all(False)
                self.selection_changed.emit()
                self.update()
            return None
        if add:
            obj.selected = not obj.selected
        else:
            # A click makes this the ONLY selected thing, even inside a
            # bigger selection. Keeping the others only made sense while a
            # press on a selected curve could drag the whole selection, and
            # a press no longer moves anything.
            doc.select_only([obj])
        self.selection_changed.emit()
        self.update()
        return obj

    # ------------------------------------------------------------ transforms
    def start_grab(self, objs=None):
        """Start a `G` move: no button held, the cursor drives it.

        Blender's grab, in a plot, and the two kinds of object move
        differently ON PURPOSE:

        * a **scan** moves in y only. Shifting a DSC curve along the
          temperature axis would be a claim about the measurement rather than
          about the figure - Christian: "shifting along x is nonsense" - so
          it does not exist, not even as a locked axis.
        * an **artist** (the heat-flow arrow, and whatever joins it later)
          moves freely in both. It is a label on the figure, not data, and
          its position says nothing about a measurement.
        """
        doc = self.doc
        if doc is None:
            return False
        objs = [o for o in (objs if objs is not None else doc.selected())
                if self._fields_of(o)]
        if not objs:
            return False
        pos = self._cursor or QPointF(self.plot_rect().center())
        self._move = {
            "objs": objs,
            "start": pos,
            "origin": [self._value_of(o) for o in objs],
            "stored": [self._stored_of(o) for o in objs],
            "typed": "",
            "axis": None,
            "keyboard": True,
            "moved": True,
        }
        self.mode_changed.emit(
            "GRAB - move, type a number, X/Y to lock an axis, Enter, Esc")
        self.update()
        return True

    @staticmethod
    def is_artist(obj):
        """True for the things that are figure furniture rather than data.

        The x restriction applies to MEASUREMENTS. An artist - the heat-flow
        arrow, a caption - goes where it is put, in both directions.
        """
        # The BASE CLASS, not a list of kinds: a new artist should not have
        # to be added here to be draggable. Listing them by name is how the
        # legend arrived unable to move.
        return isinstance(obj, model.Artist)

    @staticmethod
    def _fields_of(obj):
        """Which properties a drag writes, per kind of object.

        * artists: both plot fractions.
        * an analysis: the distance from its label to the curve, and nothing
          else. The movement is locked vertically so a label stays over the
          feature it names, and the leader arrow stretches to match.
        * an axis: along the axis, and away from it - both clamped into the
          margin by `axis_label_rect`, so a caption cannot be dragged over
          the data.
        * a scan: its offset, in data units.
        """
        if PlotWidget.is_artist(obj):
            return ("x", "y")
        if isinstance(obj, model.OffsetMarker):
            return ("at", "dy")
        if isinstance(obj, model.Analysis):
            return ("label_dy",)
        if isinstance(obj, model.Axis):
            return ("label_along", "label_gap")
        return ("offset",)

    def _value_of(self, obj):
        """An object's transformable state, as a tuple of its own fields.

        An analysis whose `label_dy` is still None (the automatic side) hands
        over the offset it is BEING DRAWN at, so a drag starts where the eye
        sees the label rather than jumping.
        """
        if isinstance(obj, model.Analysis) and obj.label_dy is None:
            return (self.effective_label_dy(obj),)
        if isinstance(obj, model.OffsetMarker):
            # The sample it is DRAWN at, so a drag starts under the hand
            # (and a moved marker is pinned to a point ON its curve).
            return (self.marker_at(obj), self.marker_dy(obj))
        # `style_of`, not getattr: a caption's gap is None until dragged.
        return tuple(float(self.style_of(obj, name))
                     for name in self._fields_of(obj))

    def _stored_of(self, obj):
        """An object's transformable fields EXACTLY as stored, None and all.

        What a cancelled or undone move must put back. Writing back the value
        it was DRAWN at instead would turn "follow the house style" into a
        fixed number the moment a drag was cancelled."""
        return tuple(getattr(obj, name) for name in self._fields_of(obj))

    def effective_label_dy(self, analysis):
        """The offset an analysis label is drawn at, automatic or chosen."""
        if analysis.label_dy is not None:
            return float(analysis.label_dy)
        rect = self.plot_rect()
        for trace in self.traces:
            if trace.scan is analysis.scan:
                return self.label_offset(analysis, trace, rect)
        return -46.0

    def _apply_value(self, obj, value):
        if self.is_artist(obj):
            # Clamped only where the numbers ARE fractions. A data-space
            # artist stores a temperature and a heat flow, and clamping those
            # to 0..1 is what sent one to "0.99 degC" the moment it was moved.
            if getattr(obj, "space", model.SPACE_RELATIVE) == model.SPACE_DATA:
                obj.x, obj.y = float(value[0]), float(value[1])
            else:
                obj.x = float(min(0.99, max(0.01, value[0])))
                obj.y = float(min(0.99, max(0.01, value[1])))
        elif isinstance(obj, model.Analysis):
            obj.label_dy = float(value[0])
        elif isinstance(obj, model.OffsetMarker):
            obj.at = value[0]
            obj.dy = float(value[1])
        elif isinstance(obj, model.Axis):
            obj.label_along = float(min(1.0, max(0.0, value[0])))
            obj.label_gap = float(max(0.0, value[1]))
        else:
            obj.offset = float(value[0])

    def _artist_origin_px(self, artist, origin, rect):
        """Where an artist stood when the gesture began, in pixels."""
        if getattr(artist, "space", model.SPACE_RELATIVE) == model.SPACE_DATA:
            return (float(self.x_to_px(origin[0], rect)),
                    float(self.y_to_px(origin[1], rect)))
        return (rect.left() + float(origin[0]) * rect.width(),
                rect.top() + float(origin[1]) * rect.height())

    def _typed_value(self):
        state = self._move
        if not state or not state["typed"]:
            return None
        try:
            return float(state["typed"].replace(",", "."))
        except ValueError:
            return None

    def _update_move(self, pos, mods=Qt.NoModifier):
        """Move everything in the gesture to where the cursor now is.

        Pixels to values, per kind of object:

        * an artist takes the cursor's own motion, in plot fractions. DOWN on
          the screen is a bigger `y`, because the fraction is measured from
          the top of the plot - getting that backwards is what made dragging
          the arrow feel inverted.
        * a scan takes the motion in DATA units, where up is more, because
          that is what the y axis says.
        """
        state = self._move
        typed = self._typed_value()
        rect = self.plot_rect()
        dx_px = pos.x() - state["start"].x()
        dy_px = pos.y() - state["start"].y()
        if mods & Qt.ShiftModifier:                # precision, as in Blender
            dx_px *= 0.1
            dy_px *= 0.1
        axis = state.get("axis")
        if axis == "x":
            dy_px = 0.0
        elif axis == "y":
            dx_px = 0.0
        for obj, origin in zip(state["objs"], state["origin"]):
            if self.is_artist(obj):
                # A typed number is not offered for an artist: "0.25" says
                # nothing about a position on a plot, and the drag is the
                # gesture that means something here. Worked in PIXELS and
                # handed back in the artist's own space, so a data-space
                # artist moves under the hand exactly like a relative one.
                ox, oy = self._artist_origin_px(obj, origin, rect)
                self.set_artist_point(
                    obj, _clamp(ox + dx_px, rect.left(), rect.right()),
                    _clamp(oy + dy_px, rect.top(), rect.bottom()), rect)
                continue
            if isinstance(obj, model.Analysis):
                # Vertical only: the label stays over its feature and the
                # leader arrow stretches.
                self._apply_value(obj, (origin[0] + dy_px,))
                continue
            if isinstance(obj, model.OffsetMarker):
                # ALONG its curve, sample by sample, as far as the hand
                # moved sideways - a curve that doubles back is walked, not
                # looked up by temperature - and the number up or down.
                self._apply_value(obj, (self._walked(obj, origin[0], dx_px,
                                                     rect),
                                        origin[1] + dy_px))
                continue
            if isinstance(obj, model.Axis):
                # The gap grows AWAY from the axes box, whichever side the
                # axis is on: down under a bottom axis, up over a top one,
                # left of a left one, right of a right one.
                side = self.axis_side(obj)
                if obj.which == "x":
                    away = dy_px if side == "bottom" else -dy_px
                    self._apply_value(obj, (
                        origin[0] + dx_px / max(1.0, rect.width()),
                        origin[1] + away))
                else:
                    away = -dx_px if side == "left" else dx_px
                    self._apply_value(obj, (
                        origin[0] - dy_px / max(1.0, rect.height()),
                        origin[1] + away))
                continue
            if typed is not None:
                delta = typed
            else:
                delta = -dy_px * self.y_per_px(rect)   # up on screen is more
                if mods & Qt.ControlModifier:
                    snap = _nice_step(self.view_y()[1] - self.view_y()[0], 20)
                    delta = round(delta / snap) * snap
            self._apply_value(obj, (origin[0] + delta,))
        for obj in state["objs"]:
            if isinstance(obj, model.Scan):
                obj._cache_key = None
        self.rebuild()

    def _finish_move(self, cancel=False):
        state, self._move = self._move, None
        if state is None:
            return
        stored = state.get("stored") or [None] * len(state["objs"])
        if cancel:
            for obj, origin, raw in zip(state["objs"], state["origin"],
                                        stored):
                self._restore(obj, origin, raw)
            self.rebuild()
            self.mode_changed.emit(self.MODE_TEXT.get(self._mode,
                                                      self.SELECT_TEXT))
            return
        changes = []
        for obj, origin, raw in zip(state["objs"], state["origin"], stored):
            value = self._value_of(obj)
            if value == origin:
                self._restore(obj, origin, raw)
                continue
            # Hand the window the BEFORE state as the current value, so the
            # undo step it builds covers the whole gesture rather than the
            # last pixel of it - and restores what was STORED, None and all.
            self._restore(obj, origin, raw)
            for name, new in zip(self._fields_of(obj), value):
                changes.append((obj, name, new))
        self.mode_changed.emit(self.MODE_TEXT.get(self._mode,
                                                   self.SELECT_TEXT))
        if changes:
            self.transform_done.emit(changes,
                                     self._move_label(list(state["objs"])))
        else:
            self.rebuild()

    #: What the undo history calls moving one of these.
    MOVE_NAMES = ((model.HeatFlowArrow, "arrow"), (model.Legend, "legend"),
                  (model.TextLabel, "label"),
                  (model.Analysis, "analysis label"),
                  (model.OffsetMarker, "offset marker"),
                  (model.Axis, "axis caption"))

    @classmethod
    def _move_label(cls, objs):
        """"move arrow", "move legend", "move 2 scan(s)" - what was moved.

        Every artist used to be recorded as "move arrow", which is what the
        undo menu then said about a label."""
        scans = [obj for obj in objs if isinstance(obj, model.Scan)]
        if len(objs) == 1 and not scans:
            for kind, name in cls.MOVE_NAMES:
                if isinstance(objs[0], kind):
                    return "move " + name
        if scans and len(scans) == len(objs):
            return "move {} scan(s)".format(len(scans))
        return "move {} object(s)".format(len(objs))

    def _restore(self, obj, origin, raw):
        """Put an object back as it was before a move: exactly as stored when
        that is known, else at the value it was drawn with."""
        if raw is None:
            self._apply_value(obj, origin)
            return
        for name, value in zip(self._fields_of(obj), raw):
            setattr(obj, name, value)

    def moving(self):
        """True while a grab or a drag is live. For tests and the status bar."""
        return self._move is not None

    # ------------------------------------------------ S and R: Blender's
    #: What `S` scales, per kind of artist: every size it has, so the whole
    #: object grows or shrinks together. Only figure furniture: nothing here
    #: stands for a measurement.
    SCALE_FIELDS = ((model.HeatFlowArrow, ("head_length", "head_width",
                                           "tail_width", "tail_length",
                                           "size")),
                    (model.Legend, ("size", "sample")),
                    (model.TextLabel, ("size",)))

    #: The point a scale or a rotation is ABOUT, as `(fx, fy)` of the
    #: artist's box - 0 left/top, 1 right/bottom, as `Artist.anchor` - and
    #: where it starts: a scale keeps the bottom left where it is, a
    #: rotation turns about the centre (Christian, round 17).
    PIVOT_START = {"scale": (0.0, 1.0), "rotate": (0.5, 0.5)}
    #: How often the snapped rotation steps, in degrees (Ctrl).
    ROTATE_SNAP = 15.0

    @classmethod
    def scale_fields(cls, obj):
        if not getattr(obj, "can_scale", False):
            return ()
        for kind, fields in cls.SCALE_FIELDS:
            if isinstance(obj, kind):
                return fields
        return ()

    def can_transform(self, mode, obj):
        if mode == "scale":
            return bool(self.scale_fields(obj))
        return self.is_artist(obj) and bool(getattr(obj, "can_rotate", False))

    def start_scale(self, objs=None):
        """Blender's S: the cursor's distance from the pivot scales the
        selected artists - further out is bigger - until a click or Enter;
        Esc or the right button puts them back. A typed number is the
        factor; Shift is precision, Ctrl snaps to tenths. X, Y, M and C
        choose the point it is about (`pivot_key`)."""
        return self._start_transform("scale", objs)

    def start_rotate(self, objs=None):
        """Blender's R: the cursor's angle about the pivot turns the
        selected artists. A typed number is degrees (counter-clockwise);
        Ctrl snaps to 15. X, Y, M and C choose the pivot."""
        return self._start_transform("rotate", objs)

    def _start_transform(self, mode, objs):
        doc = self.doc
        if doc is None or self._move is not None or self._scale is not None:
            return False
        objs = [o for o in (objs if objs is not None else doc.selected())
                if self.can_transform(mode, o)]
        if not objs:
            return False
        rect = self.plot_rect()
        entries = []
        for obj in objs:
            fields = (self.scale_fields(obj) if mode == "scale"
                      else ("rotation",))
            entries.append({
                "obj": obj, "fields": fields,
                "anchor": self.artist_point(obj, rect),
                "box": self.artist_box(obj, rect),
                "rotation": float(getattr(obj, "rotation", 0.0) or 0.0),
                "origin": tuple(float(self.style_of(obj, f) or 0.0)
                                for f in fields),
                "stored": tuple(getattr(obj, f) for f in fields + ("x",
                                                                     "y"))})
        self._scale = {"mode": mode, "entries": entries, "typed": "",
                       "pivot": self.PIVOT_START[mode], "last": None,
                       "factor": 1.0, "turn": 0.0}
        self._reference()
        self._transform_readout()
        self.update()
        return True

    def scaling(self):
        return self._scale is not None

    def artist_box(self, obj, rect=None):
        """An artist's box before its rotation, in figure units."""
        rect = rect or self.plot_rect()
        box = None
        if isinstance(obj, model.HeatFlowArrow):
            box = QRectF(self._arrow_rect())
        elif isinstance(obj, model.Legend):
            box = self.legend_rect(rect)
        elif isinstance(obj, model.TextLabel):
            box = self._label_box(obj, rect, QFont(self.figure_font()))
        if box is None or box.isEmpty():
            x, y = self.artist_point(obj, rect)
            box = QRectF(x - 10.0, y - 10.0, 20.0, 20.0)
        return box

    def _pivot_point(self, entry, pivot=None):
        """Where the pivot is on the screen, for one artist: the chosen
        point of its box, turned with the artist about its anchor."""
        fx, fy = pivot or self._scale["pivot"]
        box = entry["box"]
        ax, ay = entry["anchor"]
        ox = box.left() + fx * box.width() - ax
        oy = box.top() + fy * box.height() - ay
        turn = math.radians(-entry["rotation"])
        return (ax + ox * math.cos(turn) - oy * math.sin(turn),
                ay + ox * math.sin(turn) + oy * math.cos(turn))

    def _centre_of_pivots(self):
        points = [self._pivot_point(e) for e in self._scale["entries"]]
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))

    def _reference(self):
        """Measure the gesture from where the cursor is NOW, keeping the
        factor or angle reached so far - so choosing another pivot halfway
        through does not jump."""
        state = self._scale
        cx, cy = self._centre_of_pivots()
        pos = self._cursor or QPointF(cx + 60.0, cy)
        dx, dy = pos.x() - cx, pos.y() - cy
        state["start"] = max(math.hypot(dx, dy), 10.0) / max(state["factor"],
                                                             1e-6)
        state["angle0"] = math.atan2(dy, dx) - state["turn"]

    def pivot_key(self, key):
        """X, Y, M, C while S or R is live: which point it is about.

        * X puts the pivot on the LEFT edge; X again, the right; and back.
        * Y puts it on the TOP edge; Y again, the bottom; and back.
        * M is the middle OF THE EDGE just chosen: after X, halfway up the
          left (or right) edge; after Y, halfway along the top (or bottom).
        * C is the centre.

        So `S X M` scales about the middle of the left edge, `S X X` about
        the bottom right, `S Y` about the top left, `R C` turns about the
        centre. The pivot is drawn while it is live.
        """
        state = self._scale
        fx, fy = state["pivot"]
        if key == "x":
            fx = (1.0 if fx == 0.0 else 0.0) if state["last"] == "x" else 0.0
        elif key == "y":
            fy = (1.0 if fy == 0.0 else 0.0) if state["last"] == "y" else 0.0
        elif key == "m":
            if state["last"] == "x":
                fy = 0.5
            elif state["last"] == "y":
                fx = 0.5
            else:
                fx = fy = 0.5
        elif key == "c":
            fx = fy = 0.5
        state["pivot"] = (fx, fy)
        state["last"] = key if key in ("x", "y") else (
            state["last"] if key == "m" else None)
        self._reference()
        self._update_transform()

    @staticmethod
    def pivot_name(pivot):
        fx, fy = pivot
        if (fx, fy) == (0.5, 0.5):
            return "centre"
        across = {0.0: "left", 0.5: "", 1.0: "right"}[fx]
        down = {0.0: "top", 0.5: "middle", 1.0: "bottom"}[fy]
        return " ".join(w for w in (down, across) if w)

    def _transform_readout(self):
        state = self._scale
        if state["mode"] == "scale":
            what = "SCALE x{:.3g}".format(state["factor"])
        else:
            what = "ROTATE {:+.1f} deg".format(-math.degrees(state["turn"]))
        text = ("{} about the {} - X / Y edges, M middle, C centre; type a "
                "number, Enter, Esc").format(what,
                                             self.pivot_name(state["pivot"]))
        self.mode_changed.emit(text)
        self.hovered.emit(text)

    def _typed_number(self):
        text = self._scale["typed"]
        if not text or text in "-+.,":
            return None
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None

    def _update_transform(self, pos=None, mods=Qt.NoModifier):
        state = self._scale
        rect = self.plot_rect()
        pos = pos or self._cursor
        cx, cy = self._centre_of_pivots()
        typed = self._typed_number()
        if state["mode"] == "scale":
            if typed is not None:
                factor = typed
            elif pos is None:
                factor = state["factor"]
            else:
                factor = math.hypot(pos.x() - cx, pos.y() - cy) / state["start"]
                if mods & Qt.ShiftModifier:
                    factor = 1.0 + (factor - 1.0) * 0.1
                if mods & Qt.ControlModifier:
                    factor = round(factor * 10.0) / 10.0
            state["factor"] = max(0.05, min(20.0, factor))
        else:
            if typed is not None:
                turn = -math.radians(typed)
            elif pos is None:
                turn = state["turn"]
            else:
                turn = (math.atan2(pos.y() - cy, pos.x() - cx)
                        - state["angle0"])
                if mods & Qt.ShiftModifier:
                    turn *= 0.1
                if mods & Qt.ControlModifier:
                    step = math.radians(self.ROTATE_SNAP)
                    turn = round(turn / step) * step
            state["turn"] = turn
        for entry in state["entries"]:
            obj = entry["obj"]
            px, py = self._pivot_point(entry)
            ax, ay = entry["anchor"]
            if state["mode"] == "scale":
                factor = state["factor"]
                for name, value in zip(entry["fields"], entry["origin"]):
                    setattr(obj, name, max(0.1, value * factor))
                # The pivot stays EXACTLY put: the anchor goes back where it
                # was, the box is measured as it now is, and the anchor is
                # moved by however far the pivot then is from where it
                # belongs. Predicting the box instead (factor x the old one)
                # let everything but a bottom-left anchor wander, because a
                # box does not grow in proportion: font sizes step, and a
                # legend's padding does not scale (Christian, round 18).
                self.set_artist_point(obj, ax, ay, rect, clamp=False)
                live = dict(entry, anchor=(ax, ay),
                            box=self.artist_box(obj, rect))
                qx, qy = self._pivot_point(live)
                nx, ny = ax + (px - qx), ay + (py - qy)
            else:
                turn = state["turn"]
                degrees = entry["rotation"] - math.degrees(turn)
                obj.rotation = (degrees + 180.0) % 360.0 - 180.0
                vx, vy = ax - px, ay - py
                nx = px + vx * math.cos(turn) - vy * math.sin(turn)
                ny = py + vx * math.sin(turn) + vy * math.cos(turn)
            self.set_artist_point(obj, nx, ny, rect, clamp=False)
        self._transform_readout()
        self.invalidate()

    def _finish_transform(self, cancel=False):
        state, self._scale = self._scale, None
        if state is None:
            return
        idle = (state["factor"] == 1.0 if state["mode"] == "scale"
                else state["turn"] == 0.0)
        changes = []
        for entry in state["entries"]:
            obj = entry["obj"]
            names = entry["fields"] + ("x", "y")
            now = tuple(getattr(obj, n) for n in names)
            for name, value in zip(names, entry["stored"]):
                setattr(obj, name, value)
            if cancel or idle:
                continue
            changes.extend((obj, n, v) for n, v, old in
                           zip(names, now, entry["stored"]) if v != old)
        self.mode_changed.emit(self.MODE_TEXT.get(self._mode,
                                                   self.SELECT_TEXT))
        if changes:
            self.transform_done.emit(changes, "{} {} object(s)".format(
                state["mode"], len(state["entries"])))
        self.invalidate()

    # The old names, kept for what already calls them.
    def _update_scale(self, pos=None, mods=Qt.NoModifier):
        self._update_transform(pos, mods)

    def _finish_scale(self, cancel=False):
        self._finish_transform(cancel)

    #: The keys S and R keep for themselves while they are live, so the
    #: window's own (M is the x range, C measures) do not fire.
    TRANSFORM_KEYS = {Qt.Key_X: "x", Qt.Key_Y: "y", Qt.Key_M: "m",
                      Qt.Key_C: "c"}

    def _key_during_scale(self, ev):
        key, text = ev.key(), ev.text()
        state = self._scale
        if key == Qt.Key_Escape:
            self._finish_transform(cancel=True)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish_transform()
        elif key in self.TRANSFORM_KEYS:
            self.pivot_key(self.TRANSFORM_KEYS[key])
        elif key == Qt.Key_Backspace:
            state["typed"] = state["typed"][:-1]
            self._update_transform()
        elif text and (text.isdigit() or text in ".,"
                       or (text == "-" and state["mode"] == "rotate"
                           and not state["typed"])):
            state["typed"] += text
            self._update_transform()
        else:
            ev.ignore()
            return
        ev.accept()

    def _paint_scale(self, p):
        """The live S or R: each artist's box, dashed, the pivot on it, and
        a dashed line from the pivot to the cursor - Blender's cue."""
        state = self._scale
        if state is None:
            return
        rect = self.plot_rect()
        p.setRenderHint(QPainter.Antialiasing, True)
        for entry in state["entries"]:
            obj = entry["obj"]
            box = self.artist_box(obj, rect)
            ax, ay = self.artist_point(obj, rect)
            turn = QTransform()
            turn.translate(ax, ay)
            turn.rotate(-float(getattr(obj, "rotation", 0.0) or 0.0))
            turn.translate(-ax, -ay)
            p.setPen(QPen(_SELECT, 1.0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(turn.map(QPolygonF(box)))
            live = dict(entry, anchor=(ax, ay), box=box,
                        rotation=float(getattr(obj, "rotation", 0.0) or 0.0))
            px, py = self._pivot_point(live)
            p.setPen(QPen(_SELECT, 1.5))
            p.drawEllipse(QPointF(px, py), 4.0, 4.0)
            p.drawLine(QPointF(px - 7, py), QPointF(px + 7, py))
            p.drawLine(QPointF(px, py - 7), QPointF(px, py + 7))
        if self._cursor is not None:
            cx, cy = self._centre_of_pivots()
            p.setPen(QPen(_CURSOR, 1.0, Qt.DashLine))
            p.drawLine(QPointF(cx, cy), QPointF(self._cursor))
        p.setRenderHint(QPainter.Antialiasing, False)

    # ------------------------------------------------------------- measuring
    #: How the measuring gesture reads, step by step, in the status line.
    MEASURE_TEXT = (
        "MEASURE - click the first point, or type a temperature",
        "MEASURE - click the second point, or type a temperature",
        "MEASURE - Enter to choose the analysis, Esc to step back",
    )

    def start_measure(self, scan=None, cursors=None, editing=None,
                      span=None):
        """Begin placing cursors on one scan, TRIOS style.

        One scan, always: an analysis is about a single curve, and a gesture
        that could mean two of them is a gesture that means nothing. The
        cursors are kept in the FILE's units (degrees Celsius), so changing
        the axis to Kelvin mid-measurement moves nothing.

        `editing` is an existing analysis being adjusted: confirming replaces
        it instead of adding another.
        """
        doc = self.doc
        if doc is None:
            return False
        if doc.x_axis != model.AXIS_TEMPERATURE:
            # The analyses take TEMPERATURES. A cursor put down on a time
            # axis would be read as degrees, and the result would look like
            # an analysis and mean nothing.
            self.hovered.emit("Analyses are measured on a temperature axis")
            return False
        if scan is None:
            chosen = doc.selected_scans()
            if len(chosen) != 1:
                self.hovered.emit(
                    "Select one scan to measure on")
                return False
            scan = chosen[0]
        span = list(span) if span else None
        if span:
            # A span names the samples; the temperatures follow from them,
            # paired index for index.
            cursors = [self._celsius_of(scan, i) for i in span]
        self._measure = {"scan": scan, "cursors": list(cursors or []),
                         "typed": "", "editing": editing, "span": span}
        self.mode_changed.emit(self._measure_text())
        self._sync_pointer()
        self.update()
        return True

    def _trace_of(self, scan):
        for trace in self.traces:
            if trace.scan is scan:
                return trace
        return None

    def sample_at(self, trace, pos, rect=None):
        """The sample of a drawn curve nearest `pos`, as an index into the
        segment's OWN arrays, or None.

        Nearest in the plane, not in temperature: on a curve that doubles
        back, the temperature under the pointer names two or three points,
        and only the one the pointer is actually near is meant.
        """
        if trace is None or trace.x is None or not len(trace.x):
            return None
        rect = rect or self.plot_rect()
        px = self.x_to_px(trace.x, rect)
        py = self.y_to_px(trace.y, rect)
        index = int(np.argmin(np.hypot(px - pos.x(), py - pos.y())))
        return trace.first + index

    @staticmethod
    def _celsius_of(scan, index):
        """The file's temperature at one of its samples, in Celsius."""
        return float(scan.temperature()[int(index)])

    def _sample_point(self, trace, index, rect=None):
        """Where a sample (segment index) is drawn, clipped to the kept part."""
        rect = rect or self.plot_rect()
        local = int(_clamp(int(index) - trace.first, 0, len(trace.x) - 1))
        return QPointF(float(self.x_to_px(trace.x[local], rect)),
                       float(self.y_to_px(trace.y[local], rect)))

    def _celsius_at(self, px):
        """The file's Celsius under a pixel column, whatever the axis shows."""
        value = self.px_to_x(px)
        doc = self.doc
        if doc is not None and doc.x_axis == model.AXIS_TEMPERATURE:
            return units.to_celsius(value, getattr(doc, "x_unit",
                                                   units.TEMP_C))
        return value

    # ------------------------------------------------ the interval gesture
    def start_interval(self, scan, pos):
        """A double-click landed on a curve: it may become an interval.

        Nothing is marked yet. If the pointer moves, the press becomes a drag
        along the curve and `drag_interval` draws the stretch; if it does
        not, the release opens the scan's settings as any double-click does.
        """
        self._interval = {"scan": scan, "start": pos, "live": False}
        return True

    def drag_interval(self, pos):
        """Stretch the interval from where the double-click landed to `pos`."""
        state = self._interval
        if state is None:
            return False
        if not state["live"]:
            if math.hypot(pos.x() - state["start"].x(),
                          pos.y() - state["start"].y()) < self._slop():
                return True
            editing = None
            measuring = self._measure
            if measuring is not None and measuring["scan"] is state["scan"]:
                # Adjusting an analysis and dragging a new stretch of ITS
                # curve: the new stretch is that analysis's new interval.
                editing = measuring.get("editing")
            if not self.start_measure(state["scan"], editing=editing):
                self._interval = None
                return False
            trace = self._trace_of(state["scan"])
            start = self.sample_at(trace, state["start"])
            if start is not None:
                # BY SAMPLE along the curve, not by temperature: where the
                # press landed and where the pointer is now, each the nearest
                # point of the drawn curve (Christian: a DSC curve is a
                # parametric curve, not a function of temperature).
                self._measure["span"] = [start, start]
                first = self._celsius_of(state["scan"], start)
            else:
                first = self._celsius_at(state["start"].x())
            self._measure["cursors"] = [first, first]
            self._measure["gesture"] = True
            state["live"] = True
        span = self._measure.get("span")
        if span is not None:
            index = self.sample_at(self._trace_of(state["scan"]), pos)
            span[1] = index
            self._measure["cursors"][1] = self._celsius_of(state["scan"],
                                                           index)
        else:
            self._measure["cursors"][1] = self._celsius_at(pos.x())
        self.mode_changed.emit(self.INTERVAL_TEXT)
        self.update()
        return True

    def finish_interval(self):
        """The button came up: ask for the analysis, or open the settings.

        A drag hands the two temperatures to the window at once - that IS the
        confirmation, there is no Enter to press. A double-click that never
        moved is an ordinary double-click, and opens the scan.
        """
        state, self._interval = self._interval, None
        if state is None:
            return False
        if not state["live"]:
            self.activated.emit(state["scan"])
            return True
        measuring = self._measure
        rect = self.plot_rect()
        span = measuring.get("span")
        trace = self._trace_of(measuring["scan"])
        if span is not None and trace is not None:
            a, b = self._sample_point(trace, span[0], rect), \
                self._sample_point(trace, span[1], rect)
            if (abs(span[1] - span[0]) < 2
                    or math.hypot(a.x() - b.x(), a.y() - b.y()) < self._slop()):
                self.end_measure()
                return False
            # In ORDER ALONG THE CURVE, cursors paired with their samples.
            span.sort()
            measuring["cursors"] = [self._celsius_of(measuring["scan"], i)
                                    for i in span]
            self.measure_confirm()
            return True
        low, high = sorted(measuring["cursors"])
        wide = abs(float(self.x_to_px(self.to_axis(high), rect))
                   - float(self.x_to_px(self.to_axis(low), rect)))
        if wide < self._slop():
            self.end_measure()
            return False
        measuring["cursors"] = [low, high]
        self.measure_confirm()
        return True

    def cancel_interval(self):
        state, self._interval = self._interval, None
        if state is not None and state["live"]:
            self.end_measure()
        return state is not None

    def interval(self):
        """The double-click-drag in progress, or None. For tests."""
        return self._interval

    def measuring(self):
        """The measurement in progress, or None. For tests and the window."""
        return self._measure

    def _measure_text(self):
        state = self._measure
        if state is None:
            return self.MODE_TEXT.get(self._mode, self.SELECT_TEXT)
        step = min(len(state["cursors"]), 2)
        text = self.MEASURE_TEXT[step]
        if state["typed"]:
            text += "   [{}]".format(state["typed"])
        return text

    def measure_place(self, pos=None, value=None):
        """Put the next cursor down, from a click or from a typed number.

        A typed number is in the unit the AXIS is showing and is converted
        back to the file's Celsius, so "150" means what it says on screen
        whichever scale is selected.
        """
        state = self._measure
        if state is None:
            return False
        if value is None:
            if pos is None:
                return False
            celsius = self._celsius_at(pos.x())
        else:
            celsius = (units.to_celsius(value, getattr(self.doc, "x_unit",
                                                       units.TEMP_C))
                       if self.doc is not None
                       and self.doc.x_axis == model.AXIS_TEMPERATURE
                       else value)
        if len(state["cursors"]) >= 2:
            state["cursors"][-1] = celsius
        else:
            state["cursors"].append(celsius)
        state["typed"] = ""
        self.mode_changed.emit(self._measure_text())
        self.update()
        return True

    def cursor_at(self, pos):
        """Which measure cursor is under `pos`, or None.

        The handle on the curve, or anywhere along its dashed line: picking
        a cursor up should not require hitting a nine-pixel circle.
        """
        if self._measure is None:
            return None
        point = pos.toPoint() if hasattr(pos, "toPoint") else QPoint(pos)
        for index, box in self._cursor_handles:
            if box.contains(point):
                return index
        rect = self.plot_rect()
        best, best_gap = None, 1e30
        for index, celsius in enumerate(self._measure["cursors"]):
            x = float(self.x_to_px(self.to_axis(celsius), rect))
            gap = abs(x - point.x())
            if gap < best_gap:
                best, best_gap = index, gap
        return best if best_gap <= 6 else None

    def start_cursor_drag(self, index, pos):
        self._cursor_drag = {"index": int(index), "start": pos}
        self.mode_changed.emit(self._measure_text())
        return True

    def drag_cursor(self, pos):
        """Move the cursor being held to where the pointer is."""
        state = self._cursor_drag
        if state is None or self._measure is None:
            return False
        span = self._measure.get("span")
        if span is not None:
            # A gizmo of an analysis made along the curve follows the
            # curve: the nearest sample to the pointer, whichever branch.
            sample = self.sample_at(self._trace_of(self._measure["scan"]),
                                    pos)
            if sample is not None and 0 <= state["index"] < len(span):
                span[state["index"]] = sample
                self._measure["cursors"][state["index"]] = \
                    self._celsius_of(self._measure["scan"], sample)
                self.mode_changed.emit(self._measure_text())
                self.update()
            return True
        celsius = self._celsius_at(pos.x())
        index = state["index"]
        if 0 <= index < len(self._measure["cursors"]):
            self._measure["cursors"][index] = celsius
            self.mode_changed.emit(self._measure_text())
            self.update()
        return True

    def end_cursor_drag(self):
        """Let go of a gizmo. While an analysis made here is being ADJUSTED,
        letting go is the confirmation: it is recomputed at once, so the
        number follows the hand instead of waiting for an Enter."""
        held, self._cursor_drag = self._cursor_drag, None
        self.update()
        state = self._measure
        if (held is not None and state is not None
                and state.get("editing") is not None
                and len(state["cursors"]) >= 2):
            self.measure_confirm()

    def editing(self):
        """The analysis whose gizmos are up, or None."""
        return (self._measure or {}).get("editing")

    def gizmo_rect(self):
        """Where the measure cursors are, in GLOBAL coordinates, or None.

        The span between them over the plot's full height, widened by the
        handles and by the temperature readout drawn to the right of each
        (90 px): what a settings dialog must not cover while it is open
        beside them.
        """
        state = self._measure
        if not state or not state["cursors"]:
            return None
        rect = self.plot_rect()
        xs = [float(self.x_to_px(self.to_axis(c), rect))
              for c in state["cursors"]]
        left = max(rect.left(), min(xs) - 24)
        right = min(self.canvas_size()[0], max(xs) + 100)
        corner = self.to_widget(QPointF(left, rect.top()))
        far = self.to_widget(QPointF(right, rect.bottom()))
        top_left = self.mapToGlobal(corner.toPoint())
        return QRect(top_left, QSize(max(1, int(far.x() - corner.x())),
                                     max(1, int(far.y() - corner.y()))))

    def measure_back(self):
        """One Esc: drop the typed number, then a cursor, then the gesture.

        Christian asked for exactly this - every Esc goes back one step in
        the chronology rather than throwing the whole thing away.
        """
        state = self._measure
        if state is None:
            return False
        if state["typed"]:
            state["typed"] = ""
        elif state.get("editing") is not None:
            # The gizmos of an analysis being adjusted belong to its settings
            # dialog: closing THAT ends them. Esc here must not strip one.
            return True
        elif state["cursors"]:
            state["cursors"].pop()
        else:
            self._measure = None
            self.mode_changed.emit(self.SELECT_TEXT)
            self.update()
            return True
        self.mode_changed.emit(self._measure_text())
        self.update()
        return True

    def measure_key(self, ev):
        """Keys while cursors are being placed. True when one was used."""
        state = self._measure
        if state is None:
            return False
        key, text = ev.key(), ev.text()
        if key == Qt.Key_Escape:
            return self.measure_back()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if state["typed"]:
                try:
                    self.measure_place(value=float(
                        state["typed"].replace(",", ".")))
                except ValueError:
                    state["typed"] = ""
                return True
            if len(state["cursors"]) >= 2:
                self.measure_confirm()
            return True
        if key == Qt.Key_Backspace:
            state["typed"] = state["typed"][:-1]
            self.mode_changed.emit(self._measure_text())
            return True
        if text and (text.isdigit() or text in "-+.,"):
            state["typed"] += text
            self.mode_changed.emit(self._measure_text())
            self.update()
            return True
        return False

    def measure_confirm(self):
        """Hand the two cursors to the window, which asks what to compute."""
        state = self._measure
        if state is None or len(state["cursors"]) < 2:
            return False
        span = state.get("span")
        self.measure_ready.emit(state["scan"], float(state["cursors"][0]),
                                float(state["cursors"][1]), state["editing"],
                                tuple(span) if span else None)
        return True

    def set_measure_cursors(self, cursors, span=None):
        """Put the gizmos at `cursors` (degC) - the interval was typed."""
        if self._measure is None:
            return False
        self._measure["cursors"] = [float(c) for c in cursors]
        self._measure["span"] = span
        self.update()
        return True

    def end_measure(self):
        self._measure = None
        self.mode_changed.emit(self.MODE_TEXT.get(self._mode,
                                                  self.SELECT_TEXT))
        self._sync_pointer()
        self.update()

    def _paint_measure(self, p):
        """The crosshairs, the span between them, and their temperatures."""
        state = self._measure
        if state is None:
            return
        rect = self.plot_rect()
        trace = None
        for candidate in self.traces:
            if candidate.scan is state["scan"]:
                trace = candidate
                break
        colour = QColor(_SELECT)
        span = state.get("span")
        positions, heights = [], []
        for k, celsius in enumerate(state["cursors"]):
            if span is not None and trace is not None and k < len(span) \
                    and trace.x is not None and len(trace.x):
                # On the SAMPLE, not wherever the temperature is first met.
                point = self._sample_point(trace, span[k], rect)
                positions.append(point.x())
                heights.append(point.y())
                continue
            value = self.to_axis(celsius)
            positions.append(float(self.x_to_px(value, rect)))
            heights.append(None)
        if len(positions) == 2:
            span = QRectF(min(positions), rect.top(),
                          abs(positions[1] - positions[0]), rect.height())
            fill = QColor(colour)
            fill.setAlpha(28)
            p.fillRect(span, fill)
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 0.5))
        p.setFont(font)
        self._cursor_handles = []
        for index, x in enumerate(positions):
            held = (self._cursor_drag is not None
                    and self._cursor_drag.get("index") == index)
            p.setPen(QPen(colour, 1.6 if held else 1.2, Qt.DashLine))
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            y = heights[index]
            if y is None and trace is not None:
                y = self._curve_y_at(trace, self.px_to_x(x, rect), rect)
            if y is not None:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(QPen(colour, 1.8 if held else 1.4))
                p.drawEllipse(QPointF(x, y), 6.0, 6.0)
                p.drawLine(QPointF(x - 10, y), QPointF(x + 10, y))
                p.drawLine(QPointF(x, y - 10), QPointF(x, y + 10))
                p.setRenderHint(QPainter.Antialiasing, False)
                # The grab handle, so a cursor can be picked up and moved
                # rather than only replaced by clicking again.
                self._cursor_handles.append(
                    (index, QRect(int(x - 9), int(y - 9), 18, 18)))
            label = "{:.2f}".format(self.to_axis(state["cursors"][index]))
            p.setPen(QPen(colour, 1.0))
            p.drawText(QRectF(x + 5, rect.top() + 4 + 14 * index, 90, 14),
                       int(Qt.AlignLeft | Qt.AlignVCenter), label)
        if state["typed"]:
            p.setPen(QPen(colour, 1.0))
            p.drawText(QRectF(rect.left() + 8, rect.top() + 4, 200, 16),
                       int(Qt.AlignLeft | Qt.AlignVCenter),
                       "= {}".format(state["typed"]))

    # ----------------------------------------------------------------- input
    def keyPressEvent(self, ev):
        key = ev.key()
        if self._press is not None and key == Qt.Key_Escape:
            self._press = None              # the button is down; forget it
            ev.accept()
            return
        if self._interval is not None:
            # Mid-drag, the only key that means anything is Esc: drop the
            # interval and leave the curve exactly as it was.
            if key == Qt.Key_Escape:
                self.cancel_interval()
                self.mode_changed.emit(self.SELECT_TEXT)
            ev.accept()
            return
        if self._measure is not None and self.measure_key(ev):
            ev.accept()
            return
        if self._move is not None:
            self._key_during_move(ev)
            return
        if self._scale is not None:
            self._key_during_scale(ev)
            return
        if key == Qt.Key_Z:
            self.cycle_mode(self.ZOOM_CYCLE)
        elif key == Qt.Key_P:
            self.cycle_mode(self.PAN_CYCLE)
        elif key == Qt.Key_Escape:
            self._box = None
            self.set_mode(None)
        elif key in (Qt.Key_F, Qt.Key_Home):
            self.reset_view()
        elif key == Qt.Key_G:
            if not self.start_grab():
                self.hovered.emit("Nothing selected to move")
        elif ev.text() and (ev.text().isdigit() or ev.text() in "-+.,") \
                and self._scale is None:
            # TYPING A NUMBER IS A MOVE. Selecting a scan already makes it
            # the thing being worked on, so requiring G first was a second
            # gesture for no reason - Christian's report. G still exists for
            # anyone with it in their fingers.
            if self.start_grab():
                self._move["typed"] = ev.text()
                self._update_move(self._cursor or self._move["start"])
                self.hovered.emit(self._move_readout())
            else:
                self.hovered.emit("Select a scan first, then type a number")
        else:
            QWidget.keyPressEvent(self, ev)
            return
        ev.accept()

    def _key_during_move(self, ev):
        key, text = ev.key(), ev.text()
        if key in (Qt.Key_Escape,):
            self._finish_move(cancel=True)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish_move()
        elif key in (Qt.Key_X, Qt.Key_Y):
            # Blender's axis locks. X is only offered for artists: a scan has
            # no x freedom to lock, so saying so beats a key that does
            # nothing.
            wanted = "x" if key == Qt.Key_X else "y"
            if wanted == "x" and not any(
                    self.is_artist(o) or isinstance(o, model.OffsetMarker)
                    for o in self._move["objs"]):
                self.hovered.emit("A scan does not move along x")
            else:
                self._move["axis"] = (None if self._move.get("axis") == wanted
                                      else wanted)
                self._update_move(self._cursor or self._move["start"])
        elif key == Qt.Key_Backspace:
            self._move["typed"] = self._move["typed"][:-1]
            self._update_move(self._cursor or self._move["start"])
        elif text and (text.isdigit() or text in "-+.,"):
            self._move["typed"] += text
            self._update_move(self._cursor or self._move["start"])
        else:
            ev.ignore()
            return
        ev.accept()

    def mousePressEvent(self, ev):
        pos = self.to_figure(ev.position())
        if self._scale is not None:
            self._finish_transform(cancel=ev.button() == Qt.RightButton)
            ev.accept()
            return
        if self._move is not None:
            # A click commits a keyboard grab, and the right button cancels
            # it - Blender's rule, and the one anybody who uses G expects.
            self._finish_move(cancel=ev.button() == Qt.RightButton)
            ev.accept()
            return
        if ev.button() == Qt.RightButton:
            obj = self.object_at(pos)
            if obj is not None and not obj.selected:
                self.doc.select_only([obj])
                self.selection_changed.emit()
            self.context_menu.emit(obj, ev.globalPosition().toPoint())
            ev.accept()
            return
        if ev.button() != Qt.LeftButton:
            QWidget.mousePressEvent(self, ev)
            return
        if self._measure is not None:
            held = self.cursor_at(pos)
            if held is not None:
                self.start_cursor_drag(held, pos)
                ev.accept()
                return
            if self._measure.get("editing") is None:
                # Placing cursors by click is the TYPED route (`C`). While an
                # analysis is being adjusted, its gizmos are dragged, and a
                # press anywhere else is an ordinary press.
                self.measure_place(pos)
                ev.accept()
                return
        if self._mode:
            rect = self.plot_rect()
            self._drag = {"px": pos.x(), "py": pos.y(),
                          "x": self.px_to_x(pos.x(), rect),
                          "y": self.px_to_y(pos.y(), rect),
                          "view_x": self.view_x(), "view_y": self.view_y(),
                          "mode": self._mode}
            self._view_begin("zoom" if self._mode.startswith("zoom")
                             else "pan")
            ev.accept()
            return
        # No mode armed. Released where it was pressed, a press is a CLICK
        # and selects what is under it (or clears). Dragged, what it does
        # depends on what it started NEAR - within the pick distance:
        #
        # * a curve: mark an interval along it, and ask for the analysis on
        #   release. Never a move: a scan moves with G and nothing else.
        # * anything drawn on the figure (the arrow, the legend, a label, an
        #   analysis label, an axis caption): move it.
        # * nothing: a box select. With Shift it is ALWAYS a box, adding to
        #   the selection, which is how a box starts on top of a curve.
        #
        # Christian, round 9: "double-click-drag" never reached the handler
        # for it. On a trackpad, tap-then-drag arrives as ONE press and a
        # drag, not as a double-click, so it was a box every time. Deciding
        # by proximity makes the gesture work however the hardware sends it;
        # a real double-click-drag still does the same thing.
        add = bool(ev.modifiers() & Qt.ShiftModifier)
        target = None if add else self.drag_target(pos)
        if target is not None:
            self._press = {"kind": target[0], "obj": target[1],
                           "start": pos}
        else:
            self._box = {"start": pos, "now": pos, "add": add,
                         "moved": False}
        ev.accept()

    def _press_became_drag(self, pos, mods=Qt.NoModifier):
        """A press near an object has moved far enough: act on the object."""
        press, self._press = self._press, None
        obj = press["obj"]
        if self.doc is not None and not obj.selected:
            self.doc.select_only([obj])
            self.selection_changed.emit()
        if press["kind"] == "interval":
            self.start_interval(obj, press["start"])
            self.drag_interval(pos)
            return
        objs = self.drag_group(obj)
        self._move = {"objs": objs, "start": press["start"],
                      "origin": [self._value_of(o) for o in objs],
                      "stored": [self._stored_of(o) for o in objs],
                      "typed": "",
                      "axis": None, "keyboard": False, "moved": True}
        self._update_move(pos, mods)
        self.hovered.emit(self._move_readout())

    def drag_group(self, obj):
        """What a drag on `obj` moves: `obj`, and when it is part of the
        selection every other selected thing that moves by hand - several
        analysis labels stretch their arrows together, several offset
        markers travel together (Christian, round 14). Never a scan (a scan
        moves with G) and never an axis caption, which is the frame."""
        doc = self.doc
        if doc is None or not obj.selected:
            return [obj]
        return [obj] + [o for o in doc.selected()
                        if o is not obj and self._fields_of(o)
                        and not isinstance(o, (model.Scan, model.Axis))]

    def mouseMoveEvent(self, ev):
        pos = self.to_figure(ev.position())
        self._cursor = pos
        self._sync_pointer()
        if self._scale is not None:
            self._update_transform(pos, ev.modifiers())
            self.update()
            return
        if self._cursor_drag is not None:
            self.drag_cursor(pos)
            return
        if self._interval is not None:
            self.drag_interval(pos)
            return
        if self._press is not None:
            start = self._press["start"]
            if (abs(pos.x() - start.x()) >= self._slop()
                    or abs(pos.y() - start.y()) >= self._slop()):
                self._press_became_drag(pos, ev.modifiers())
            return
        if self._box is not None:
            box = self._box
            box["now"] = pos
            if (not box["moved"]
                    and abs(pos.x() - box["start"].x()) < self._slop()
                    and abs(pos.y() - box["start"].y()) < self._slop()):
                return
            box["moved"] = True
            self.hovered.emit("SELECT box - release to take everything inside")
            self.update()
            return
        state = self._move
        if state is not None:
            if not state["keyboard"]:
                if (not state["moved"]
                        and abs(pos.y() - state["start"].y()) < self._slop()
                        and abs(pos.x() - state["start"].x()) < self._slop()):
                    return
                state["moved"] = True
            self._update_move(pos, ev.modifiers())
            self.hovered.emit(self._move_readout())
            return
        drag = self._drag
        if drag is not None and drag["mode"].startswith("pan"):
            rect = self.plot_rect()
            # Measured in PIXELS through the PRESS-time view, never the live
            # one: reading the live limits back feeds the motion into itself
            # and the pan accelerates away.
            x0, x1 = drag["view_x"]
            y0, y1 = drag["view_y"]
            dx = ((drag["px"] - pos.x()) / max(1.0, rect.width()) * (x1 - x0))
            dy = ((pos.y() - drag["py"]) / max(1.0, rect.height()) * (y1 - y0))
            if drag["mode"] in ("pan_h", "pan_free"):
                self._view_x = (x0 + dx, x1 + dx)
            if drag["mode"] in ("pan_v", "pan_free"):
                self._view_y = (y0 + dy, y1 + dy)
            self.update()                  # blit the cache, rebuild on release
            self.view_changed.emit()
            return
        self.hovered.emit(self.readout(pos))
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._cursor_drag is not None:
            self.end_cursor_drag()
            ev.accept()
            return
        if self._interval is not None:
            self.finish_interval()
            ev.accept()
            return
        if self._press is not None:
            # Near an object and never moved: a click on it. A click on one
            # of several selected things narrows the selection to it - but
            # if it turns out to be the first half of a double-click, the
            # double-click puts the selection back and acts on all of it.
            press, self._press = self._press, None
            before = (list(self.doc.selected()) if self.doc is not None
                      else [])
            chosen = self.select_at(press["start"])
            self._click_restore = ((chosen, before)
                                   if chosen is not None and chosen in before
                                   and len(before) > 1 else None)
            ev.accept()
            return
        if self._box is not None:
            box, self._box = self._box, None
            if box["moved"]:
                self.select_in_box(box["start"], box["now"], add=box["add"])
            else:
                self.select_at(box["start"], add=box["add"])
            ev.accept()
            return
        if self._move is not None and not self._move["keyboard"]:
            # Only a double-click-drag gets here: a single press no longer
            # starts a move. Still, it is a double-click.
            waiting = self._move.get("activate")
            if self._move["moved"]:
                self._finish_move()
            else:
                self._move = None
                if waiting is not None:
                    self.open_object(waiting)
            ev.accept()
            return
        drag, self._drag = self._drag, None
        if drag is None or ev.button() != Qt.LeftButton:
            QWidget.mouseReleaseEvent(self, ev)
            return
        mode = drag["mode"]
        if mode.startswith("pan"):
            self.invalidate()
            self.commit_view()
            return
        rect = self.plot_rect()
        end = self.to_figure(ev.position())
        x1 = self.px_to_x(_clamp(end.x(), rect.left(), rect.right()),
                          rect, drag["view_x"])
        y1 = self.px_to_y(_clamp(end.y(), rect.top(), rect.bottom()),
                          rect, drag["view_y"])
        if mode in ("zoom_h", "zoom_box") and abs(x1 - drag["x"]) > 1e-12:
            self.set_view_x(min(drag["x"], x1), max(drag["x"], x1))
        if mode in ("zoom_v", "zoom_box") and abs(y1 - drag["y"]) > 1e-12:
            self.set_view_y(min(drag["y"], y1), max(drag["y"], y1))
        self.commit_view()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        """Double-click opens the settings - unless it turns into a DRAG.

        The second press is treated as a press that remembers what to open if
        nothing moves, and the release decides: still, and it was a
        double-click; moved, and it was a double-click-DRAG, which acts on
        whatever it landed on:

        * on a CURVE it marks an interval, and letting go asks which analysis
          to run on it. Christian: marking an interval is the trivial and
          obvious gesture, and the one everything else was missing. It never
          moves the scan - a scan moves with G, and nothing else.
        * on an ARTIST (the arrow, the legend, a label), an analysis label or
          an axis caption it moves that thing, as it always did.
        """
        pos = self.to_figure(ev.position())
        # Whatever an extra press of the pair started, the double-click owns
        # the gesture now.
        self._box = None
        self._press = None
        if self._measure is not None:
            held = self.cursor_at(pos)
            if held is not None:
                self.start_cursor_drag(held, pos)
                ev.accept()
                return
        obj = self.object_at(pos)
        if obj is None:
            QWidget.mouseDoubleClickEvent(self, ev)
            return
        restore, self._click_restore = self._click_restore, None
        if restore is not None and restore[0] is obj and self.doc is not None:
            for other in restore[1]:
                other.selected = True
            self.selection_changed.emit()
        if isinstance(obj, model.Scan):
            if self.doc is not None and not obj.selected:
                self.doc.select_only([obj])
                self.selection_changed.emit()
            trace = self._trace_at(pos)
            if trace is not None and trace.scan is obj:
                self.start_interval(obj, pos)
            else:
                # Its NAME, not its curve: there is no stretch of curve under
                # the pointer to mark, so this is only a double-click.
                self.activated.emit(obj)
            ev.accept()
            return
        if (self.doc is not None and not obj.selected
                and not self._frame_part(obj)):
            self.doc.select_only([obj])
            self.selection_changed.emit()
        if self._fields_of(obj) and not self._frame_part(obj):
            objs = self.drag_group(obj)
            self._move = {"objs": objs, "start": pos,
                          "origin": [self._value_of(o) for o in objs],
                          "stored": [self._stored_of(o) for o in objs],
                          "typed": "", "axis": None, "keyboard": False,
                          "moved": False, "activate": obj}
        else:
            self.open_object(obj)
        ev.accept()

    def open_object(self, obj):
        """What a double-click that did not move does: open the thing.

        An analysis made HERE also gets its cursors back, so its interval can
        be adjusted and the analysis recomputed. That used to happen on the
        press, which made a panel analysis's label the one label that could
        not be double-click-dragged - and every new analysis is a panel one.
        """
        several = (self.doc is not None and obj.selected
                   and sum(isinstance(o, model.Analysis)
                           for o in self.doc.selected()) > 1)
        if (isinstance(obj, model.Analysis) and obj.source == "panel"
                and self.doc is not None and not several):
            cursors = obj.cursors()
            if len(cursors) == 2:
                self.doc.select_only([obj.scan])
                self.selection_changed.emit()
                self.start_measure(obj.scan, cursors, editing=obj,
                                   span=obj.span)
        # ...and its settings, because opening an analysis should show the
        # analysis. The cursors adjust the interval; the dialog the rest.
        self.activated.emit(obj)

    def enterEvent(self, ev):
        self.setFocus(Qt.MouseFocusReason)
        QWidget.enterEvent(self, ev)

    def leaveEvent(self, ev):
        self._cursor = None
        self.setCursor(Qt.ArrowCursor)
        self.hovered.emit("")
        self.update()
        QWidget.leaveEvent(self, ev)

    def resizeEvent(self, ev):
        QWidget.resizeEvent(self, ev)
        self.invalidate()

    # -------------------------------------------------------------- readouts
    def readout(self, pos):
        """What the status line says: where the cursor is, on which scan."""
        doc = self.doc
        if doc is None:
            return ""
        x = self.px_to_x(pos.x())
        y = self.px_to_y(pos.y())
        x_name = "T" if doc.x_axis == model.AXIS_TEMPERATURE else "t"
        x_unit = "°C" if doc.x_axis == model.AXIS_TEMPERATURE else "min"
        text = "{} = {:.3f} {}   y = {:.5g} {}".format(
            x_name, x, x_unit, y, doc.y_unit)
        trace = self._trace_at(pos)
        if trace is not None:
            text += "   |   {}".format(trace.name)
            if trace.missing:
                text += "   NO {}".format(trace.missing.upper())
            elif trace.scan.offset:
                text += "   offset {:+.5g} {}".format(trace.scan.offset,
                                                      doc.y_unit)
        return text

    def _move_readout(self):
        state = self._move
        if state is None:
            return ""
        unit = self.doc.y_unit if self.doc else ""
        if state["typed"]:
            return "GRAB {} {}   (Enter to confirm, Esc to cancel)".format(
                state["typed"], unit)
        first = state["objs"][0]
        lock = ("  [{} locked]".format(state["axis"].upper())
                if state.get("axis") else "")
        if self.is_artist(first):
            return "MOVE {} to x {:.2f}, y {:.2f} of the plot{}".format(
                first.kind, first.x, first.y, lock)
        if isinstance(first, model.Analysis):
            return "MOVE the label {:+.0f} px (vertical only){}".format(
                first.label_dy - state["origin"][0][0],
                "  - {} together".format(len(state["objs"]))
                if len(state["objs"]) > 1 else "")
        if isinstance(first, model.OffsetMarker):
            return "MOVE {} offset marker(s){}".format(
                sum(isinstance(o, model.OffsetMarker)
                    for o in state["objs"]), lock)
        if isinstance(first, model.Axis):
            return "MOVE the {} caption (it stays in the margin)".format(
                first.which)
        return "MOVE {:+.5g} {}   (type a number, Enter, or Esc){}".format(
            first.offset - state["origin"][0][0], unit, lock)

    # -------------------------------------------------------------- blinking
    def _sync_blink(self):
        need = any(t.missing for t in self.traces)
        if need and not self._blink_timer.isActive():
            self._blink_timer.start()
        elif not need and self._blink_timer.isActive():
            self._blink_timer.stop()
            self._blink = 0

    def _tick_blink(self):
        self._blink = (self._blink + 1) % BLINK_PERIOD
        if self._blink in BLINK_ON or (self._blink - 1) % BLINK_PERIOD in BLINK_ON:
            self.update()

    def blink_lit(self):
        """Whether the alarm is showing this instant.

        A double flash with a long pause, rather than a steady strobe: it has
        to be noticeable at the edge of vision and must not make the window
        unpleasant to work in while three scans wait for their molar mass.
        """
        return (self._move is None and self._drag is None
                and self._blink in BLINK_ON)

    # -------------------------------------------------------------- painting
    def _key(self):
        doc = self.doc
        # The selection of EVERY object: a selected artist, analysis label or
        # axis caption is drawn orange into the cache, and a click that only
        # changes selection just asks for a repaint. With artists missing
        # here, clicking off a label left it orange until something else
        # rebuilt the plot (Christian, round 10).
        selection = (tuple(obj.selected for obj in doc.objects())
                     if doc is not None else ())
        return (selection, self.canvas_size(), self.page(),
                self.width(), self.height(), self.devicePixelRatioF(),
                self.view_x(), self.view_y(),
                doc.x_axis if doc else "", doc.y_unit if doc else "",
                doc.exo if doc else "",
                ((doc.offset_markers,
                  style.figure_value(doc, "offset_marker_size"),
                  tuple((s.marker.at, s.marker.dy, s.marker.size,
                         s.marker.colour, s.marker.visible,
                         s.marker.number_format)
                        for s in doc.scans))
                 if doc else ()),
                (tuple(style.figure_value(doc, key) for key in (
                    "font_family", "temperature_format", "value_format",
                    "offset_format"))
                 + tuple(a.number_format for a in doc.axes.values())
                 if doc else ()),
                (doc.arrow.x, doc.arrow.y, doc.arrow.word, doc.arrow.direction,
                 doc.arrow.visible, doc.arrow.head_length,
                 doc.arrow.head_width, doc.arrow.tail_width,
                 doc.arrow.tail_length, style.value(doc, doc.arrow, "size"))
                if doc else (),
                tuple((id(t.scan), t.scan.offset,
                       t.colour.rgb(), t.scan.selected, t.missing,
                       tuple((id(a), a.visible, a.selected, a.colour,
                              a.label, a.attribution, a.number_format)
                             for a in t.scan.analysis_objects),
                       len(t.x) if t.x is not None else 0)
                      for t in self.traces))

    def paintEvent(self, _ev):
        painter = QPainter(self)
        drag = self._drag
        if (drag is not None and drag["mode"].startswith("pan")
                and self._cache is not None and self._cursor is not None):
            k = self.page()[2]
            painter.fillRect(self.rect(), self._surround())
            painter.drawPixmap(
                int((self._cursor.x() - drag["px"]) * k)
                if drag["mode"] in ("pan_h", "pan_free") else 0,
                int((self._cursor.y() - drag["py"]) * k)
                if drag["mode"] in ("pan_v", "pan_free") else 0,
                self._cache)
            return
        key = self._key()
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        painter.drawPixmap(0, 0, self._cache)
        # Only what follows the cursor is painted per event, so a mouse move
        # is a blit and a few lines rather than a rebuild of the curves.
        painter.save()
        dx, dy, k = self.page()
        painter.translate(dx, dy)
        painter.scale(k, k)
        painter.setClipRect(self.plot_rect())
        self._paint_names(painter)
        self._paint_cursor(painter)
        self._paint_band(painter)
        self._paint_select_box(painter)
        self._paint_scale(painter)
        self._paint_offsets(painter)
        self._paint_alarms(painter)
        self._paint_hidden(painter)
        self._paint_measure(painter)
        painter.restore()
        self._paint_flash(painter)

    # ------------------------------------------------------------- the flash
    #: How long "Saved ..." stays up, in seconds; it holds for the first third
    #: and fades for the rest. MoloM's numbers.
    FLASH_SECONDS = 2.2

    def flash(self, text, seconds=None):
        """A message that fades out over the top of the plot.

        MoloM's: the status bar already says what happened, and saving is
        exactly the moment nobody is looking at the bottom of the window.
        Painted per event and never into the cache, so an export cannot
        carry it.
        """
        self._flash = (str(text), time.monotonic(),
                       float(seconds or self.FLASH_SECONDS))
        self.update()
        QTimer.singleShot(40, self._flash_tick)

    def flashing(self):
        """The text on screen right now, or None. For tests."""
        return self._flash[0] if self._flash else None

    def _flash_tick(self):
        if not self._flash:
            return
        _text, started, seconds = self._flash
        if time.monotonic() - started >= seconds:
            self._flash = None
            self.update()
            return
        self.update()
        QTimer.singleShot(40, self._flash_tick)

    def _paint_flash(self, p):
        if not self._flash:
            return
        text, started, seconds = self._flash
        left = seconds - (time.monotonic() - started)
        if left <= 0:
            return
        # Hold at full opacity for the first third, then fade - a message
        # that starts fading at once is one you read half of.
        alpha = int(235 * min(1.0, left / (seconds * 0.66)))
        p.save()
        font = QFont(self.font())
        font.setPointSizeF(max(11.0, font.pointSizeF() * 1.25))
        font.setBold(True)
        p.setFont(font)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 26
        height = metrics.height() + 12
        # In PANE pixels, over the middle of the axes box wherever the page
        # sits and however it is scaled.
        rect = self.plot_rect()
        centre = self.to_widget(QPointF(rect.center().x(), rect.top()))
        x = centre.x() - width // 2
        y = centre.y() + 18
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(38, 74, 48, int(alpha * 0.85)))
        p.drawRoundedRect(QRectF(x, y, width, height), 5, 5)
        p.setPen(QColor(170, 235, 180, alpha))
        p.drawText(QPointF(x + 13, y + metrics.ascent() + 6), text)
        p.restore()

    def hidden_shown(self):
        """The traces whose truncated ends are on screen right now: the one
        under the pointer and the selected ones."""
        hovered = (self._trace_at(self._cursor)
                   if self._cursor is not None and self._move is None
                   else None)
        return [t for t in self.traces
                if t.hidden and (t is hovered or t.scan.selected)]

    def _paint_hidden(self, p):
        """A scan's truncated ends, DASHED, while it is hovered or selected.

        So what was cut is never invisible to the person working on it, and
        never in the figure: painted per event, like the name readout, so no
        export can carry it.
        """
        shown = self.hidden_shown()
        if not shown:
            return
        rect = self.plot_rect()
        limit = max(50, 2 * rect.width())
        p.setRenderHint(QPainter.Antialiasing, True)
        for trace in shown:
            colour = trace_colour(trace)
            colour.setAlpha(170)
            pen = QPen(colour, self.style_of(trace.scan, "line_width")
                       * CURVE_WIDTH, Qt.DashLine)
            p.setPen(pen)
            for x, y in trace.hidden:
                stride = max(1, int(len(x) // limit))
                p.drawPolyline(_polyline(self.x_to_px(x[::stride], rect),
                                         self.y_to_px(y[::stride], rect)))
        p.setRenderHint(QPainter.Antialiasing, False)

    def _surround(self):
        return (_BG if self.layout_mode() == figure_module.MODE_WINDOW
                else _SURROUND)

    def _render(self):
        """The figure, on its page, into the cache.

        A figure of fixed size or aspect is drawn in its OWN drawing units
        and scaled onto the pane (`page`), so what is on screen is the export
        at a zoom, not a re-layout of it.
        """
        ratio = float(self.devicePixelRatioF() or 1.0)
        pixmap = QPixmap(max(1, int(round(self.width() * ratio))),
                         max(1, int(round(self.height() * ratio))))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(self._surround())
        painter = QPainter(pixmap)
        dx, dy, k = self.page()
        painter.translate(dx, dy)
        painter.scale(k, k)
        canvas_w, canvas_h = self.canvas_size()
        painter.fillRect(QRectF(0.0, 0.0, canvas_w, canvas_h), _BG)
        self.paint_into(painter)
        painter.end()
        return pixmap

    #: The colours of the two marks an SVG export finds its clip by
    #: (`clip_svg`). One unit wide, at 1/255 opacity: invisible even where
    #: the marks were never taken out.
    CLIP_OPEN = "#0a0b0c"
    CLIP_CLOSE = "#0c0b0a"

    def _clip_mark(self, p, rect, opening):
        """Mark where the axes' clip starts and ends, for an SVG export.

        Qt's SVG writer ignores `setClipRect`, so an SVG drew a curve past
        the y range, a shaded integral and an interval dash straight over
        the margin (Christian, round 18). While `self._svg_clip` is a list,
        the clipped part is fenced by two marks and the clip rectangle, in
        the file's coordinates, is recorded; `clip_svg` then wraps what is
        between the marks in a real `clipPath`.
        """
        if getattr(self, "_svg_clip", None) is None:
            return
        if opening:
            self._svg_clip.append(p.transform().mapRect(QRectF(rect)))
        mark = QColor(self.CLIP_OPEN if opening else self.CLIP_CLOSE)
        mark.setAlpha(1)
        p.fillRect(QRectF(rect.left(), rect.top(), 1.0, 1.0), mark)

    def paint_into(self, painter, columns=None):
        """Draw the whole plot onto any painter, at any resolution.

        The screen and the SVG export go through this one method, so a figure
        that disagrees with the window is not possible - the rule this project
        inherits from the PXRD window, where an export that quietly differs
        from the screen was judged worse than no export.
        """
        previous, self._columns_override = self._columns_override, columns
        try:
            self._paint_all(painter)
        finally:
            self._columns_override = previous

    def _paint_all(self, p):
        # A painter on an image or an SVG starts from the APPLICATION font,
        # not this widget's: set the figure's, or exports lose the family.
        p.setFont(self.figure_font())
        rect = self.plot_rect()
        self._label_boxes = []
        self._analysis_boxes = []
        self._marker_boxes = []
        self._axis_boxes = []
        self._text_boxes = []
        p.setRenderHint(QPainter.Antialiasing, False)
        self._paint_grid(p, rect)
        if not self.traces:
            p.setPen(_TEXT_DIM)
            canvas_w, canvas_h = self.canvas_size()
            p.drawText(QRectF(0.0, 0.0, canvas_w, canvas_h), Qt.AlignCenter,
                       "Nothing to plot.\nDrop a TRIOS .tri file here.")
            self._paint_frame(p, rect)
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        # CLIPPED to the axes. A zoomed-in view still has points off both
        # sides, and without this they are drawn across the margins, the
        # numbers and the caption - which is what appears as soon as anybody
        # zooms in.
        p.save()
        p.setClipRect(rect)
        self._clip_mark(p, rect, True)
        for trace in self.traces:
            if trace.missing is None:
                self._paint_trace(p, rect, trace)
            else:
                self._paint_placeholder(p, rect, trace)
        for trace in self.traces:
            if trace.missing is None:
                self._paint_analyses(p, rect, trace)
        self._paint_offset_markers(p, rect)
        self._clip_mark(p, rect, False)
        p.restore()
        self._paint_arrow(p, rect)
        self._paint_legend(p, rect)
        self._paint_text_labels(p, rect)
        p.setRenderHint(QPainter.Antialiasing, False)
        self._paint_frame(p, rect)

    # ------------------------------------------------------------ the pieces
    def _paint_frame(self, p, rect):
        """The two axis lines, each on its side, and their captions.

        The captions are the AXIS OBJECTS talking: their text, their size and
        their position along the axis, all draggable and all editable from
        the axis's own settings. Their boxes are kept for hit-testing, so a
        double-click on a caption opens the axis rather than doing nothing.
        """
        doc = self.doc
        p.setPen(QPen(_AXIS, 1))
        x_side = self.axis_side(doc.axes["x"]) if doc else "bottom"
        y_side = self.axis_side(doc.axes["y"]) if doc else "left"
        y_line = rect.bottom() if x_side == "bottom" else rect.top()
        x_line = rect.left() if y_side == "left" else rect.right()
        p.drawLine(QPointF(rect.left(), y_line), QPointF(rect.right(), y_line))
        p.drawLine(QPointF(x_line, rect.top()), QPointF(x_line, rect.bottom()))
        # The line on the OPPOSITE side, which closes the box (Origin's
        # style, and the default): per axis, with its ticks or without.
        if doc is not None and doc.axes["x"].mirror:
            y_far = rect.top() if x_side == "bottom" else rect.bottom()
            p.drawLine(QPointF(rect.left(), y_far),
                       QPointF(rect.right(), y_far))
        if doc is not None and doc.axes["y"].mirror:
            x_far = rect.right() if y_side == "left" else rect.left()
            p.drawLine(QPointF(x_far, rect.top()),
                       QPointF(x_far, rect.bottom()))
        if doc is None:
            return
        for which in ("x", "y"):
            axis = doc.axes[which]
            if not axis.visible:
                continue
            font = QFont(p.font())
            font.setPointSizeF(self.style_of(axis, "label_size"))
            p.setFont(font)
            colour = QColor(_SELECT) if axis.selected else QColor(_TEXT)
            box = self.axis_label_rect(axis, rect, p)
            text = axis.caption(doc)
            if which == "x":
                draw_markup(p, box, text, font, colour)
            else:
                p.save()
                p.translate(box.center())
                p.rotate(-90)
                draw_markup(p, QRectF(-box.height() / 2.0, -box.width() / 2.0,
                                      box.height(), box.width()),
                            text, font, colour)
                p.restore()
            self._axis_boxes.append((axis, box.toRect()))

    def axis_spine_rect(self, which):
        """The band that counts as the SPINE: the axis line and its ticks.

        Three targets per axis, each with its own window (Christian, round
        18): the spine opens the ticks - lengths, steps, the opposite line;
        the numbers open their size and format; the caption opens the
        caption. OUTSIDE the axes box, on the axis's own side: a band
        reaching even a few pixels inside would swallow the click that
        starts a box select in the corner, which is exactly what it did.
        """
        rect = self.plot_rect()
        doc = self.doc
        if doc is None:
            return QRectF()
        axis = doc.axes[which]
        depth = max(6.0, self._tick_out(axis) + 3.0)
        return self._band(axis, rect, 0.0, depth)

    def axis_numbers_rect(self, which):
        """The band the axis's numbers sit in, beyond its spine band."""
        rect = self.plot_rect()
        doc = self.doc
        if doc is None:
            return QRectF()
        axis = doc.axes[which]
        if not getattr(axis, "show_numbers", True):
            return QRectF()
        start = max(6.0, self._tick_out(axis) + 3.0)
        return self._band(axis, rect, start,
                          max(4.0, self.tick_extent(axis) + 2.0 - start))

    def _band(self, axis, rect, start, depth):
        """A band along an axis, `start` to `start + depth` out of the box."""
        side = self.axis_side(axis)
        if side == "bottom":
            return QRectF(rect.left(), rect.bottom() + 1 + start,
                          rect.width(), depth)
        if side == "top":
            return QRectF(rect.left(), rect.top() - 1 - start - depth,
                          rect.width(), depth)
        if side == "left":
            return QRectF(rect.left() - 1 - start - depth, rect.top(),
                          depth, rect.height())
        return QRectF(rect.right() + 1 + start, rect.top(), depth,
                      rect.height())

    def axis_hit(self):
        """Which part of an axis the last pick landed on: "caption",
        "spine" or "numbers"."""
        return self._axis_hit

    def _frame_part(self, obj):
        """True for an axis picked by its spine or numbers: those open
        their settings on a double-click and are never SELECTED - no
        orange, and the caption does not light up for them."""
        return isinstance(obj, model.Axis) and self._axis_hit != "caption"

    def axis_label_rect(self, axis, rect=None, painter=None):
        """Where an axis caption sits, as a QRectF.

        `label_along` runs from 0 to 1 ALONG the axis; the caption keeps
        `caption_gap` from the axis's NUMBERS, on the axis's own side: below
        or above them for x, left or right of the widest for y. Kept on the
        figure and never over the data.
        """
        rect = rect or self.plot_rect()
        canvas_w, canvas_h = self.canvas_size()
        font = QFont(painter.font() if painter is not None else self.font())
        font.setPointSizeF(self.style_of(axis, "label_size"))
        text = axis.caption(self.doc) if self.doc else ""
        width, height = markup_size(text, font)
        width += 8
        height += 2
        gap = self.caption_gap(axis)
        reach = self.tick_extent(axis)
        side = self.axis_side(axis)
        if axis.which == "x":
            span = max(1.0, rect.width() - width)
            left = rect.left() + _clamp(axis.label_along, 0.0, 1.0) * span
            if side == "bottom":
                top = _clamp(rect.bottom() + reach + gap, rect.bottom() + 1.0,
                             max(rect.bottom() + 1.0, canvas_h - height - 1))
            else:
                top = _clamp(rect.top() - reach - gap - height, 1.0,
                             max(1.0, rect.top() - height - 1))
            return QRectF(left, top, width, height)
        span = max(1.0, rect.height() - width)
        centre_y = rect.bottom() - _clamp(axis.label_along, 0.0, 1.0) * span
        if side == "left":
            left = _clamp(rect.left() - reach - gap - height, 1.0,
                          max(1.0, rect.left() - height - 1))
        else:
            left = _clamp(rect.right() + reach + gap, rect.right() + 1.0,
                          max(rect.right() + 1.0, canvas_w - height - 1))
        return QRectF(left, centre_y - width, height, width)

    def label_colour(self, label):
        """A caption's ink: its own colour, its scan's, or the theme's.

        A label that belongs to a line reads as part of that line, so "auto"
        means the scan's colour there and the theme's ink for a free one.
        """
        if label.selected:
            return QColor(_SELECT)
        if label.colour not in (None, "", "auto"):
            return (for_light(label.colour) if THEME == THEME_LIGHT
                    else QColor(label.colour))
        owner = getattr(label, "scan", None)
        if owner is not None:
            return (for_light(owner.colour) if THEME == THEME_LIGHT
                    else QColor(owner.colour))
        return QColor(_INK)

    def _label_box(self, label, rect, base):
        """A label's box before rotation, and the font it is drawn in."""
        font = QFont(base)
        font.setPointSizeF(self.style_of(label, "size"))
        font.setBold(bool(label.bold))
        metrics = QFontMetrics(font)
        width = markup_size(label.text, font)[0] + 6
        height = metrics.height() + 2
        px, py = self.artist_point(label, rect)
        fx, fy = label.anchor_offsets()
        return QRectF(px - fx * width, py - fy * height, width, height)

    @contextlib.contextmanager
    def _rotated(self, p, artist, rect):
        """Draw `artist` turned by its rotation about its anchor point."""
        angle = float(getattr(artist, "rotation", 0.0) or 0.0)
        if not angle:
            yield
            return
        ax, ay = self.artist_point(artist, rect)
        p.save()
        p.translate(ax, ay)
        p.rotate(-angle)
        p.translate(-ax, -ay)
        try:
            yield
        finally:
            p.restore()

    def rotated_bounds(self, artist, box, rect=None):
        """The screen box around `box` turned with `artist`: what it is
        picked by."""
        angle = float(getattr(artist, "rotation", 0.0) or 0.0)
        if not angle or box is None:
            return box
        rect = rect or self.plot_rect()
        ax, ay = self.artist_point(artist, rect)
        turn = QTransform()
        turn.translate(ax, ay)
        turn.rotate(-angle)
        turn.translate(-ax, -ay)
        return turn.mapRect(QRectF(box))

    def _paint_text_labels(self, p, rect):
        """The captions the user has put on the figure."""
        doc = self.doc
        if doc is None:
            return
        for label in doc.labels:
            if not label.visible:
                continue
            box = self._label_box(label, rect, p.font())
            font = QFont(p.font())
            font.setPointSizeF(self.style_of(label, "size"))
            font.setBold(bool(label.bold))
            with self._rotated(p, label, rect):
                p.save()
                # The same markup as every other text on the figure -
                # `*T*`, `_{g}`, and LaTeX between dollars. Drawn as plain
                # text, "(Hbc)$_{1.00}$" stayed literal (round 18).
                draw_markup(p, box, label.text, font,
                            self.label_colour(label))
                p.restore()
            self._text_boxes.append(
                (label, self.rotated_bounds(label, box, rect).toRect()))

    def _paint_grid(self, p, rect):
        """Ticks, numbers and (only if asked for) grid lines, each axis on
        its own side.

        The style is the DSC_Plotter template's `style()`: ticks pointing IN,
        minor ticks between the numbered ones, and NO GRID. The panel drew a
        grid to begin with because the PXRD window does; a DSC figure does
        not, and Christian wants the default to be the figure.
        """
        doc = self.doc
        for which, view, to_px in (("x", self.view_x(), self.x_to_px),
                                   ("y", self.view_y(), self.y_to_px)):
            axis = doc.axes[which] if doc else model.Axis(0, which)
            side = self.axis_side(axis)
            font = QFont(p.font())
            font.setPointSizeF(self.style_of(axis, "tick_size"))
            p.setFont(font)
            metrics = QFontMetrics(font)
            lo, hi = view
            step = self.tick_step(axis, lo, hi)
            subdivisions = max(1, int(getattr(axis, "minor_count", 5) or 1))
            minor = step / float(subdivisions)
            length = float(getattr(axis, "tick_length", 7.0))
            minor_length = float(getattr(axis, "minor_length", 3.0))
            # +1 points into the box, -1 out of it, from each side's line.
            inward = 1.0 if axis.ticks_inward else -1.0
            into = {"bottom": -1.0, "top": 1.0, "left": 1.0, "right": -1.0}[side]
            line = {"bottom": rect.bottom(), "top": rect.top(),
                    "left": rect.left(), "right": rect.right()}[side]
            # The opposite line takes ticks too when asked (no numbers).
            far = {"bottom": rect.top(), "top": rect.bottom(),
                   "left": rect.right(), "right": rect.left()}[side]
            mirrored = (getattr(axis, "mirror", False)
                        and getattr(axis, "mirror_ticks", False))
            clear = self._tick_out(axis)
            numbers = getattr(axis, "show_numbers", True)

            def tick(at, size):
                ends = [(line, line + into * inward * size)]
                if mirrored:
                    ends.append((far, far - into * inward * size))
                for start, end in ends:
                    if which == "x":
                        p.drawLine(QPointF(at, start), QPointF(at, end))
                    else:
                        p.drawLine(QPointF(start, at), QPointF(end, at))

            value = math.ceil(lo / step) * step
            while value <= hi + 1e-9:
                at = float(to_px(value, rect))
                if axis.show_grid:
                    p.setPen(QPen(_GRID, 1))
                    if which == "x":
                        p.drawLine(QPointF(at, rect.top()),
                                   QPointF(at, rect.bottom()))
                    else:
                        p.drawLine(QPointF(rect.left(), at),
                                   QPointF(rect.right(), at))
                p.setPen(QPen(_AXIS, 1))
                tick(at, length)
                if numbers:
                    # Measured from the FONT: fixed 13 and 16 pixel boxes
                    # clipped bigger numbers instead of making room.
                    text = self.tick_text(axis, value, which)
                    p.setPen(_TEXT_DIM)
                    width = metrics.horizontalAdvance(text)
                    height = metrics.height()
                    if side == "bottom":
                        box = QRectF(at - width, line + clear + 3,
                                     2 * width, height + 2)
                        align = Qt.AlignHCenter
                    elif side == "top":
                        box = QRectF(at - width, line - clear - 3 - height - 2,
                                     2 * width, height + 2)
                        align = int(Qt.AlignHCenter | Qt.AlignBottom)
                    elif side == "left":
                        box = QRectF(line - clear - 8 - width,
                                     at - height / 2.0, width, height)
                        align = int(Qt.AlignRight | Qt.AlignVCenter)
                    else:
                        box = QRectF(line + clear + 8, at - height / 2.0,
                                     width, height)
                        align = int(Qt.AlignLeft | Qt.AlignVCenter)
                    p.drawText(box, align, text)
                value += step
            if not axis.minor_ticks or subdivisions < 2:
                continue
            p.setPen(QPen(_AXIS, 1))
            value = math.ceil(lo / minor) * minor
            while value <= hi + 1e-9:
                tick(float(to_px(value, rect)), minor_length)
                value += minor

    def columns(self, rect):
        """Sample columns, in DEVICE pixels.

        `rect.width()` is logical, so on a 150% display a per-logical-pixel
        envelope is a staircase with 1.5-device-pixel treads. Reduce at the
        resolution the screen actually has and the treads disappear.
        """
        if self._columns_override:
            return max(1, int(self._columns_override))
        return max(1, int(round(rect.width()
                                * float(self.devicePixelRatioF() or 1.0))))

    def _polylines(self, trace, rect):
        """The curve as polylines, decimated per pixel column.

        Two things make this different from the PXRD version, and both come
        from x not being sorted:

        * the visible part is taken with a MASK, dilated by one sample so a
          segment entering the view is not cut short;
        * the mask is split into CONTIGUOUS RUNS, so a curve that leaves the
          view and comes back is two polylines rather than one with a
          straight line drawn across the gap.

        Within a run, the decimation groups CONSECUTIVE samples that fall in
        the same pixel column, which tolerates reversals: a turning point
        simply starts a new group.
        """
        x, y = trace.x, trace.y
        if x is None or not len(x):
            return [], None, None
        lo, hi = self.view_x()
        inside = (x >= lo) & (x <= hi)
        if not inside.any():
            return [], None, None
        keep = inside.copy()
        keep[1:] |= inside[:-1]
        keep[:-1] |= inside[1:]
        idx = np.flatnonzero(keep)
        breaks = np.flatnonzero(np.diff(idx) > 1)
        runs = np.split(idx, breaks + 1)
        columns = self.columns(rect)
        left, width = rect.left(), max(1, rect.width())
        polys, all_px, all_py = [], [], []
        for run in runs:
            if len(run) < 2:
                continue
            xs, ys = x[run], y[run]
            px = left + (xs - lo) / max(hi - lo, 1e-12) * width
            py = self.y_to_px(ys, rect)
            if len(px) > columns:
                col = np.clip(((px - left) / width * columns).astype(np.int64),
                              0, columns - 1)
                starts = np.flatnonzero(
                    np.concatenate(([True], col[1:] != col[:-1])))
                cx = px[starts]
                top = np.minimum.reduceat(py, starts)
                bottom = np.maximum.reduceat(py, starts)
                px, py = _columns(cx, top, bottom)
            polys.append(_polyline(px, py))
            all_px.append(px)
            all_py.append(py)
        if not polys:
            return [], None, None
        return polys, np.concatenate(all_px), np.concatenate(all_py)

    def _paint_trace(self, p, rect, trace):
        polys, px, py = self._polylines(trace, rect)
        trace.px, trace.py = px, py
        width = self.style_of(trace.scan, "line_width") * CURVE_WIDTH
        if trace.scan.selected:
            halo = QColor(_SELECT)
            halo.setAlpha(90)
            p.setPen(QPen(halo, width + 4.0))
            for poly in polys:
                p.drawPolyline(poly)
            width += SELECTED_EXTRA
        p.setPen(QPen(trace_colour(trace), width))
        for poly in polys:
            p.drawPolyline(poly)

    def _paint_placeholder(self, p, rect, trace):
        """A scan that cannot be drawn in this unit, drawn as its absence.

        A dashed line at its own offset: it keeps its place in the stack, it
        can be picked and right-clicked, and it is plainly not a measurement.
        The alarm label beside it is painted per event so it can blink.
        """
        trace.px = trace.py = None
        y = self.y_to_px(trace.scan.offset, rect)
        if not (rect.top() - 4 <= y <= rect.bottom() + 4):
            return
        colour = trace_colour(trace)
        colour.setAlpha(120)
        p.setPen(QPen(colour, 1.0, Qt.DashLine))
        p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _paint_analyses(self, p, rect, trace):
        """The analyses switched ON for this scan, as markers on its curve.

        Nothing is drawn unless it was ticked: a run carries a dozen stored
        analyses and a figure wants one or two, so they start off and are
        switched on in the outliner or in the scan's settings.

        The marker sits at the CURVE, not at the baseline: the nearest sample
        to the stored temperature, which is the one place the eye expects it.
        An analysis whose attribution is a GUESS (a `.txt` export names only
        the step, and three segments share a name) is drawn with a dashed
        tick, so the figure says which numbers are certain.
        """
        doc = self.doc
        if doc is None or doc.x_axis != model.AXIS_TEMPERATURE:
            return                     # the stored cursors are temperatures
        lo, hi = self.view_x()
        for analysis in trace.scan.visible_analyses():
            value = analysis.value()
            if value is None:
                continue
            value = self.to_axis(value)
            if not (lo <= value <= hi):
                continue
            anchor_y = self._curve_y_at(trace, value, rect,
                                        self._analysis_slice(trace, analysis))
            if anchor_y is None:
                continue
            colour = (QColor(_SELECT) if analysis.selected
                      else self.analysis_colour(analysis, trace))
            if analysis.shade and "Integration" in analysis.model_name:
                self._paint_integral(p, rect, trace, analysis, colour)
            # After the shading, so the dashes sit ON TOP of trace and fill.
            if analysis.show_interval:
                self._paint_interval(p, rect, trace, analysis)
            self._paint_analysis_label(p, rect, trace, analysis, value,
                                       anchor_y, colour)

    def _paint_integral(self, p, rect, trace, analysis, colour):
        """The shaded area between the curve and its baseline.

        What `add_integral_trios` draws in the template: the region the
        enthalpy was measured over, filled between the curve and the straight
        baseline joining the two stored cursors. A number with nothing under
        it says where a peak is; the shading says what was integrated.
        """
        covered = self._covered(trace, analysis)
        if covered is None:
            return
        xs, ys = covered
        # The baseline is a straight line between the curve's own values at
        # the two cursors, which is TRIOS's "linear, double point".
        base = _chord(xs, ys)
        px = self.x_to_px(xs, rect)
        top = self.y_to_px(ys, rect)
        bottom = self.y_to_px(base, rect)
        shape = QPolygonF()
        for a, b in zip(px.tolist(), top.tolist()):
            shape.append(QPointF(a, b))
        for a, b in zip(px.tolist()[::-1], bottom.tolist()[::-1]):
            shape.append(QPointF(a, b))
        fill = QColor(colour)
        fill.setAlpha(55)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPolygon(shape)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(colour, 0.8, Qt.SolidLine))
        p.drawLine(QPointF(px[0], bottom[0]), QPointF(px[-1], bottom[-1]))

    def label_offset(self, analysis, trace, rect):
        """How far the label sits from the curve, in pixels.

        `label_dy` of None means "work it out": the label goes on the side the
        peak does NOT occupy, so the leader arrow never crosses the shading.
        A negative integral - an endotherm on an exo-down axis - therefore
        labels from below, which is Christian's report. Once it has been
        dragged the stored number wins, because that was a decision.
        """
        if analysis.label_dy is not None:
            return float(analysis.label_dy)
        return -46.0 if self.peak_points_up(analysis, trace) else 46.0

    def _covered(self, trace, analysis):
        """`(xs, ys)`: the part of the drawn curve an integration covers.

        Its own stretch of samples when it was measured along the curve;
        otherwise every sample between the two stored cursor temperatures,
        which is all a file's analysis says - and which, on a curve that
        doubles back, takes in more than one branch.
        """
        stretch = self._analysis_slice(trace, analysis)
        if stretch is not None:
            a, b = stretch
            if b - a < 2:
                return None
            return trace.x[a:b + 1], trace.y[a:b + 1]
        x0 = model.number(analysis.fields.get("Baseline cursor x"))
        x1 = model.number(analysis.fields.get("Baseline cursor x1"))
        if x0 is None or x1 is None or trace.x is None:
            return None
        low, high = self.to_axis(min(x0, x1)), self.to_axis(max(x0, x1))
        inside = (trace.x >= low) & (trace.x <= high)
        if inside.sum() < 3:
            return None
        return trace.x[inside], trace.y[inside]

    def peak_points_up(self, analysis, trace):
        """True when the feature rises above its own baseline on screen."""
        covered = self._covered(trace, analysis)
        if covered is None:
            return True
        xs, ys = covered
        deviation = ys - _chord(xs, ys)
        # On screen y grows downward, so a curve ABOVE its baseline in data
        # terms is the one with the larger positive deviation.
        return abs(float(deviation.max())) >= abs(float(deviation.min()))

    def to_axis(self, celsius):
        """A stored temperature, in whatever unit the axis is showing."""
        doc = self.doc
        if doc is None or doc.x_axis != model.AXIS_TEMPERATURE:
            return celsius
        return units.from_celsius(celsius, getattr(doc, "x_unit",
                                                   units.TEMP_C))

    def interval_marks(self, trace, analysis, rect=None):
        """What marks an analysis's interval, in pixels: `(dashes, lines)`.

        Christian's rules (round 10), replacing a copy of the curve drawn a
        few pixels ABOVE it between the two bounds - which sat over the data
        and said nothing the dashes did not:

        * **dashes**: a short vertical dash at each bound, centred ON the
          trace. Every analysis with two cursors has them.
        * **lines**: only where the result is a temperature on the curve
          (`Analysis.marks_a_point` - onset, endset, glass transition). A
          straight line from the left bound to the result point and on to the
          right bound: the template's construction. No dash at the point
          itself; the label's arrow already marks it.
        * an integration gets the dashes alone: its shading and baseline show
          what was integrated, and a connecting curve must never be drawn.

        Each (a, b) pair is a segment between two QPointF.
        """
        rect = rect or self.plot_rect()
        cursors = analysis.cursors()
        if len(cursors) != 2 or trace.x is None or not len(trace.x):
            return [], []
        stretch = self._analysis_slice(trace, analysis)
        bounds = []
        if stretch is not None:
            # Measured along the curve: the bounds ARE two samples.
            for local in stretch:
                bounds.append(QPointF(
                    float(self.x_to_px(trace.x[local], rect)),
                    float(self.y_to_px(trace.y[local], rect))))
        else:
            for celsius in sorted(cursors):
                x = self.to_axis(celsius)
                y = self._curve_y_at(trace, x, rect)
                if y is None:
                    return [], []
                bounds.append(QPointF(float(self.x_to_px(x, rect)),
                                      float(y)))
        dashes = [(QPointF(b.x(), b.y() - INTERVAL_TICK),
                   QPointF(b.x(), b.y() + INTERVAL_TICK)) for b in bounds]
        lines = []
        value = analysis.value() if analysis.marks_a_point else None
        if value is not None:
            x = self.to_axis(value)
            y = self._curve_y_at(trace, x, rect, stretch)
            if y is not None:
                point = QPointF(float(self.x_to_px(x, rect)), float(y))
                lines = [(bounds[0], point), (point, bounds[1])]
        return dashes, lines

    def _paint_interval(self, p, rect, trace, analysis):
        """The interval marks, in the axis colour: structure, not data.

        The template draws these and a figure needs them - an enthalpy with
        no interval marked is a number somebody has to take on trust. Each
        analysis can switch them off (`show_interval`) for the cases where
        two overlap.
        """
        dashes, lines = self.interval_marks(trace, analysis, rect)
        if not dashes:
            return
        p.setPen(QPen(QColor(_AXIS), 1.0))
        for a, b in lines + dashes:
            # Cut to the axes box HERE, not only by the painter's clip: a
            # bound outside the view put its dash on the margin of an
            # exported figure (Christian, round 18), and a viewer that
            # ignores an SVG clip would do it again.
            kept = _clip_segment(a, b, rect)
            if kept is not None:
                p.drawLine(*kept)

    def _paint_analysis_label(self, p, rect, trace, analysis, value, anchor_y,
                              colour):
        """The label, and the arrow from it down to what it names.

        The label sits `label_dy` pixels from the curve and the arrow is
        drawn between the two, so moving the label lengthens or shortens the
        arrow - which is what dragging an analysis does. The movement is
        locked vertically for now, so a label cannot drift off its feature.

        `flush` is the template's: which edge of the text sits on the arrow.
        Left puts the arrow under the first letter, so the label reads away
        to the right of its feature; right is the mirror image; centre hangs
        it over the arrow. The arrow stays vertical whichever it is - the
        point it touches is the feature, and only the text moves around it.
        """
        font = QFont(p.font())
        font.setPointSizeF(max(5.0, float(self.style_of(analysis,
                                                        "label_size"))))
        p.setFont(font)
        text = labels.render(analysis, self.doc).text
        if not analysis.certain:
            text += " ?"
        x = float(self.x_to_px(value, rect))
        label_y = float(anchor_y) + self.label_offset(analysis, trace, rect)
        width, height = markup_size(text, font)
        # `draw_markup` centres the text in the box, so the 3 px either side
        # is where it starts and ends: a left flush starts the TEXT at x.
        width += 6
        flush = self.analysis_flush(analysis)
        if flush == style.FLUSH_LEFT:
            left = x - 3.0
        elif flush == style.FLUSH_RIGHT:
            left = x - width + 3.0
        else:
            left = x - width / 2.0
        box = QRectF(left, label_y - height / 2.0, width, height)
        # The arrow runs from the edge of the text to the curve, so the head
        # lands ON the feature and not inside the writing.
        start = box.bottom() + 2 if label_y < anchor_y else box.top() - 2
        p.setPen(QPen(colour, 1.0,
                      Qt.SolidLine if analysis.certain else Qt.DashLine))
        p.drawLine(QPointF(x, start), QPointF(x, anchor_y))
        step = 5.0 if label_y < anchor_y else -5.0
        head = QPolygonF([QPointF(x, anchor_y),
                          QPointF(x - 3.0, anchor_y - step),
                          QPointF(x + 3.0, anchor_y - step)])
        p.setBrush(colour)
        p.setPen(QPen(colour, 0.5))
        p.drawPolygon(head)
        p.setBrush(Qt.NoBrush)
        draw_markup(p, box, text, font, colour)
        self._analysis_boxes.append((analysis, box.toRect()))

    def _temperature_axis(self):
        return (self.doc is not None
                and self.doc.x_axis == model.AXIS_TEMPERATURE)

    def _shown_samples(self, trace, rect):
        """`(px, py, shown)` for a trace's kept samples: where each is on
        screen, and whether it is inside the axes box - the curve as it is
        actually SHOWN, truncated and framed."""
        px = np.asarray(self.x_to_px(trace.x, rect), dtype=float)
        py = np.asarray(self.y_to_px(trace.y, rect), dtype=float)
        shown = (np.isfinite(px) & np.isfinite(py)
                 & (px >= rect.left()) & (px <= rect.right())
                 & (py >= rect.top()) & (py <= rect.bottom()))
        return px, py, shown

    @staticmethod
    def _walk(px, shown, k, target, slack=3.0):
        """From sample `k`, ALONG the curve (either way, sample by sample)
        towards screen x = `target`: the shown sample that gets closest
        before the curve turns away for good or leaves the view.

        Temperature jitters sample to sample, so a step that goes slightly
        the wrong way is walked through; turning away by more than `slack`
        is a real reversal (a hook, the turn of a cooling) and stops it.
        """
        n = len(px)
        best = k
        for step in (1, -1):
            j = k
            while 0 <= j + step < n and shown[j + step]:
                j += step
                gap = abs(px[j] - target)
                if gap < abs(px[best] - target):
                    best = j
                elif gap > abs(px[best] - target) + slack:
                    break
        return best

    def marker_sample(self, marker, trace=None, rect=None):
        """The sample a marker points at, as an index into its trace's KEPT
        samples, or None when that point is not on the shown curve.

        Unplaced, it is the leftmost point of the curve AS SHOWN - kept,
        and inside the view - walked a few units along the curve, so it
        sits tight against the y axis wherever the curve reaches it and at
        the shown end of one that starts later. Never the raw data: a
        truncated start or a stretch outside the view is not a place to
        point at (Christian, round 15)."""
        rect = rect or self.plot_rect()
        trace = trace or self._trace_of(marker.scan)
        if trace is None or trace.x is None or not len(trace.x):
            return None
        px, _py, shown = self._shown_samples(trace, rect)
        if not shown.any():
            return None
        at = marker.at
        if at and at[0] == "i":
            k = int(at[1]) - trace.first
            return k if 0 <= k < len(px) and shown[k] else None
        if at and at[0] == "T" and self._temperature_axis():
            aim = float(self.x_to_px(self.to_axis(float(at[1])), rect))
            return int(np.argmin(np.where(shown, np.abs(px - aim), np.inf)))
        start = int(np.argmin(np.where(shown, px, np.inf)))
        return self._walk(px, shown, start, px[start] + OFFSET_MARKER_INSET)

    def marker_at(self, marker):
        """Where a marker is drawn, as it would be STORED: `("i", sample)`
        in the segment's own numbering; what it holds when not drawn."""
        trace = self._trace_of(marker.scan)
        k = self.marker_sample(marker, trace)
        return marker.at if k is None else ("i", trace.first + k)

    def _walked(self, marker, at, dx_px, rect):
        """A marker's place `at`, moved `dx_px` along its curve."""
        if not dx_px or not at or at[0] != "i":
            return at
        trace = self._trace_of(marker.scan)
        if trace is None or trace.x is None or not len(trace.x):
            return at
        px, _py, shown = self._shown_samples(trace, rect)
        k = int(at[1]) - trace.first
        if not (0 <= k < len(px) and shown[k]):
            return at
        return ("i", trace.first + self._walk(px, shown, k, px[k] + dx_px))

    def marker_x(self, marker):
        """The x a marker points at, in the axis's unit, or None."""
        trace = self._trace_of(marker.scan)
        k = self.marker_sample(marker, trace)
        return None if k is None else float(trace.x[k])

    def marker_celsius(self, marker):
        """The temperature (degC) of the sample a marker points at, or None
        (not drawn, or not on a temperature axis)."""
        if not self._temperature_axis():
            return None
        trace = self._trace_of(marker.scan)
        k = self.marker_sample(marker, trace)
        return (None if k is None
                else self._celsius_of(marker.scan, trace.first + k))

    def marker_text(self, marker):
        """The offset, written in the marker's (or the house) format - and
        CONVERTED when the format names a unit (`%.2f mW`): the offset is
        in the y axis's unit, the marker may say it in another."""
        spec = self.style_of(marker, "number_format")
        unit = numbers.split(spec)[1]
        value = float(marker.scan.offset)
        if unit:
            value = labels.convert_heat_flow(value, self.doc.y_unit, unit,
                                             marker.scan)
            if value is None:
                return "? " + unit
        text = numbers.write(value, spec, numbers.OFFSET)
        return "{} {}".format(text, unit) if unit else text

    def marker_dy(self, marker, rect=None):
        """How far below its curve a marker's text starts (above if < 0)."""
        if marker.dy is not None:
            return float(marker.dy)
        return OFFSET_MARKER_DROP * (rect or self.plot_rect()).height()

    def marker_colour(self, marker):
        if marker.selected:
            return QColor(_SELECT)
        if marker.colour in (None, "", "auto"):
            return QColor(_INK)
        return (for_light(marker.colour) if THEME == THEME_LIGHT
                else QColor(marker.colour))

    def _paint_offset_markers(self, p, rect):
        """The template's `add_yoffset_markers`: each drawn scan's offset,
        `+0.5`, under its curve with a small arrow up to it, the left edge
        of the text on the arrow. One object per scan (`Scan.marker`),
        picked, moved and styled like any label."""
        doc = self.doc
        if doc is None or not doc.offset_markers:
            return
        for trace in self.drawable():
            marker = trace.scan.marker
            if not marker.visible:
                continue
            k = self.marker_sample(marker, trace, rect)
            if k is None:
                continue
            x = float(self.x_to_px(trace.x[k], rect))
            anchor = float(self.y_to_px(trace.y[k], rect))
            font = QFont(p.font())
            font.setPointSizeF(max(4.0, float(self.style_of(marker, "size"))))
            p.setFont(font)
            metrics = QFontMetrics(font)
            colour = self.marker_colour(marker)
            text = self.marker_text(marker)
            dy = self.marker_dy(marker, rect)
            width = metrics.horizontalAdvance(text) + 6.0
            height = float(metrics.height())
            below = dy >= 0
            top = anchor + dy if below else anchor + dy - height
            box = QRectF(x - 3.0, top, width, height)
            start = box.top() if below else box.bottom()
            tip = 1.0 if below else -1.0         # the head points at the curve
            p.setPen(QPen(colour, 0.8))
            if abs(start - anchor) > 4.0:
                p.drawLine(QPointF(x, start), QPointF(x, anchor + 3.0 * tip))
            p.setBrush(colour)
            p.drawPolygon(QPolygonF([QPointF(x, anchor),
                                     QPointF(x - 2.0, anchor + 4.0 * tip),
                                     QPointF(x + 2.0, anchor + 4.0 * tip)]))
            p.setBrush(Qt.NoBrush)
            p.drawText(box, Qt.AlignCenter, text)
            self._marker_boxes.append((marker, box.united(
                QRectF(x - 3.0, min(anchor, start), 6.0,
                       abs(start - anchor)))))

    def analysis_flush(self, analysis):
        """"left", "center" or "right" for this label, never "auto"."""
        return style.flush_for(analysis, self.style_of(analysis, "flush"))

    def analysis_colour(self, analysis, trace=None):
        """An analysis is its scan's colour unless it was given its own."""
        if analysis.colour in (None, "", "auto"):
            colour = (trace_colour(trace) if trace is not None
                      else QColor(analysis.scan.colour))
            colour.setAlpha(190)
            return colour
        return (for_light(analysis.colour) if THEME == THEME_LIGHT
                else QColor(analysis.colour))

    def _analysis_slice(self, trace, analysis):
        """`(a, b)`: the stretch of the drawn curve an analysis covers, as
        inclusive indices into `trace.x`, or None when it was not measured
        along the curve (a file's analyses, typed temperatures)."""
        span = getattr(analysis, "span", None)
        if not span or trace.x is None or not len(trace.x):
            return None
        last = len(trace.x) - 1
        a = int(_clamp(span[0] - trace.first, 0, last))
        b = int(_clamp(span[1] - trace.first, 0, last))
        return (a, b) if b > a else None

    def _curve_y_at(self, trace, value, rect, within=None):
        """The screen y of the drawn curve nearest x = `value`, or None.

        "Nearest sample" rather than an interpolation, because x doubles back
        on itself: there is no single y at a temperature a cooling scan passed
        through twice, and the sample the analysis was computed from is the
        one that matters.
        """
        if trace.x is None or not len(trace.x):
            return None
        lo, hi = within if within is not None else (0, len(trace.x) - 1)
        xs = trace.x[lo:hi + 1]
        if not len(xs):
            return None
        index = lo + int(np.argmin(np.abs(xs - value)))
        return self.y_to_px(float(trace.y[index]), rect)

    def _paint_names(self, p):
        """Which curve is which - for the one under the cursor, and for the
        selected ones. Nothing else.

        These are a READOUT, not part of the figure: they appear when you
        point at a curve and go when you stop. A caption that belongs in the
        figure is a `TextLabel`, which is an object you place and keep.
        Painted per event rather than into the cache, because they follow the
        cursor.
        """
        rect = self.plot_rect()
        hovered = (self._trace_at(self._cursor)
                   if self._cursor is not None and self._move is None
                   else None)
        wanted = [t for t in self.traces
                  if t.scan.selected or t is hovered]
        if not wanted:
            self._label_boxes = []
            return
        metrics = QFontMetrics(p.font())
        boxes = []
        for trace in wanted:
            y = None
            if trace.py is not None and len(trace.py):
                y = float(trace.py[np.argmax(trace.px)])
            elif trace.missing is not None:
                y = self.y_to_px(trace.scan.offset, rect)
            if y is None or not (rect.top() - 20 <= y <= rect.bottom() + 20):
                continue
            text = trace.name
            width = metrics.horizontalAdvance(text)
            box = QRect(int(rect.right()) - width - 10, int(y) - 9,
                        width + 8, 17)
            box = _free_slot(box, [b for _t, b in boxes], rect)
            background = QColor(_BG)
            background.setAlpha(190)
            p.fillRect(box, background)
            p.setPen(QPen(_SELECT if trace.scan.selected
                          else trace_colour(trace), 1))
            p.drawText(box, int(Qt.AlignLeft | Qt.AlignVCenter), text)
            boxes.append((trace, box))
        self._label_boxes = boxes

    def _arrow_rect(self):
        """What the cursor has to be inside to mean the arrow.

        The arrow AND its label, since the two are one object as far as
        anybody pointing at them is concerned.
        """
        geometry = self.arrow_geometry()
        if geometry is None:
            return QRect()
        tail_top, head_tip, cx, _head_len, head_half, tail_half = geometry
        half = max(8.0, head_half + 4.0, tail_half + 4.0)
        top, bottom = min(tail_top, head_tip), max(tail_top, head_tip)
        label = 2.4 * QFontMetrics(self.arrow_font()).height()
        if head_tip > tail_top:
            top -= label                       # the label sits above
        else:
            bottom += label
        return QRect(int(cx - half), int(top), int(2 * half),
                     int(bottom - top))

    def artist_point(self, artist, rect=None):
        """Where an artist sits, in pixels, whichever space it is stored in."""
        rect = rect or self.plot_rect()
        if getattr(artist, "space", "relative") == model.SPACE_DATA:
            return (float(self.x_to_px(artist.x, rect)),
                    float(self.y_to_px(artist.y, rect)))
        return (rect.left() + float(artist.x) * rect.width(),
                rect.top() + float(artist.y) * rect.height())

    def set_artist_point(self, artist, px, py, rect=None, clamp=True):
        """Put an artist at a pixel position, in its own space.

        A drag keeps a relative artist's anchor inside the plot; a scale or
        rotation (`clamp=False`) must not, or the point it is about moves
        whenever the anchor would pass the edge."""
        rect = rect or self.plot_rect()
        if getattr(artist, "space", "relative") == model.SPACE_DATA:
            artist.set_position(self.px_to_x(px, rect), self.px_to_y(py, rect))
        else:
            fx = (px - rect.left()) / max(1.0, rect.width())
            fy = (py - rect.top()) / max(1.0, rect.height())
            if clamp:
                fx, fy = _clamp(fx, 0.01, 0.99), _clamp(fy, 0.01, 0.99)
            artist.set_position(fx, fy)
        return artist

    def convert_artist_space(self, artist, space, rect=None):
        """Change which space an artist is stored in, keeping it in place."""
        rect = rect or self.plot_rect()
        px, py = self.artist_point(artist, rect)
        artist.space = space
        self.set_artist_point(artist, px, py, rect)
        return artist

    def legend_rect(self, rect=None, painter=None):
        """Where the legend sits and how big it is, or None when it is off."""
        doc = self.doc
        if doc is None or not doc.legend.visible:
            return None
        legend = doc.legend
        entries = legend.entries(doc)
        if not entries:
            return None
        rect = rect or self.plot_rect()
        font = QFont(painter.font() if painter is not None else self.font())
        font.setPointSizeF(self.style_of(legend, "size"))
        metrics = QFontMetrics(font)
        width = 0
        for _scan, text in entries:
            width = max(width, markup_size(text, font)[0])
        width += legend.sample + 18
        height = metrics.height() * legend.spacing * len(entries) + 10
        px, py = self.artist_point(legend, rect)
        fx, fy = legend.anchor_offsets()
        return QRectF(px - fx * width, py - fy * height, width, height)

    def _paint_legend(self, p, rect):
        """The key: a colour sample and a name per drawn scan."""
        doc = self.doc
        if doc is None or not doc.legend.visible:
            return
        legend = doc.legend
        box = self.legend_rect(rect, p)
        if box is None:
            return
        with self._rotated(p, legend, rect):
            p.save()
            self._paint_legend_box(p, legend, box)
            p.restore()

    def _paint_legend_box(self, p, legend, box):
        doc = self.doc
        font = QFont(p.font())
        font.setPointSizeF(self.style_of(legend, "size"))
        p.setFont(font)
        metrics = QFontMetrics(font)
        if legend.show_frame:
            backing = QColor(_BG)
            backing.setAlpha(210)
            p.setBrush(backing)
            edge = QColor(_SELECT) if legend.selected else QColor(_GRID)
            p.setPen(QPen(edge, 1.0))
            p.drawRoundedRect(box, 3, 3)
            p.setBrush(Qt.NoBrush)
        elif legend.selected:
            p.setPen(QPen(_SELECT, 1.0, Qt.DashLine))
            p.drawRect(box)
        step = metrics.height() * legend.spacing
        y = box.top() + 5 + metrics.height() / 2.0
        for scan, text in legend.entries(doc):
            colour = (for_light(scan.colour) if THEME == THEME_LIGHT
                      else QColor(scan.colour))
            width = (float(legend.line_width) if legend.line_width
                     else max(1.2, self.style_of(scan, "line_width")
                              * CURVE_WIDTH))
            p.setPen(QPen(colour, width))
            p.drawLine(QPointF(box.left() + 8, y),
                       QPointF(box.left() + 8 + legend.sample, y))
            ink = (QColor(_SELECT) if legend.selected
                   else (QColor(_TEXT) if legend.colour in (None, "", "auto")
                         else (for_light(legend.colour)
                               if THEME == THEME_LIGHT
                               else QColor(legend.colour))))
            text_box = QRectF(box.left() + legend.sample + 14,
                              y - metrics.height() / 2.0,
                              box.width() - legend.sample - 20,
                              metrics.height())
            draw_markup(p, QRectF(text_box.left() + markup_size(text, font)[0]
                                  / 2.0, text_box.top(), 0, text_box.height()),
                        text, font, ink)
            y += step

    def arrow_colour(self):
        """The ink the arrow is drawn in: its own colour, or the theme's.

        "auto" is the default and means "whatever reads on this background",
        so the same figure works in both themes without the arrow having to
        be recoloured by hand. A colour the user picks is used as it stands.
        """
        doc = self.doc
        chosen = doc.arrow.colour if doc is not None else "auto"
        if chosen in (None, "", "auto"):
            return QColor(_INK)
        return for_light(chosen) if THEME == THEME_LIGHT else QColor(chosen)

    def arrow_font(self, base=None):
        """The arrow's text: the house style's size unless it has its own."""
        font = QFont(base if base is not None else self.font())
        size = self.style_of(self.doc.arrow, "size") if self.doc else 10.0
        font.setPointSizeF(max(4.0, float(size)))
        return font

    def arrow_geometry(self, rect=None):
        """`(tail_top, head_tip, cx, head_len, head_half, tail_half)` in
        figure units, or None.

        From the arrow's own dimensions in POINTS - head length and width,
        tail length and width - which default to the DSC_Plotter template's
        `add_exo_arrow` (tail 4.5 wide, head 13 wide and 9 long, tail 0.9 of
        the head), so the panel and the published figure draw one arrow.
        """
        doc = self.doc
        if doc is None:
            return None
        arrow = doc.arrow
        rect = rect or self.plot_rect()
        head_len = max(0.5, float(arrow.head_length)) * PT
        total = head_len + max(0.0, float(arrow.tail_length)) * PT
        head_half = max(0.25, float(arrow.head_width)) * PT / 2.0
        tail_half = max(0.25, float(arrow.tail_width)) * PT / 2.0
        cx, cy = self.artist_point(arrow, rect)
        fx, fy = arrow.anchor_offsets()
        cx += (0.5 - fx) * 2.0 * max(head_half, tail_half)
        cy += (0.5 - fy) * total
        down = arrow.direction == units.EXO_DOWN
        tail_top = cy - total / 2.0 if down else cy + total / 2.0
        head_tip = cy + total / 2.0 if down else cy - total / 2.0
        return tail_top, head_tip, cx, head_len, head_half, tail_half

    def _paint_arrow(self, p, rect):
        """The heat-flow arrow: an object, not a decoration.

        It points the way its label says, which is also the way the data is
        drawn - `units.orientation` keeps the two from contradicting each
        other, so a figure cannot go out with an arrow that disagrees with
        its own axis.

        ONE filled polygon: a shaft of the tail's width and length and a
        solid head of its own length and width (the tip angle follows from
        the two), as the template's `add_exo_arrow` draws it.
        """
        doc = self.doc
        if doc is None or not doc.arrow.visible:
            return
        arrow = doc.arrow
        geometry = self.arrow_geometry(rect)
        if geometry is None:
            return
        tail_top, head_tip, cx, head_len, half_head, half_shaft = geometry
        colour = QColor(_SELECT) if arrow.selected else self.arrow_colour()
        step = 1.0 if head_tip > tail_top else -1.0        # down or up
        head_base = head_tip - step * head_len
        shape = QPolygonF([
            QPointF(cx - half_shaft, tail_top),
            QPointF(cx + half_shaft, tail_top),
            QPointF(cx + half_shaft, head_base),
            QPointF(cx + half_head, head_base),
            QPointF(cx, head_tip),
            QPointF(cx - half_head, head_base),
            QPointF(cx - half_shaft, head_base),
        ])
        p.setPen(QPen(colour, 0.6))
        p.setBrush(colour)
        p.drawPolygon(shape)
        p.setBrush(Qt.NoBrush)
        font = self.arrow_font(p.font())
        p.setFont(font)
        p.setPen(colour)
        # The label sits beyond the TAIL, which is above an exo-down arrow and
        # below an exo-up one, so it never covers the head.
        height = 2.2 * QFontMetrics(font).height()
        top = (tail_top - height - 4.0) if step > 0 else (tail_top + 4.0)
        p.drawText(QRectF(cx - 100, top, 200, height),
                   int(Qt.AlignHCenter | (Qt.AlignBottom if step > 0
                                          else Qt.AlignTop)),
                   arrow.text())

    # --------------------------------------------------- per-event overlays
    #: The reticle's circle radius, and how far its ticks reach past it.
    RETICLE_RADIUS = 13.0
    RETICLE_TICK = 6.0

    def _paint_cursor(self, p):
        """A RETICLE where the cursor is, not a line down the plot.

        The dashed vertical was borrowed from the PXRD window, where the x
        position is the whole question. Here it mostly gets in the way of
        reading a stack, so the plain cursor is a ring with four ticks and a
        small cross - a sight, which is what a pointer on a figure is.
        """
        if self._cursor is None or self._measure is not None:
            return
        rect = self.plot_rect()
        x, y = float(self._cursor.x()), float(self._cursor.y())
        if not (rect.left() <= x <= rect.right()
                and rect.top() <= y <= rect.bottom()):
            return
        k = self.page()[2]
        radius = self.RETICLE_RADIUS / k
        tick = self.RETICLE_TICK / k
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(_CURSOR, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(x, y), radius, radius)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            p.drawLine(QPointF(x + dx * (radius - 3), y + dy * (radius - 3)),
                       QPointF(x + dx * (radius + tick),
                               y + dy * (radius + tick)))
        p.drawLine(QPointF(x - 3, y), QPointF(x + 3, y))
        p.drawLine(QPointF(x, y - 3), QPointF(x, y + 3))
        p.setRenderHint(QPainter.Antialiasing, False)

    def _paint_select_box(self, p):
        """The selection rectangle: dashed, in the selection colour, so it
        cannot be mistaken for the zoom band."""
        box = self._box
        # Only once it IS a box: every press starts one now, and a click
        # that never became a drag should not leave a dot behind.
        if box is None or not box.get("moved"):
            return
        rect = QRectF(box["start"], box["now"]).normalized()
        fill = QColor(_SELECT)
        fill.setAlpha(40)
        p.fillRect(rect, fill)
        p.setPen(QPen(_SELECT, 1, Qt.DashLine))
        p.drawRect(rect)

    def _paint_band(self, p):
        drag = self._drag
        if drag is None or not drag["mode"].startswith("zoom") \
                or self._cursor is None:
            return
        rect = self.plot_rect()
        x0, y0 = drag["px"], drag["py"]
        x1 = _clamp(self._cursor.x(), rect.left(), rect.right())
        y1 = _clamp(self._cursor.y(), rect.top(), rect.bottom())
        if drag["mode"] == "zoom_h":
            band = QRectF(min(x0, x1), rect.top(), abs(x1 - x0),
                          rect.height())
        elif drag["mode"] == "zoom_v":
            band = QRectF(rect.left(), min(y0, y1), rect.width(),
                          abs(y1 - y0))
        else:
            band = QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0),
                          abs(y1 - y0))
        p.fillRect(band, _BAND)
        p.setPen(QPen(_BAND_EDGE, 1, Qt.DashLine))
        p.drawRect(band)

    def _paint_offsets(self, p, force=False):
        """The offset arrow: how far a scan has been moved, as a number.

        Christian's ask, and it is what replaces the PXRD window's stack
        slots: if a scan can sit anywhere, the figure has to say where it is
        sitting. Drawn for the scans being moved and for the selected ones,
        rather than for all of them, because eight of these at once is a mess.
        """
        doc = self.doc
        if doc is None:
            return
        rect = self.plot_rect()
        scans = [t.scan for t in self.traces
                 if t.scan.selected or (self._move is not None
                                        and t.scan in self._move["objs"])]
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.0))
        p.setFont(font)
        for scan in scans:
            if not scan.offset:
                continue
            zero = self.y_to_px(0.0, rect)
            here = self.y_to_px(scan.offset, rect)
            if abs(zero - here) < 4:
                continue
            x = rect.left() + 26
            colour = QColor(scan.colour)
            p.setPen(QPen(colour, 1.0, Qt.DashLine))
            p.drawLine(int(rect.left()), int(here), int(x + 40), int(here))
            p.setPen(QPen(colour, 1.2))
            p.drawLine(int(x), int(zero), int(x), int(here))
            for end, sign in ((zero, 1), (here, -1)):
                p.drawLine(int(x), int(end), int(x - 4), int(end + 5 * sign))
                p.drawLine(int(x), int(end), int(x + 4), int(end + 5 * sign))
            p.drawText(QPoint(int(x) + 6, int((zero + here) / 2) + 4),
                       "{:+.4g} {}".format(scan.offset, doc.y_unit))

    def _paint_alarms(self, p):
        """The blinking red label on a scan that is missing its molar mass.

        Painted per event rather than into the cache, because it blinks, and
        blinking a cached pixmap would mean rebuilding the curves twice a
        second. Not drawn at all while a gesture is live: an alarm that
        flashes under the hand during a drag is the annoyance Christian asked
        me to avoid.
        """
        if not self.blink_lit():
            return
        rect = self.plot_rect()
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 0.5))
        p.setFont(font)
        metrics = QFontMetrics(font)
        for trace in self.traces:
            if not trace.missing:
                continue
            y = self.y_to_px(trace.scan.offset, rect)
            if not (rect.top() - 10 <= y <= rect.bottom() + 10):
                continue
            text = "NO {}".format(trace.missing.upper())
            width = metrics.horizontalAdvance(text) + 12
            box = QRect(int(rect.left()) + 8, int(y) - 9, width, 18)
            p.setBrush(_ALARM)
            p.setPen(QPen(_ALARM.lighter(140), 1))
            p.drawRoundedRect(box, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.drawText(box, Qt.AlignCenter, text)
            p.setBrush(Qt.NoBrush)

    # ----------------------------------------------------------------- paper
    def darken_for_paper(self):
        """Trace colours as they would print, parallel to `traces`."""
        return [for_light(t.colour) for t in self.traces]


# ------------------------------------------------------------------ helpers
#: The analysis models whose result fields are decoded (see TRI-FORMAT.md in
#: ACH-DSC-Plotter). Everything else in a file is kept and reported, but it
#: has no number to draw, so it is not drawn.
DECODED_MODELS = ("Onset point", "Endset point", "Peak Integration",
                  "Glass transition")


def _is_decoded(entry):
    kind = str(entry.get("Model", ""))
    return any(name in kind for name in DECODED_MODELS)


def _free_slot(box, taken, bounds, step=15, tries=6):
    """`box`, moved up in steps until it clears `taken`, or left where it was.

    Deliberately simple: a handful of nudges, always upward, and it gives up
    rather than searching. A label that has moved a long way from the thing it
    labels is worse than two labels that touch.
    """
    for _ in range(tries):
        if all(not box.intersects(other) for other in taken):
            break
        box = box.translated(0, -step)
    if box.top() < bounds.top():
        box = box.translated(0, bounds.top() - box.top())
    return box


def trace_colour(trace):
    """A trace's colour as the current theme draws it.

    The palette is chosen for a dark ground, so on white every trace is
    brought down to `PAPER_LUMA`. Resolved HERE, at paint time, rather than
    stored on the Trace: the theme can change between two paints and the
    colour the user picked must not be overwritten by a rendering choice.
    """
    return for_light(trace.colour) if THEME == THEME_LIGHT else QColor(trace.colour)


def _analysis_marker(entry):
    """`(label, x)` for a stored analysis, or `(label, None)`.

    Only the models whose result fields are decoded get a number; the rest
    are drawn at their cursor, which is still where the user put them.
    """
    kind = str(entry.get("Model", ""))
    if "Glass" in kind:
        # The midpoint is what a glass transition is quoted as, and the one
        # the reader reproduces exactly from TRIOS's own stored points (see
        # TRI-FORMAT.md section 5).
        value = model.number(entry.get("Midpoint"))
        if value is not None:
            return ("Tg {:.1f}".format(value), value)
    if "Onset" in kind or "Endset" in kind:
        value = model.number(entry.get("Onset x") or entry.get("Endset x"))
        if value is not None:
            return ("{} {:.1f}".format(kind.split()[0], value), value)
    if "Integration" in kind:
        value = model.number(entry.get("Peak temperature"))
        enthalpy = model.number(entry.get("Enthalpy (normalized)"))
        if value is not None:
            text = ("{:.1f} J/g".format(enthalpy) if enthalpy is not None
                    else "peak")
            return (text, value)
    value = model.number(entry.get("Cursor x") or entry.get("Onset cursor x"))
    return (kind, value)


def _columns(cx, top, bottom):
    """One point where a column is flat, two where it is not.

    Built with `repeat` and a cumulative index rather than a loop: a Python
    loop over a thousand columns costs more than the points it saves.
    """
    spiky = (bottom - top) > 0.5
    counts = np.where(spiky, 2, 1)
    ends = np.cumsum(counts)
    heads = ends - counts
    px = np.repeat(cx, counts)
    py = np.empty(int(ends[-1]), dtype=float)
    py[heads] = top
    py[ends[spiky] - 1] = bottom[spiky]
    return px, py


def _polyline(px, py):
    poly = QPolygonF()
    for a, b in zip(np.asarray(px).tolist(), np.asarray(py).tolist()):
        poly.append(QPointF(a, b))
    return poly



#: What a label may contain, spelled the way somebody used to LaTeX would
#: write it. Only these, and only because they are what a DSC figure needs.
MARKUP_SYMBOLS = {
    "\\Delta": "\u0394", "\\delta": "\u03b4", "\\alpha": "\u03b1",
    "\\beta": "\u03b2", "\\gamma": "\u03b3", "\\Gamma": "\u0393",
    "\\epsilon": "\u03b5", "\\varepsilon": "\u03b5", "\\zeta": "\u03b6",
    "\\eta": "\u03b7", "\\theta": "\u03b8", "\\Theta": "\u0398",
    "\\kappa": "\u03ba", "\\lambda": "\u03bb", "\\Lambda": "\u039b",
    "\\mu": "\u03bc", "\\nu": "\u03bd", "\\xi": "\u03be", "\\pi": "\u03c0",
    "\\Pi": "\u03a0", "\\rho": "\u03c1", "\\sigma": "\u03c3",
    "\\Sigma": "\u03a3", "\\tau": "\u03c4", "\\phi": "\u03c6",
    "\\varphi": "\u03c6", "\\Phi": "\u03a6", "\\chi": "\u03c7",
    "\\psi": "\u03c8", "\\Psi": "\u03a8", "\\omega": "\u03c9",
    "\\Omega": "\u03a9", "\\degree": "\u00b0", "\\circ": "\u00b0",
    "\\pm": "\u00b1", "\\mp": "\u2213", "\\times": "\u00d7",
    "\\cdot": "\u00b7", "\\infty": "\u221e", "\\approx": "\u2248",
    "\\sim": "\u223c", "\\leq": "\u2264", "\\le": "\u2264",
    "\\geq": "\u2265", "\\ge": "\u2265", "\\neq": "\u2260",
    "\\rightarrow": "\u2192", "\\to": "\u2192", "\\leftarrow": "\u2190",
    "\\uparrow": "\u2191", "\\downarrow": "\u2193", "\\AA": "\u00c5",
    "\\%": "%", "\\$": "$", "\\{": "{", "\\}": "}", "\\_": "_", "\\#": "#",
    "\\&": "&",
}

#: LaTeX's spaces: math mode ignores typed spaces, so these are how a
#: caption like the template's `$T \quad / \quad \mathrm{degC}$` is spaced.
MATH_SPACES = {"\\qquad": "\u2003\u2003", "\\quad": "\u2003",
               "\\,": "\u2009", "\\:": "\u2005", "\\;": "\u2005",
               "\\ ": " ", "\\!": ""}

_COMMAND = re.compile(r"\\([A-Za-z]+|.)")
#: Script levels a run can be on.
SUB, SUP = "sub", "sup"


def _symbol(text, index):
    """`(glyph, next index)` for the backslash command at `text[index]`, or
    None when it is not one this knows."""
    for name, glyph in MATH_SPACES.items():
        if text.startswith(name, index):
            return glyph, index + len(name)
    match = _COMMAND.match(text, index)
    if match and match.group(0) in MARKUP_SYMBOLS:
        return MARKUP_SYMBOLS[match.group(0)], match.end()
    return None


def _group(text, index):
    """The inside of the `{...}` at `text[index]` (braces nest), and the
    index after it."""
    depth = 0
    for end in range(index, len(text)):
        if text[end] == "{" and (end == 0 or text[end - 1] != "\\"):
            depth += 1
        elif text[end] == "}" and text[end - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[index + 1:end], end + 1
    return text[index + 1:], len(text)


def _script_arg(text, index):
    """What a `_` or `^` applies to: a `{group}`, one command, or one
    character."""
    if index >= len(text):
        return "", index
    if text[index] == "{":
        return _group(text, index)
    if text[index] == "\\":
        match = _COMMAND.match(text, index)
        return match.group(0), match.end()
    return text[index], index + 1


def _math(text, runs, script=False, upright=False, spaces=False):
    r"""LaTeX math mode: letters italic, digits and signs upright, spaces
    ignored, `_` and `^` scripts, `\mathrm{}` / `\text{}` upright, the
    Greek letters and symbols of `MARKUP_SYMBOLS`."""
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace() and not spaces:
            index += 1
            continue
        if char in "_^":
            argument, index = _script_arg(text, index + 1)
            _math(argument, runs, SUB if char == "_" else SUP, upright,
                  spaces)
            continue
        if char == "{":
            inner, index = _group(text, index)
            _math(inner, runs, script, upright, spaces)
            continue
        if char == "}":
            index += 1
            continue
        if char == "\\":
            match = re.match(r"\\(mathrm|mathit|mathbf|mathsf|text|textrm|"
                             r"textit|rm)\s*", text[index:])
            if match and text[index + match.end():index + match.end() + 1] \
                    == "{":
                inner, index = _group(text, index + match.end())
                kind = match.group(1)
                _math(inner, runs, script,
                      upright=kind not in ("mathit", "textit"),
                      spaces=kind.startswith("text"))
                continue
            found = _symbol(text, index)
            if found is not None:
                runs.append((found[0], False, script))
                index = found[1]
                continue
        runs.append((char, char.isalpha() and not upright, script))
        index += 1


def _unescaped(text, char, start):
    """The index of the next `char` in `text` not preceded by a backslash."""
    index = text.find(char, start)
    while index > 0 and text[index - 1] == "\\":
        index = text.find(char, index + 1)
    return index


def markup_runs(text):
    r"""`[(text, italic, script), ...]` for a label; `script` is False,
    `SUB` or `SUP`.

    The figure's own markup, which a DSC figure actually needs:

    * `*T*` sets a quantity symbol cursive;
    * `_{g}` lowers a subscript and `^{2}` raises a superscript;
    * a backslash name writes a Greek letter or a symbol (`\Delta`).

    And LaTeX between dollars, as matplotlib's mathtext takes it, so a
    label written for the plotter reads the same here: `$T_{g}$`,
    `(Hbc)$_{1.00}$`, `$T \quad / \quad \mathrm{degC}$` (Christian, round
    18). Rich text would drag a QTextDocument into a painted plot for this;
    a tokeniser and three flags do it.
    """
    text = str(text)
    runs, italic, index, plain = [], False, 0, []

    def flush():
        if plain:
            runs.append(("".join(plain), italic, False))
            del plain[:]

    while index < len(text):
        char = text[index]
        if char == "$":
            close = _unescaped(text, "$", index + 1)
            if close > index:
                flush()
                _math(text[index + 1:close], runs)
                index = close + 1
                continue
        if char == "\\":
            found = _symbol(text, index)
            if found is not None:
                plain.append(found[0])
                index = found[1]
                continue
        if char == "*":
            flush()
            italic = not italic
            index += 1
            continue
        if char in "_^" and index + 1 < len(text):
            flush()
            argument, index = _script_arg(text, index + 1)
            for name, glyph in sorted(MARKUP_SYMBOLS.items(),
                                      key=lambda item: -len(item[0])):
                argument = argument.replace(name, glyph)
            runs.append((argument, italic, SUB if char == "_" else SUP))
            continue
        plain.append(char)
        index += 1
    flush()
    merged = []
    for run in runs:
        if not run[0]:
            continue
        if merged and merged[-1][1:] == run[1:]:
            merged[-1] = (merged[-1][0] + run[0],) + run[1:]
        else:
            merged.append(run)
    return merged


def _run_font(font, italic, script):
    styled = QFont(font)
    styled.setItalic(italic)
    if script:
        styled.setPointSizeF(max(4.0, font.pointSizeF() * 0.72))
    return styled


def markup_size(text, font):
    """`(width, height)` the drawn text will occupy."""
    width = 0
    height = QFontMetrics(font).height()
    for part, italic, subscript in markup_runs(text):
        width += QFontMetrics(_run_font(font, italic, subscript)) \
            .horizontalAdvance(part)
    return width, height


def draw_markup(p, box, text, font, colour):
    """Draw text centred in `box`, honouring the markup."""
    width, _height = markup_size(text, font)
    x = box.center().x() - width / 2.0
    metrics = QFontMetrics(font)
    baseline = box.center().y() + metrics.ascent() / 2.0 - 1
    shift = {SUB: metrics.height() * 0.18, SUP: -metrics.ascent() * 0.38}
    p.setPen(colour)
    for part, italic, script in markup_runs(text):
        styled = _run_font(font, italic, script)
        p.setFont(styled)
        p.drawText(QPointF(x, baseline + shift.get(script, 0.0)), part)
        x += QFontMetrics(styled).horizontalAdvance(part)
    p.setFont(font)


def _nice_step(span, target=8):
    raw = span / float(target)
    power = 10.0 ** math.floor(math.log10(max(raw, 1e-12)))
    for mult in (1, 2, 5, 10):
        if raw <= mult * power:
            return mult * power
    return 10.0 * power


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _chord(xs, ys):
    """The straight line from the first point to the last, at every x.

    Not `np.interp`, which needs x to INCREASE and silently returns nonsense
    for a cooling scan, whose temperature runs the other way.
    """
    span = float(xs[-1] - xs[0])
    if abs(span) < 1e-12:
        return np.full(len(ys), float(ys[0]))
    return ys[0] + (ys[-1] - ys[0]) * (xs - xs[0]) / span


def _rect_distance(box, point):
    """Pixels from `point` to the nearest edge of `box`; 0 inside it."""
    dx = max(box.left() - point.x(), 0.0, point.x() - box.right())
    dy = max(box.top() - point.y(), 0.0, point.y() - box.bottom())
    return math.hypot(dx, dy)


def _close(a, b, tol=1e-9):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def clip_svg(path, rects):
    """Wrap each fenced stretch of an SVG in a clipPath (see
    `PlotWidget._clip_mark`). The writer puts every change of pen or brush
    in a sibling `<g>`, so the stretch between the two marks is a run of
    whole groups, and a `<g clip-path>` around it is balanced."""
    if not rects:
        return False
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    defs = []
    for number, box in enumerate(rects):
        name = "dscpanel-axes-{}".format(number)
        opening = text.find('fill="{}"'.format(PlotWidget.CLIP_OPEN))
        closing = text.find('fill="{}"'.format(PlotWidget.CLIP_CLOSE),
                            opening + 1)
        if opening < 0 or closing < 0:
            break
        open_group = text.rfind("<g", 0, opening)
        open_end = text.find("</g>", opening)
        close_group = text.rfind("<g", 0, closing)
        close_end = text.find("</g>", closing)
        if min(open_group, open_end, close_group, close_end) < 0:
            break
        text = (text[:open_group]
                + '<g clip-path="url(#{})">'.format(name)
                + text[open_end + len("</g>"):close_group]
                + "</g>"
                + text[close_end + len("</g>"):])
        defs.append('<clipPath id="{}"><rect x="{:.4f}" y="{:.4f}" '
                    'width="{:.4f}" height="{:.4f}"/></clipPath>'.format(
                        name, box.left(), box.top(), box.width(),
                        box.height()))
    if not defs:
        return False
    head = text.find(">", text.find("<svg")) + 1
    text = text[:head] + "\n<defs>" + "".join(defs) + "</defs>" + text[head:]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def _clip_segment(a, b, rect):
    """The part of the segment a-b inside `rect`, or None (Liang-Barsky)."""
    x0, y0, x1, y1 = a.x(), a.y(), b.x(), b.y()
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for p_, q_ in ((-dx, x0 - rect.left()), (dx, rect.right() - x0),
                   (-dy, y0 - rect.top()), (dy, rect.bottom() - y0)):
        if p_ == 0:
            if q_ < 0:
                return None
            continue
        t = q_ / p_
        if p_ < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return None
    return (QPointF(x0 + low * dx, y0 + low * dy),
            QPointF(x0 + high * dx, y0 + high * dy))

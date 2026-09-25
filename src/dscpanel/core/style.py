"""The house style: what a size is when nobody has chosen one.

Christian asked for defaults that persist between sessions and can still be
overridden for one figure. That is three places a value can come from, and a
fourth that is written here, looked up most specific first:

1. **the object.** A size typed into one analysis's own settings is a
   decision about that analysis, and it wins over everything.
2. **the figure** (`Document.style`, a `FigureStyle`). Saved in the session
   file, so "every analysis label in THIS figure at 7 pt" travels with the
   figure and does not touch any other.
3. **the user's defaults**: `preferences.json` beside the registration
   manifest (`branding.app_dir()`). Kept on this computer, shared by every
   figure, and what a new figure starts from.
4. **the built-in value** in `SETTINGS` below, which is what the program
   shipped with and what "reset" goes back to.

None at levels 1 and 2 means "not chosen here, ask the next level". So an
object attribute such as `Analysis.label_size` is None until somebody sets
it, and nothing may read it directly: every read goes through `value`, or a
figure made under one set of defaults will quietly ignore the next.

UI-free and Qt-free: the preferences are a JSON file, not QSettings, so this
module is testable with a temporary path and nothing else.
"""

import json
import os

from .. import branding

#: How an analysis label sits against the arrow that points at its feature,
#: which is the DSC_Plotter template's `flush`: `left` puts the text's left
#: edge on the arrow, so the label reads to the right of it; `right` the
#: mirror image; `center` hangs it centred over the arrow.
FLUSH_LEFT = "left"
FLUSH_CENTER = "center"
FLUSH_RIGHT = "right"
FLUSHES = (FLUSH_LEFT, FLUSH_CENTER, FLUSH_RIGHT)
#: "By analysis kind": what the template itself chooses per artist - tangent
#: constructions (onset, endset, glass transition) flush left, everything
#: else centred.
FLUSH_AUTO = "auto"

#: Words for the choices, for the dialogs.
FLUSH_TITLES = {
    FLUSH_AUTO: "by analysis kind",
    FLUSH_LEFT: "left",
    FLUSH_CENTER: "centred",
    FLUSH_RIGHT: "right",
}


class Setting(object):
    """One row of the house style: a name, a built-in value and its limits."""

    def __init__(self, key, title, default, kind="size", low=None, high=None,
                 step=0.5, decimals=1, choices=(), note="", figure=True,
                 suffix=""):
        self.key = key
        #: Shown after the number in a settings field (" px").
        self.suffix = suffix
        self.title = title
        self.default = default
        #: True for the figure's style (a figure may override it and saves
        #: it); False for how the program HANDLES, which is the user's alone
        #: and has nothing to do with any one figure - the pick distance.
        self.figure = figure
        #: "size" is a number; "choice" is one of `choices`.
        self.kind = kind
        self.low = low
        self.high = high
        self.step = step
        self.decimals = decimals
        self.choices = tuple(choices)
        self.note = note

    def clean(self, value):
        """`value` if it is a legal one for this setting, else None.

        Used on everything read from a file, so a hand-edited preferences file
        or a session from a later version degrades to "not chosen" rather than
        to an exception in a paint call.
        """
        if value is None:
            return None
        if self.kind == "choice":
            return value if value in self.choices else None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number:                        # NaN
            return None
        if self.low is not None:
            number = max(float(self.low), number)
        if self.high is not None:
            number = min(float(self.high), number)
        return number


#: Every value that falls back on the house style, in the order the settings
#: page lists them. The built-in numbers are the ones the objects carried
#: before there was a house style, so nothing changes until it is changed.
SETTINGS = (
    Setting("analysis_size", "Analysis labels", 9.0, low=5.0, high=40.0,
            note="the text of an onset, an integral, a Tg"),
    Setting("analysis_flush", "Analysis label alignment", FLUSH_AUTO,
            kind="choice", choices=(FLUSH_AUTO,) + FLUSHES,
            note="which edge of the label sits on its arrow"),
    Setting("caption_size", "Axis captions", 10.0, low=5.0, high=40.0,
            note="T / degC and Heat Flow / W/g"),
    Setting("tick_size", "Axis numbers", 8.0, low=4.0, high=30.0),
    Setting("legend_size", "Legend text", 9.0, low=5.0, high=30.0),
    Setting("label_size", "Labels", 10.0, low=5.0, high=48.0,
            note="captions placed on the figure (Ctrl+T)"),
    Setting("line_width", "Curve width", 1.0, low=0.2, high=8.0, step=0.2,
            decimals=2),
    # How close a press must be to a curve or a label to act on it (mark an
    # interval, move the label) rather than start a box select. Christian
    # found 60 px grabbed a neighbouring scan where curves run close; 14 is
    # the old fixed value, and the hand that uses it decides.
    Setting("pick_radius", "Pick distance", 14.0, low=2.0, high=60.0,
            step=1.0, decimals=0, figure=False, suffix=" px",
            note="how close, in pixels, a press must be to a curve or a "
                 "label to act on it; further away, a drag draws a box"),
)

BY_KEY = dict((setting.key, setting) for setting in SETTINGS)

#: The ones a figure can override and a session saves.
FIGURE_SETTINGS = tuple(s for s in SETTINGS if s.figure)

#: Which object attribute falls back on which setting, by `Obj.kind`.
FIELDS = {
    ("analysis", "label_size"): "analysis_size",
    ("analysis", "flush"): "analysis_flush",
    ("axis", "label_size"): "caption_size",
    ("axis", "tick_size"): "tick_size",
    ("legend", "size"): "legend_size",
    ("label", "size"): "label_size",
    ("scan", "line_width"): "line_width",
}


class FigureStyle(object):
    """Level 2: one figure's own choices, every one None until made.

    Plain attributes rather than a dict, so the undo stack's `SetProps` can
    record a change to it exactly as it records a change to a scan.
    """

    kind = "style"

    def __init__(self):
        for setting in FIGURE_SETTINGS:
            setattr(self, setting.key, None)

    def chosen(self):
        """`{key: value}` for what this figure has set, and nothing else."""
        return dict((s.key, getattr(self, s.key)) for s in FIGURE_SETTINGS
                    if getattr(self, s.key) is not None)


# ----------------------------------------------------------- level 3: user
#: The user's defaults, as loaded. Empty means "the built-in values".
_preferences = {}

#: Where the preferences live. Tests point this at a temporary file so that
#: running the suite never touches the defaults of whoever runs it.
PATH_OVERRIDE = None


def preferences_path():
    if PATH_OVERRIDE:
        return str(PATH_OVERRIDE)
    return os.path.join(branding.app_dir(), "preferences.json")


def load_preferences(path=None):
    """Read the user's defaults. A missing or unreadable file means none.

    Unreadable is not an error worth stopping the program for: the file is a
    convenience, and the built-in values are always a correct figure.
    """
    _preferences.clear()
    path = path or preferences_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return dict(_preferences)
    if not isinstance(stored, dict):
        return dict(_preferences)
    for section in ("style", "handling"):
        entries = stored.get(section)
        if not isinstance(entries, dict):
            continue
        for key, raw in entries.items():
            setting = BY_KEY.get(key)
            cleaned = setting.clean(raw) if setting is not None else None
            if cleaned is not None:
                _preferences[key] = cleaned
    return dict(_preferences)


def save_preferences(path=None):
    """Write the user's defaults. Only what differs from the built-in.

    Two sections: `style` is what a figure can also override, `handling` is
    how the program responds to the hand (the pick distance)."""
    path = path or preferences_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    changed = dict((key, value) for key, value in _preferences.items()
                   if value != BY_KEY[key].default)
    state = {"format": "preferences", "version": 1,
             "style": dict((k, v) for k, v in changed.items()
                           if BY_KEY[k].figure),
             "handling": dict((k, v) for k, v in changed.items()
                              if not BY_KEY[k].figure)}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    return path


def preferences():
    """A copy of the user's defaults, for a dialog's Cancel."""
    return dict(_preferences)


def restore_preferences(saved):
    _preferences.clear()
    _preferences.update(saved or {})


def builtin(key):
    return BY_KEY[key].default


def preference(key):
    """Level 3 and below: the user's default, else the built-in value."""
    value = _preferences.get(key)
    return builtin(key) if value is None else value


def set_preference(key, value):
    """Change a default. None (or the built-in value) forgets it."""
    setting = BY_KEY[key]
    value = setting.clean(value)
    if value is None or value == setting.default:
        _preferences.pop(key, None)
    else:
        _preferences[key] = value


# ------------------------------------------------------------- resolution
def figure_value(doc, key):
    """Level 2 and below: what an object that chose nothing gets."""
    own = getattr(getattr(doc, "style", None), key, None)
    return preference(key) if own is None else own


def key_for(obj, attr):
    return FIELDS.get((getattr(obj, "kind", ""), attr))


def value(doc, obj, attr):
    """The value `obj.attr` is DRAWN with: its own, or the figure's, or the
    user's default, or the built-in one.

    Every read of a styled attribute goes through here. `doc` may be None
    (a dialog opened outside a window), which skips the figure level.
    """
    own = getattr(obj, attr, None)
    if own is not None:
        return own
    key = key_for(obj, attr)
    if key is None:
        return None
    return figure_value(doc, key)


def inherited(doc, obj, attr):
    """What `obj.attr` would be if it chose nothing - for "use the default"."""
    key = key_for(obj, attr)
    return figure_value(doc, key) if key is not None else None


def flush_for(analysis, flush):
    """A flush that is a side, never `auto`, for this analysis.

    `auto` is the template's own choice: `add_tangent` and
    `add_glass_transition` flush left, `add_integral` and `mark_spot` centre.
    """
    if flush in FLUSHES:
        return flush
    name = str(getattr(analysis, "model_name", ""))
    if "Onset" in name or "Endset" in name or "Glass" in name:
        return FLUSH_LEFT
    return FLUSH_CENTER

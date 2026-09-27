"""The log: what the program did, and every error, in a file.

Started from its shortcut the program has no console, so an error had
nowhere to go - and PySide6 turns an exception inside a Qt slot into the
end of the process unless an excepthook takes it. `install` fixes both: the
hook writes the traceback here and the program carries on (Christian's work
is still open), and `faulthandler` writes the stack of a hard crash - one in
Qt itself - into a file of its own beside it.

The files live with the preferences (`branding.app_dir()`); Help > Open the
log folder shows them. Rotating: a megabyte, two old ones kept.

UI-free. `on_error` is how the window hears about an error it should show.
"""

import faulthandler
import logging
import logging.handlers
import os
import platform
import sys
import traceback

from .. import branding

#: The program's logger. Modules log through `logging.getLogger(NAME)`;
#: without `install` (tests, tools) nothing is written anywhere.
NAME = "dscpanel"
LOGGER = logging.getLogger(NAME)

#: Called with a one-line summary after an error was logged, or None.
on_error = None

_crash_file = None


def path():
    """The log file."""
    return os.path.join(branding.app_dir(), branding.EXE_NAME + ".log")


def install(target=None):
    """Log to `target` (the default file), catch every unhandled error and
    every hard crash. Returns the file's path; never raises - a program
    that cannot write its log should still start."""
    global _crash_file
    target = target or path()
    try:
        folder = os.path.dirname(target)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=1000000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        _crash_file = open(target + ".crash", "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except OSError:
        pass
    sys.excepthook = _hook
    from .. import __version__
    LOGGER.info("%s %s started: Python %s on %s", branding.APP_NAME,
                __version__, platform.python_version(), platform.platform())
    return target


def _hook(kind, value, tb):
    """Every unhandled error: its traceback into the log, a line to the
    window. The program carries on."""
    text = "".join(traceback.format_exception(kind, value, tb))
    LOGGER.error("Unhandled %s: %s\n%s", kind.__name__, value, text)
    if sys.__stderr__ is not None:
        try:
            sys.__stderr__.write(text)
        except Exception:
            pass
    if on_error is not None:
        try:
            on_error("{}: {}".format(kind.__name__, value))
        except Exception:
            pass

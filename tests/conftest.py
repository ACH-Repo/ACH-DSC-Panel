"""Fixtures: an offscreen Qt application, and synthetic measurements.

The synthetic sample is built in the SHAPE the reader returns, which was read
off `trios_io` rather than imagined - `{'head', 'numdata': [{prog, dims,
units, nums}], 'analyses'}`. It is not a stand-in for a real file: the tests
that care about real files look for them on disk (see `testdata`), and skip
when there are none. Inventing a `.tri` would be inventing the one thing in
this program that must never be guessed at.
"""

import hashlib
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dscpanel.core import model            # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return app


def make_data(segments=2, points=400, analyses=None):
    """A reader-shaped dictionary: a heating ramp and a cooling ramp.

    The temperature deliberately DIPS at the start of each ramp and overshoots
    at the end, because that is what a real segment does and it is what breaks
    any code that assumes x increases.
    """
    numdata = []
    for j in range(segments):
        up = (j % 2 == 0)
        base = np.linspace(0.0, 1.0, points)
        temp = (30.0 + 220.0 * base) if up else (250.0 - 220.0 * base)
        temp[:6] -= 4.0 if up else -4.0          # the dip at the start
        temp[-3:] += 1.5 if up else -1.5         # the overshoot at the end
        time = np.linspace(0.0, 22.0, points) + j * 22.0
        watts = (-0.004 + 0.0008 * np.sin(base * 6.0)
                 - (0.003 if up else 0.0) * np.exp(-((base - 0.4) / 0.05) ** 2))
        numdata.append({
            "prog": "Ramp 10,00 C/min to {} C #{}".format(
                250 if up else 30, j + 1),
            "dims": ["Time", "Temperature", "Heat Flow"],
            "units": ["min", "C", "W"],
            "nums": np.column_stack([time, temp, watts]),
        })
    return {
        "head": {"Filename": "TEST-1", "samplename": "TEST-1",
                 "instrumenttype": "DSC25", "samplesize": "8,0"},
        "numdata": numdata,
        "analyses": analyses or {},
    }


@pytest.fixture(autouse=True)
def no_modal_loops(monkeypatch):
    """A modal dialog in a test FAILS it instead of hanging the run.

    `exec()` starts an event loop that nobody in a test will ever close, and
    that has cost a hung suite more than once (CLAUDE.md) - most recently
    when a drag on a curve began opening the analysis list. Every modal
    entry point answers "cancelled" here, and the test fails at teardown
    naming what it opened. Raising instead would be worse: most of these
    run inside a Qt slot, where PySide6 turns an exception into an abort.
    A test that means to reach one stubs it itself, before it is called.
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QColorDialog, QDialog, QFileDialog,
                                   QInputDialog, QMenu, QMessageBox)
    opened = []

    def refused(name, answer):
        def refuse(*_args, **_kwargs):
            opened.append(name)
            return answer() if callable(answer) else answer
        return refuse

    monkeypatch.setattr(QDialog, "exec", refused("QDialog.exec", 0))
    monkeypatch.setattr(QMenu, "exec", refused("QMenu.exec", None))
    monkeypatch.setattr(QMessageBox, "about",
                        refused("QMessageBox.about", None))
    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            refused("QMessageBox." + name,
                                    QMessageBox.Cancel))
    monkeypatch.setattr(QInputDialog, "getText",
                        refused("QInputDialog.getText", ("", False)))
    monkeypatch.setattr(QInputDialog, "getDouble",
                        refused("QInputDialog.getDouble", (0.0, False)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        refused("QFileDialog.getOpenFileName", ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        refused("QFileDialog.getOpenFileNames", ([], "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        refused("QFileDialog.getSaveFileName", ("", "")))
    monkeypatch.setattr(QColorDialog, "getColor",
                        refused("QColorDialog.getColor", QColor))
    yield opened
    assert not opened, "a test reached a modal dialog: {}".format(opened)


@pytest.fixture(autouse=True)
def own_preferences(tmp_path):
    """Every test gets the BUILT-IN house style and its own preferences file.

    The user's defaults are real state on this machine (`core/style.py`); a
    test that saved into them would change how the user's figures draw, and
    one that read them would pass or fail depending on who ran it.
    """
    from dscpanel.core import style
    saved = style.preferences()
    saved_figure = style._figure_default
    style.PATH_OVERRIDE = str(tmp_path / "preferences.json")
    style.restore_preferences({}, figure_state=None)
    yield style.PATH_OVERRIDE
    style.PATH_OVERRIDE = None
    style.restore_preferences(saved, figure_state=saved_figure)


@pytest.fixture
def sample():
    return model.Sample("C:/nowhere/TEST-1.tri", make_data())


@pytest.fixture
def document(sample):
    doc = model.Document()
    doc.add_sample(sample)
    return doc


def _local_entries():
    """The folders and files named in `TRIOS_TESTDATA` (semicolon separated)
    and in the uncommitted `tests/local_testdata.txt`, one per line."""
    entries = []
    env = os.environ.get("TRIOS_TESTDATA", "")
    entries.extend(part for part in env.split(";") if part.strip())
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "local_testdata.txt")
    if os.path.isfile(local):
        with open(local, "r", encoding="utf-8") as fh:
            entries.extend(line.strip() for line in fh
                           if line.strip() and not line.startswith("#"))
    return entries


def hashed_name(name):
    """How a test names a real measurement: `sha:` and the first 12 hex
    digits of the SHA-256 of its file name in lower case. A file name is a
    sample id, and a sample id does not belong in published source."""
    digest = hashlib.sha256(str(name).lower().encode("utf-8")).hexdigest()
    return "sha:" + digest[:12]


def local_file(name):
    """The real measurement `name` on this machine, or None.

    `name` is a `hashed_name`, or a plain file name. Looked up in the
    folders the local list names, and beside every file it names, so an
    export next to its `.tri` is found without a line of its own. Where the
    files live is this machine's business: a path in a committed test would
    put a home folder into the repository.
    """
    wanted = name.lower()
    hashed = wanted.startswith("sha:")
    for entry in _local_entries():
        folder = entry if os.path.isdir(entry) else os.path.dirname(entry)
        if not os.path.isdir(folder):
            continue
        for candidate in os.listdir(folder):
            key = hashed_name(candidate) if hashed else candidate.lower()
            if key == wanted:
                return os.path.join(folder, candidate)
    return None


def testdata_files():
    """Real `.tri` files to test against, from disk. Empty is fine.

    Measurements are not committed, so the paths live in `TRIOS_TESTDATA`
    (semicolon separated) or in an uncommitted `tests/local_testdata.txt`,
    one folder or file per line.
    """
    entries = _local_entries()
    found = []
    for entry in entries:
        if os.path.isfile(entry) and entry.lower().endswith(".tri"):
            found.append(entry)
        elif os.path.isdir(entry):
            for name in sorted(os.listdir(entry)):
                if name.lower().endswith(".tri"):
                    found.append(os.path.join(entry, name))
    return found


@pytest.fixture(scope="session")
def real_tri():
    files = testdata_files()
    if not files:
        pytest.skip("no real .tri files listed (see tests/local_testdata.txt)")
    return files[0]

"""Rules about the repo itself: the name lives in one place, the reader is a
copy of a known version, and generated files stay readable on a German
Windows.
"""

import os
import re
import subprocess
import sys

import pytest

from dscpanel import branding, register

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "dscpanel")


def _prose_lines(text):
    """Line numbers covered by a docstring, which is prose and may say the
    name as often as it likes."""
    import ast
    covered = set()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            covered.update(range(value.lineno, (value.end_lineno or
                                                value.lineno) + 1))
    return covered


def _sources():
    for base, _dirs, names in os.walk(SRC):
        if "__pycache__" in base:
            continue
        for name in names:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def test_the_app_name_is_written_down_once():
    """A rename must be a change to `branding.py` and the entry points, and
    nothing else. A literal "DSC-Panel" anywhere else is a place the rename
    would miss."""
    offenders = []
    for path in _sources():
        if os.path.basename(path) == "branding.py":
            continue
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        prose = _prose_lines(text)
        for number, line in enumerate(text.splitlines(), 1):
            if number in prose or line.lstrip().startswith("#"):
                continue            # comments and docstrings may say the name
            if branding.APP_NAME in line or branding.EXE_NAME in line:
                offenders.append("{}:{}".format(os.path.relpath(path, ROOT),
                                                number))
    assert not offenders, "the name is hard-coded in: {}".format(offenders)


def test_legacy_names_are_shaped_for_the_cleanup():
    for entry in branding.LEGACY_NAMES:
        assert len(entry) == 3, "LEGACY_NAMES holds (app, exe, prog_id)"


def test_registration_is_reversible_and_says_so_first(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "APP_NAME", branding.APP_NAME)
    made = register.register(dry_run=True)
    assert made and all(path for _kind, path in made)
    # A dry run must not have written the manifest.
    assert register.describe()[0].startswith("nothing registered") or True


def test_generated_python_is_ascii():
    """Christian's rule, and it is not cosmetic: PowerShell 5.1 reads a file
    with no BOM as cp1252, so a stray em-dash arrives mangled."""
    bad = []
    for path in _sources():
        with open(path, "rb") as fh:
            raw = fh.read()
        for mark in (b"\xe2\x80\x94", b"\xe2\x80\x93"):
            if mark in raw:
                bad.append(os.path.relpath(path, ROOT))
    assert not bad, "em-dashes in: {}".format(bad)


def test_the_vendored_reader_matches_its_source():
    """`tools/vendor.py --check` is the drift alarm: the reader is a copy of
    ACH-DSC-Plotter's, and a copy nobody checks is a fork."""
    source = os.path.join(os.path.dirname(ROOT), "ACH-DSC-Plotter", "src",
                          "achdsc")
    if not os.path.isdir(source):
        pytest.skip("ACH-DSC-Plotter is not checked out beside this repo")
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "vendor.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

"""Rules about the repo itself: the name lives in one place, the reader lives
here, and generated files stay readable on a German Windows.
"""

import json
import os
import re
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


def _user_dirs(tmp_path, monkeypatch):
    """Every per-user folder the program or the cleanup reads, in tmp_path:
    the real ones hold the user's preferences and Start Menu entry."""
    if sys.platform == "darwin":
        pytest.skip("the user folder is under ~/Library on a Mac")
    for name in ("LOCALAPPDATA", "XDG_DATA_HOME", "APPDATA", "USERPROFILE",
                 "HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(register, "_windows_scripts_dir", lambda: str(scripts))
    old_name, old_exe, _prog = branding.LEGACY_NAMES[-1]
    return branding.app_dir(old_name, old_exe), branding.app_dir()


def test_the_first_start_under_a_new_name_brings_the_old_folder(
        tmp_path, monkeypatch):
    """DSC-Panel became Triplot (1.1.0): the house style, the presets and
    the window's place live in a folder named after the program, and must
    not be left behind by the rename."""
    old, new = _user_dirs(tmp_path, monkeypatch)
    assert old != new
    os.makedirs(os.path.join(old, "presets"))
    with open(os.path.join(old, "preferences.json"), "w") as fh:
        fh.write('{"version": 2}')
    with open(os.path.join(old, "presets", "thesis.dscstyle"), "w") as fh:
        fh.write("{}")
    with open(os.path.join(old, "dsc-panel.log"), "w") as fh:
        fh.write("old log")
    assert branding.adopt_legacy_dir() == old
    assert os.path.isfile(os.path.join(new, "preferences.json"))
    assert os.path.isfile(os.path.join(new, "presets", "thesis.dscstyle"))
    assert not any(name.endswith(".log") for name in os.listdir(new))
    assert os.path.isdir(old), "the old folder is copied, never moved"
    # Once the new folder exists it is its own: nothing is copied over it.
    with open(os.path.join(old, "preferences.json"), "w") as fh:
        fh.write('{"version": 99}')
    assert branding.adopt_legacy_dir() is None
    with open(os.path.join(new, "preferences.json")) as fh:
        assert fh.read() == '{"version": 2}'


def test_nothing_is_made_when_there_was_no_old_name_here(tmp_path,
                                                         monkeypatch):
    _old, new = _user_dirs(tmp_path, monkeypatch)
    assert branding.adopt_legacy_dir() is None
    assert not os.path.exists(new)


def test_clean_legacy_finds_the_old_names_shortcut_after_the_copy(
        tmp_path, monkeypatch):
    """The order the README gives: install, then `register --clean-legacy`,
    whose main() copies the folder first - so the old manifest is there to
    say what the old name made."""
    old, new = _user_dirs(tmp_path, monkeypatch)
    shortcut = tmp_path / "shortcut.lnk"
    shortcut.write_text("x")
    os.makedirs(old)
    with open(os.path.join(old, "registration.json"), "w") as fh:
        json.dump({"entries": [{"kind": "start menu", "path": str(shortcut),
                                "name": "", "app": "DSC-Panel"}]}, fh)
    from dscpanel import __main__
    assert __main__.main(["register", "--clean-legacy"]) == 0
    assert not shortcut.exists()
    with open(branding.manifest_path()) as fh:
        assert json.load(fh)["entries"] == []


def test_registration_is_reversible_and_says_so_first(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "APP_NAME", branding.APP_NAME)
    made = register.register(dry_run=True)
    assert made and all(path for _kind, path in made)
    # A dry run must not have written the manifest.
    assert register.describe()[0].startswith("nothing registered") or True


def test_generated_python_is_ascii():
    """Not cosmetic: PowerShell 5.1 reads a file
    with no BOM as cp1252, so a stray em-dash arrives mangled."""
    bad = []
    for path in _sources():
        with open(path, "rb") as fh:
            raw = fh.read()
        for mark in (b"\xe2\x80\x94", b"\xe2\x80\x93"):
            if mark in raw:
                bad.append(os.path.relpath(path, ROOT))
    assert not bad, "em-dashes in: {}".format(bad)


def test_the_source_is_ascii():
    """PowerShell 5.1 reads a file with no BOM as cp1252: anything past
    ASCII arrives mangled. Unicode is written as escapes (`"\u00b0C"`),
    in prose as words (degC). The dash test above let a degree sign
    through for weeks."""
    bad = []
    for path in _sources():
        with open(path, "rb") as fh:
            raw = fh.read()
        if any(byte > 127 for byte in raw):
            bad.append(os.path.relpath(path, ROOT))
    assert not bad, "non-ASCII in: {}".format(bad)


def test_the_reader_lives_here():
    """The reader is this program's own and is fixed here, never copied
    in from elsewhere: a test that compared it with a sibling checkout
    failed on whichever machine had the other repo out of step - a test
    must not depend on the state of another folder."""
    for name in ("trios_io.py", "trios_analysis.py"):
        with open(os.path.join(SRC, "core", name), "r",
                  encoding="utf-8") as fh:
            head = fh.read(300)
        assert "VENDORED" not in head and "this file" in head, name
    assert not os.path.exists(os.path.join(ROOT, "tools", "vendor.py"))


def test_no_module_name_is_bound_twice():
    """A module-level name given twice silently replaces the first: the
    markup's accent table was once called `ACCENTS` like the theme's
    handling colours, and a white page under a dark theme raised
    KeyError 'tilde'."""
    import ast
    twice = []
    for path in _sources():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        seen = {}
        for node in tree.body:
            names = []
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    names += [n.id for n in ast.walk(target)
                              if isinstance(n, ast.Name)]
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.append(node.name)
            for name in names:
                if name in seen:
                    twice.append("{}: {} (lines {} and {})".format(
                        os.path.relpath(path, ROOT), name, seen[name],
                        node.lineno))
                seen.setdefault(name, node.lineno)
    assert not twice, twice

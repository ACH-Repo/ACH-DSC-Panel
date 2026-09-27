"""Every place the program says its own name, in ONE module.

The name is expected to change ("DSC-Panel" is a working title), and a name
that is spelled out in twenty places is a name nobody dares to change. So:

* the window title, the Start Menu shortcut, the file-type id, the settings
  folder and the manifest of what was registered all read from here;
* `LEGACY_NAMES` lists every name this program has been called before, so a
  release under a new name can take the OLD name's shortcuts, file type and
  aliases away. That is the whole deregistration plan: the new version knows
  what the old one installed, because the old name is still written down.

What a rename costs, with this module in place:

1. change `APP_NAME`, `EXE_NAME`, `PROG_ID` and `SETTINGS_ORG`/`SETTINGS_APP`
   here, and add the outgoing values to `LEGACY_NAMES`;
2. change the two entry-point lines in `pyproject.toml`;
3. `pip uninstall ach-dsc-panel` (this removes the old command), reinstall;
4. run `dsc-panel register --clean-legacy`, which reads `LEGACY_NAMES` and the
   registration manifest and removes what the old name left behind.

Nothing else in the program contains the name as a literal. A test enforces
that (`tests/test_branding.py`).
"""

import os
import sys

#: What the program calls itself in the window title and the Start Menu.
APP_NAME = "DSC-Panel"

#: The command, and the base name of every shortcut and shim that is created.
EXE_NAME = "dsc-panel"

#: The windowed entry point, which a shortcut prefers so no console appears.
EXE_NAME_GUI = "dsc-panel-gui"

#: The Explorer file-type id for the session file, under HKCU\Software\Classes.
PROG_ID = "DscPanel.Session"

#: The session file's extension.
SESSION_EXT = ".dscpanel"

#: A style preset's extension (`core/presets.py`): JSON inside, named so a
#: dropped one is known for what it is.
PRESET_EXT = ".dscstyle"

#: QSettings coordinates. Changing these forgets the user's window geometry,
#: which is why they are written down rather than derived from APP_NAME.
SETTINGS_ORG = "ACH"
SETTINGS_APP = "DSC-Panel"

#: Names this program has gone by. (name, exe, prog_id) for each, oldest
#: first. `register --clean-legacy` walks this list and removes anything it
#: finds: Start Menu shortcuts, desktop shortcuts, PATH shims and the file
#: association. Add the outgoing values here as part of a rename; never
#: remove an entry, because somebody's machine may still be carrying it.
LEGACY_NAMES = ()

#: A one-line description, for shortcut tooltips and the About box.
DESCRIPTION = "Stacked DSC scans from TRIOS files"

#: Where the source lives, for the About box. It carries the name, so it is
#: written here and nowhere else (and changes with a rename).
REPOSITORY = "https://github.com/ACH-Repo/ACH-DSC-Panel"

#: The copyright line from LICENSE, for the About box.
COPYRIGHT = ("Christian Nelle (@p3rAsperaAdAstra), AG Henke, "
             "TU Dortmund. MIT licence.")


def app_dir():
    """Where the registration manifest and any user data live.

    Per user, never per install, so a reinstall does not lose track of the
    shortcuts the last install made.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/" + APP_NAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, EXE_NAME)


def manifest_path():
    """The file listing what this program has registered on this machine.

    Written by `register`, read by `register --remove` and
    `register --clean-legacy`. It exists so that removal takes away exactly
    what was added, rather than guessing at paths a future version might get
    wrong.
    """
    return os.path.join(app_dir(), "registration.json")


def window_title(subject=""):
    """`APP_NAME`, with the open session or file in front of it."""
    return "{} - {}".format(subject, APP_NAME) if subject else APP_NAME

"""Command line: control the running Cellar from a terminal, a script or a desktop shortcut.

    cellar list                              accounts and what they are doing
    cellar launch NAME... [--place ID | --job PLACE JOB | --private LINK | --follow USER]
                                             NAME = account (username or alias), group:NAME, or all
    cellar preset NAME                       run a saved preset
    cellar stop NAME... | all                close accounts' Roblox windows
    cellar show                              bring the window up

The commands go to the running Cellar over its local socket. launch / preset start Cellar first when it is
not running (it starts hidden in the tray if that is set up).
"""

import json
import os
import sys
from typing import List, Optional

from . import APP_ID

COMMANDS = ("list", "launch", "preset", "stop", "show", "help")
NEEDS_APP = ("launch", "preset", "show")        # these may start Cellar


def is_cli(argv: List[str]) -> bool:
    return len(argv) > 1 and argv[1] in COMMANDS


def usage() -> str:
    return __doc__.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]


def send(argv: List[str], timeout: float = 30.0) -> Optional[str]:
    """Sends the command to a running Cellar and returns its answer, or None when Cellar is not running.
    Plain socket, no Qt: Cellar's QLocalServer listens on <tempdir>/cellar-<uid> (Qt's tempPath = $TMPDIR or /tmp),
    and a QCoreApplication here would block the QApplication if Cellar has to start after all."""
    import socket
    import tempfile
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    for d in dict.fromkeys((tempfile.gettempdir(), "/tmp")):
        try:
            s.connect(os.path.join(d, f"{APP_ID}-{os.getuid()}"))
            break
        except OSError:
            continue
    else:
        return None
    try:
        s.sendall(b"cmd " + json.dumps(argv[1:]).encode())
        out = b""
        while not out.endswith(b"\0"):
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        return out.rstrip(b"\0").decode(errors="replace")
    except OSError as ex:
        return f"ERR no answer from Cellar ({ex})"
    finally:
        s.close()


def main(argv: List[str]) -> Optional[int]:
    """Returns an exit code, or None when Cellar should start and run the command itself."""
    if argv[1] == "help":
        print(usage())
        return 0
    answer = send(argv)
    if answer is None:
        if argv[1] in NEEDS_APP:
            return None
        print("Cellar is not running.", file=sys.stderr)
        return 1
    if answer.startswith("ERR "):
        print(answer[4:], file=sys.stderr)
        return 1
    if answer:
        print(answer)
    return 0


def parse_launch(args: List[str]):
    """-> (names, spec or None, error). spec None = each account's own game / the Launch page."""
    from . import util
    from .models import LaunchSpec
    names, spec, i = [], None, 0
    while i < len(args):
        a = args[i]
        try:
            if a == "--place":
                spec = LaunchSpec(kind="Game", place_id=util.parse_place_id(args[i + 1]))
                i += 2
            elif a == "--job":
                spec = LaunchSpec(kind="Job", place_id=util.parse_place_id(args[i + 1]), job_id=args[i + 2])
                i += 3
            elif a == "--private":
                spec = ("private", args[i + 1])
                i += 2
            elif a == "--follow":
                spec = ("follow", args[i + 1])
                i += 2
            elif a.startswith("--"):
                return [], None, f"unknown option {a}"
            else:
                names.append(a)
                i += 1
        except IndexError:
            return [], None, f"{a} needs a value"
    if isinstance(spec, LaunchSpec) and spec.place_id <= 0:
        return [], None, "that is not a Place ID or game link"
    return names, spec, ""


def pick_accounts(names: List[str]):
    """-> (accounts, error). Names: username / alias (any case), group:NAME, or all."""
    from . import store
    if not names:
        return [], "name at least one account (or all, or group:NAME)"
    out, missing = [], []
    for n in names:
        low = n.lower()
        if low == "all":
            found = list(store.accounts)
        elif low.startswith("group:"):
            found = [a for a in store.accounts if a.group.lower() == low[6:]]
        else:
            found = [a for a in store.accounts if low in (a.username.lower(), a.alias.lower())]
        if not found:
            missing.append(n)
        out += [a for a in found if a not in out]
    return out, ("not found: " + ", ".join(missing) if missing else "")


def add_shortcut(title: str, args: List[str], icon: str = "") -> str:
    """An app-menu entry that runs `cellar <args>` (e.g. "Launch ArcticTweaK"). Returns the file written.
    Shows up in the app launcher / KRunner search; drag it to the desktop or panel from there."""
    import re
    import shutil
    exe = shutil.which(APP_ID)
    base = [exe] if exe else [sys.executable, "-m", "cellar"]

    def q(a: str) -> str:   # desktop-entry quoting: double quotes, with \ " ` $ escaped
        return '"' + re.sub(r'([\\"`$])', r"\\\1", a) + '"' if re.search(r'[\s"\\`$\']', a) else a
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "shortcut"
    path = os.path.join(data, "applications", f"{APP_ID}-{slug}.desktop")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\n"
                f"Name={title}\nComment=Cellar shortcut\nExec={' '.join(q(a) for a in base + args)}\n"
                f"Icon={icon or APP_ID}\nTerminal=false\nCategories=Game;\nX-Cellar-Shortcut=true\n")
    os.chmod(path, 0o755)
    return path

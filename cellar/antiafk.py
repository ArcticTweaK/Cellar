"""Anti-AFK (port of AntiAfk.cs).

Roblox kicks after ~20 minutes without input. Every N minutes each Sober window this app
started is focused for a moment through KWin, gets one tiny input from ydotool (a virtual
input device - the only way to type into another window on Wayland), and the window you
were using gets the focus back.

Keyboard actions are the reliable choice on Wayland because they go to the focused window
wherever the mouse is. "Nudge" moves the pointer by a few pixels and only counts when the
pointer is over that Roblox window.
"""

import os
import shutil
import subprocess
from typing import Callable, List, Optional

from PySide6.QtCore import QEventLoop, QTimer

from . import log, store

ACTIONS = [("Zoom", "Zoom camera  (press I then O - recommended)"),
           ("Space", "Jump  (press Space)"),
           ("Nudge", "Mouse nudge  (only works while the pointer is over that window)")]

KEY_SPACE, KEY_I, KEY_O = 57, 23, 24


def ydotool_path() -> Optional[str]:
    return shutil.which("ydotool") or next((p for p in ("/run/current-system/sw/bin/ydotool", "/usr/bin/ydotool")
                                            if os.access(p, os.X_OK)), None)


def socket_path() -> Optional[str]:
    for p in (os.environ.get("YDOTOOL_SOCKET"), "/run/ydotoold/socket", f"/run/user/{os.getuid()}/.ydotool_socket",
              "/tmp/.ydotool_socket"):
        if p and os.path.exists(p):
            return p
    return None


def status() -> str:
    """'' when ready, otherwise what is missing."""
    if not ydotool_path():
        return "ydotool is not installed (install the 'ydotool' package; NixOS: programs.ydotool.enable = true)"
    sp = socket_path()
    if not sp:
        return ("the ydotoold daemon is not running (most distros: systemctl --user enable --now ydotool; "
                "NixOS: programs.ydotool.enable = true)")
    if not os.access(sp, os.W_OK):
        return f"no permission for {sp} (add yourself to the 'ydotool' group and log in again)"
    return ""


def _ydo(*args: str) -> bool:
    exe = ydotool_path()
    if not exe:
        return False
    env = dict(os.environ)
    sp = socket_path()
    if sp:
        env["YDOTOOL_SOCKET"] = sp
    try:
        return subprocess.run([exe, *args], env=env, capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _sleep(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _key(code: int) -> bool:
    return _ydo("key", f"{code}:1", f"{code}:0")


def _do_action() -> bool:
    act = store.settings.anti_afk_action
    if act == "Space":
        return _key(KEY_SPACE)
    if act == "Nudge":
        ok = _ydo("mousemove", "-x", "4", "-y", "2")
        _sleep(40)
        return _ydo("mousemove", "-x", "-4", "-y", "-2") and ok
    ok = _key(KEY_I)
    _sleep(60)
    return _key(KEY_O) and ok


_busy = False


def pulse(kwin, window_ids: List[str], logf: Callable[[str], None]) -> int:
    """window_ids: KWin ids of the windows to poke (only clients this app started). Runs on the UI thread."""
    global _busy
    if _busy or not window_ids:
        return 0
    why = status()
    if why:
        logf("Anti-AFK cannot send input: " + why)
        return 0
    _busy = True
    n = 0
    try:
        before = kwin.active_id()
        wins = {w.id: w for w in kwin.windows()}
        for wid in window_ids:
            w = wins.get(wid)
            if w is None or wid == before:
                continue                   # the window you are using needs nothing
            was_min = w.minimized
            kwin.activate(wid)
            _sleep(160)                    # let Roblox notice it has the focus
            if _do_action():
                n += 1
            _sleep(80)
            if was_min:
                kwin.minimize([wid])
        if before:
            kwin.activate(before)          # give you your window back
    except Exception as ex:
        log.error("anti-AFK", ex)
    finally:
        _busy = False
    return n

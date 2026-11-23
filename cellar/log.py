"""Tiny app log: writes log.txt and notifies listeners (the UI log panel)."""

import threading
import time
import traceback
from typing import Callable, List

from . import paths

_lock = threading.Lock()
_listeners: List[Callable[[str, bool], None]] = []
_last_msg = ""
_last_stamp = ""
_repeat = 0


def init() -> None:
    try:
        if paths.LOG_FILE.exists() and paths.LOG_FILE.stat().st_size > 512 * 1024:
            paths.LOG_FILE.unlink()
    except OSError:
        pass


def add_listener(fn: Callable[[str, bool], None]) -> None:
    _listeners.append(fn)


def write(msg: str) -> None:
    """Log one line. The same message repeated right after itself is shown as "(2x)", "(3x)"..."""
    global _last_msg, _last_stamp, _repeat
    now = time.strftime("%H:%M:%S")
    with _lock:
        replace = _repeat > 0 and msg == _last_msg
        if replace:
            _repeat += 1
            shown = f"{_last_stamp}  {msg}  ({_repeat}x)"
        else:
            _last_msg, _last_stamp, _repeat = msg, now, 1
            shown = f"{now}  {msg}"
        try:
            with open(paths.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{now}  {msg}\n")
        except OSError:
            pass
    for fn in list(_listeners):
        try:
            fn(shown, replace)
        except Exception:
            pass


def error(where: str, ex: BaseException) -> None:
    write(f"ERROR in {where}: {type(ex).__name__}: {ex}")
    with _lock:
        try:
            with open(paths.LOG_FILE, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(type(ex), ex, ex.__traceback__)))
        except OSError:
            pass

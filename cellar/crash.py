"""Crash handling: Python errors anywhere -> log + one friendly dialog; hard crashes (segfaults, e.g. in Qt WebEngine
or a GPU driver) -> a trace in crash.txt that the next start reports.

Without this, an error inside a Qt slot only printed to a terminal nobody sees, and a segfault closed Cellar
without a word (the browser-login crash on NVIDIA + Wayland looked exactly like that).
"""

import faulthandler
import sys
import threading
import time
import traceback

from . import log, paths, util

CRASH_FILE = paths.DATA_DIR / "crash.txt"
LAST_CRASH_FILE = paths.DATA_DIR / "crash-last.txt"

_fault_file = None
_shown_at = 0.0
_dialog_open = False


def scrub(text: str) -> str:
    """Never let a .ROBLOSECURITY cookie end up in a report someone pastes into a bug report."""
    return util._COOKIE_RE.sub("<cookie removed>", text)


def previous_crash() -> str:
    """The trace of a hard crash in the last run ('' if it ended normally). Moved to crash-last.txt."""
    try:
        text = CRASH_FILE.read_text(errors="replace").strip() if CRASH_FILE.exists() else ""
        if text:
            CRASH_FILE.replace(LAST_CRASH_FILE)
        return text
    except OSError:
        return ""


def install() -> None:
    global _fault_file
    try:
        _fault_file = open(CRASH_FILE, "w")
        faulthandler.enable(_fault_file, all_threads=True)
    except OSError:
        faulthandler.enable()
    sys.excepthook = _hook
    threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback, a.thread.name if a.thread else "")


def uninstall() -> None:
    """Normal quit: an empty crash file means "ended normally" for the next start."""
    try:
        faulthandler.disable()
        if _fault_file:
            _fault_file.close()
        CRASH_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _hook(etype, value, tb, thread: str = "") -> None:
    if issubclass(etype, KeyboardInterrupt):
        return
    details = scrub("".join(traceback.format_exception(etype, value, tb)))
    log.write(f"ERROR{' in ' + thread if thread else ''}: {etype.__name__}: {scrub(str(value))}")
    try:
        with open(paths.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(details)
    except OSError:
        pass
    try:
        from .ui.common import ui
        ui(lambda: _show(etype.__name__, scrub(str(value)), details))
    except Exception:
        sys.__excepthook__(etype, value, tb)


def _show(name: str, msg: str, details: str) -> None:
    """One dialog at a time and at most one per 20 s, so a repeating error cannot bury the screen in boxes."""
    global _shown_at, _dialog_open
    if _dialog_open or time.time() - _shown_at < 20:
        return
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox
    _dialog_open, _shown_at = True, time.time()
    try:
        box = QMessageBox(QMessageBox.Warning, "Something went wrong",
                          "Cellar hit an error but keeps running. What you just did may not have worked - try it "
                          "again.\n\nIf it keeps happening, press Copy details and include it in a bug report.",
                          parent=QApplication.activeWindow())
        box.setInformativeText(f"{name}: {msg}"[:300])
        box.setDetailedText(details)
        copy = box.addButton("Copy details", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is copy:
            QGuiApplication.clipboard().setText(details)
    finally:
        _dialog_open = False

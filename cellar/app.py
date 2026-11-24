"""Entry point."""

import json
import os
import signal
import sys

from . import APP_ID, APP_NAME, __version__, log, paths, store


def _unlock(parent=None) -> bool:
    from PySide6.QtWidgets import QMessageBox
    from .ui.dialogs import PasswordDialog
    kind = store.file_kind()
    if kind == "P":
        while True:
            pw = PasswordDialog.ask(parent, f"{APP_NAME} - unlock", "Enter the password of your accounts file:")
            if pw is None:
                return False
            err = store.load_accounts(pw)
            if err is None:
                return True
            QMessageBox.warning(parent, APP_NAME, err)
    while True:
        err = store.load_accounts(None)
        if err is None:
            return True
        box = QMessageBox(QMessageBox.Warning, APP_NAME, err + "\n\nRetry (for example after unlocking your wallet), "
                          "start with an empty account list (the old file is kept as accounts.dat.old), or quit?")
        retry = box.addButton("Retry", QMessageBox.AcceptRole)
        fresh = box.addButton("Start empty", QMessageBox.DestructiveRole)
        box.addButton("Quit", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is retry:
            continue
        if box.clickedButton() is fresh:
            store.start_fresh()
            return True
        return False


def _apply_ui_scale() -> None:
    """Settings > Appearance > Size: Qt's own scale factor makes everything bigger together (text, icons,
    spacing, pictures). It has to be set before the QApplication exists, so it is read straight from the file."""
    if os.environ.get("QT_SCALE_FACTOR"):              # the user (or the desktop) already chose one
        return
    try:
        with open(paths.SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        v = str(d.get("ui_scale", "auto"))
        factor = float(d.get("auto_scale", 1.0)) if v == "auto" else int(v) / 100
    except (OSError, ValueError, TypeError):
        return
    if 0.5 <= factor <= 3 and abs(factor - 1) > 0.01:
        os.environ["QT_SCALE_FACTOR"] = f"{factor:.2f}"


def auto_scale_for(width: int) -> float:
    """'Auto' size from the primary screen's width in logical pixels (after the desktop's own scaling)."""
    return 1.3 if width >= 3200 else 1.15 if width >= 2300 else 1.0


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_ID} {__version__}")
        return 0
    from . import cli
    pending_cmd = None
    if cli.is_cli(argv):
        rc = cli.main(argv)
        if rc is not None:
            return rc
        pending_cmd = argv[1:]          # Cellar is not running: start it, then do the command

    # Qt WebEngine (browser login) needs shared OpenGL contexts set before the QApplication exists. The module
    # itself is only imported when a login window opens (browser_login): that saves ~36 MB for everyone else.
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    _apply_ui_scale()
    app = QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)                 # Wayland app id -> icon / taskbar grouping
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    # one copy only - a second start just shows the first one
    sock_name = f"{APP_ID}-{os.getuid()}"
    from . import playlink
    link = next((a for a in argv[1:] if playlink.is_link(a)), "")
    probe = QLocalSocket()
    probe.connectToServer(sock_name)
    if probe.waitForConnected(400):
        probe.write(b"open " + link.encode() if link else b"show")
        probe.flush()
        probe.waitForBytesWritten(400)
        return 0
    # Cellar's old self (Roblox MultiHub for Linux) uses the same accounts: never both at once.
    old = QLocalSocket()
    old.connectToServer(f"{paths.OLD_ID}-{os.getuid()}")
    if old.waitForConnected(400):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, APP_NAME, "Roblox MultiHub is still running - Cellar is its new version and "
                                "takes over its accounts.\n\nQuit Roblox MultiHub first (tray icon > Quit; answer "
                                "No to keep your accounts running), then start Cellar again. Cellar takes the "
                                "running accounts over.")
        return 0
    QLocalServer.removeServer(sock_name)
    server = QLocalServer()
    server.listen(sock_name)
    # Stop answering the moment Cellar quits, not when the process finally ends: Python still waits for running
    # background jobs (seconds, measured), and meanwhile a new Cellar (Restart, or you opening it again) would
    # connect to this dying one, ask it to show itself and quit - nothing opened. Closing here also keeps the late
    # QLocalServer destructor from deleting the socket file the new Cellar has made by then.
    app.aboutToQuit.connect(server.close)

    from .ui.common import app_icon, init_threading
    app.setWindowIcon(app_icon())
    init_threading()
    moved = paths.migrate_old_name()
    paths.ensure_dirs()
    log.init()
    from . import crash
    if crash.previous_crash():
        log.write(f"Cellar closed unexpectedly last time. What it was doing is saved in {crash.LAST_CRASH_FILE} "
                  "- please include that file if you report the problem.")
    crash.install()
    for m in moved:
        log.write("rename to Cellar: " + m)
    from . import sober
    if not sober.old_clients_running() and paths.drop_old_link():
        log.write(f"rename to Cellar: removed the link at {paths.OLD_DATA_DIR} (no account from before runs any more)")
    store.load_settings()
    scr = app.primaryScreen()
    if scr is not None:     # remember what 'auto' should use next time (the scale itself is set before Qt starts)
        own = float(os.environ.get("QT_SCALE_FACTOR") or 1)
        store.settings.auto_scale = auto_scale_for(int(scr.geometry().width() * own))
        store.save_settings()
    from . import theme
    theme.set_accent(store.settings.accent)
    theme.apply(store.settings.theme)
    if not _unlock():
        return 0

    from PySide6.QtCore import QTimer
    from .ui.main_window import MainWindow
    hidden = "--minimized" in argv or store.settings.start_minimized_to_tray or (
        pending_cmd is not None and pending_cmd[0] != "show")
    w = MainWindow(start_hidden=hidden)
    if not hidden or w.tray is None:
        w.show()

    def on_conn():
        c = server.nextPendingConnection()
        if not c:
            return

        def read():
            msg = bytes(c.readAll()).decode(errors="replace")
            if msg.startswith("open "):
                w.open_play_link(msg[5:])
            elif msg.startswith("cmd "):
                try:
                    reply = w.run_command(json.loads(msg[4:]))
                except Exception as ex:
                    reply = f"ERR {ex}"
                c.write(reply.encode() + b"\0")
                c.flush()
            else:
                w.showNormal()
                w.raise_()
                w.activateWindow()
        c.readyRead.connect(read)
    server.newConnection.connect(on_conn)
    if link:
        QTimer.singleShot(1500, lambda: w.open_play_link(link))
    if pending_cmd:
        QTimer.singleShot(2500, lambda: w.log(w.run_command(pending_cmd)))

    # let Python handle Ctrl+C in a terminal
    t = QTimer()
    t.start(500)
    t.timeout.connect(lambda: None)
    rc = app.exec()
    crash.uninstall()
    return rc

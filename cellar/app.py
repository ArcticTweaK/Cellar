"""Entry point."""

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


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_ID} {__version__}")
        return 0

    # Qt WebEngine (browser login) must be imported before the QApplication exists.
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        pass
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    app = QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)                 # Wayland app id -> icon / taskbar grouping
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    # one copy only - a second start just shows the first one
    sock_name = f"{APP_ID}-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(sock_name)
    if probe.waitForConnected(400):
        probe.write(b"show")
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

    from .ui.common import app_icon, init_threading
    app.setWindowIcon(app_icon())
    init_threading()
    moved = paths.migrate_old_name()
    paths.ensure_dirs()
    log.init()
    for m in moved:
        log.write("rename to Cellar: " + m)
    from . import sober
    if not sober.old_clients_running() and paths.drop_old_link():
        log.write(f"rename to Cellar: removed the link at {paths.OLD_DATA_DIR} (no account from before runs any more)")
    store.load_settings()
    if not _unlock():
        return 0

    from .ui.main_window import MainWindow
    hidden = "--minimized" in argv or store.settings.start_minimized_to_tray
    w = MainWindow(start_hidden=hidden)
    if not hidden or w.tray is None:
        w.show()

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(lambda: (w.showNormal(), w.raise_(), w.activateWindow()))
    server.newConnection.connect(on_conn)

    # let Python handle Ctrl+C in a terminal
    from PySide6.QtCore import QTimer
    t = QTimer()
    t.start(500)
    t.timeout.connect(lambda: None)
    return app.exec()

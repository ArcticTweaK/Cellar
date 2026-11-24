"""Screenshots of Cellar's main window without touching your real Cellar, accounts or Sober.

Renders off-screen (no window appears) with fake accounts and throw-away config / data folders, so it works
while your real Cellar is running. Use it to check how UI changes look.

    nix develop -c python tools/screenshot.py OUT_DIR [themes] [tabs]
    nix develop -c python tools/screenshot.py /tmp/shots blossom,daylight 0,7
    EMPTY=1 ...    the same with no accounts (empty state)

themes: keys from cellar/theme.py (default: all). tabs: page numbers: 0 Home, 1 Library, 2 Accounts, 3 Friends, 4 Servers,
5 Presets, 6 Macros, 7 Windows, 8 Performance, 9 My Sober, 10 Settings, 11 Help, 12 Activity (default: 0).
"""

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp(prefix="cellar-shot-")
for _v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[_v] = os.path.join(_tmp, _v.lower())
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])

from cellar import paths, store, theme  # noqa: E402
from cellar.models import Account  # noqa: E402
from cellar.ui import main_window  # noqa: E402
from cellar.ui.common import init_threading  # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_tmp, "shots")
    themes = sys.argv[2].split(",") if len(sys.argv) > 2 else [t.key for t in theme.THEMES]
    tabs = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0]
    init_threading()
    paths.ensure_dirs()
    store.load_settings()
    store.loaded = False                    # never write an accounts file
    names = [] if os.environ.get("EMPTY") else ["ArcticTweaK", "JasperThunderbeast", "piedmontdriver", "empyreanOS",
                                                 "arctic_hz"]
    store.accounts = [Account(username=n, order=i) for i, n in enumerate(names)]
    for i, a in enumerate(store.accounts):
        a.last_used = time.time() - 3600 * (i + 1)
        a.group = "Main" if i == 0 else "Farm"
        li = store.live(a)
        li.presence_type, li.where = (2, "Some Game") if i < 4 else (1, "")

    main_window.MainWindow.startup = lambda self: None     # no network, no adopting real clients
    theme.apply(themes[0])
    w = main_window.MainWindow()
    w.model.running = {a.id for a in store.accounts}
    w.resize(1600, 980)
    w.show()
    if store.accounts:
        w.table.selectRow(0)
    os.makedirs(out, exist_ok=True)
    for th in themes:
        w.apply_theme(th)
        for tab in tabs:
            w.tabs.setCurrentIndex(tab)
            for _ in range(5):
                app.processEvents()
            w.grab().save(os.path.join(out, f"{th}_{tab}.png"))
    print("saved to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

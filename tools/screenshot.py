"""Screenshots of Cellar's main window without touching your real Cellar, accounts or Sober.

Renders off-screen (no window appears) with fake accounts and throw-away config / data folders, so it works
while your real Cellar is running. Use it to check how UI changes look.

    nix develop -c python tools/screenshot.py OUT_DIR [themes] [tabs]
    nix develop -c python tools/screenshot.py /tmp/shots blossom,daylight 0,7
    EMPTY=1 ...    the same with no accounts (empty state)
    TABLE=1 ...    the account list as a table instead of cards

themes: keys from cellar/theme.py (default: all). tabs: 0 Launch, 1 Presets, 2 Macros, 3 Anti-AFK & rejoin,
4 Windows, 5 My Sober, 6 Performance, 7 Settings, 8 Help (default: 0).
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
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])

from cellar import paths, store, theme  # noqa: E402
from cellar.models import Account  # noqa: E402
from cellar.ui import main_window  # noqa: E402
from cellar.ui.common import init_threading  # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_tmp, "shots")
    themes = sys.argv[2].split(",") if len(sys.argv) > 2 else [t.key for t in theme.THEMES]
    tabs = sys.argv[3].split(",") if len(sys.argv) > 3 else ["0"]
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
        a.color = ["blue", "", "green", "green", "pink"][i % 5]
        li = store.live(a)
        li.presence_type, li.where = (2, "Some Game") if i < 4 else (1, "")

    main_window.MainWindow.startup = lambda self: None     # no network, no adopting real clients
    from cellar import games
    from cellar.models import GameEntry
    from cellar.ui import dialogs, launch_pages
    launch_pages.bg = dialogs.bg = lambda *a, **k: None    # no network (friends, favourites, game details)
    from PySide6.QtGui import QColor, QImage
    games.ICON_DIR.mkdir(parents=True, exist_ok=True)
    img = QImage(150, 150, QImage.Format_ARGB32)
    names = ["ABOVE", "Murder Mystery 2", "Emergency Response", "Fisch", "Dandy's World", "Blox Fruits"]
    for i, name in enumerate(names):            # fake recent games with generated icons (place 1001+i, universe i+1)
        img.fill(QColor.fromHsv(i * 57 % 360, 150, 210))
        img.save(str(games.icon_path(i + 1)))
        games._uni[1001 + i] = i + 1
        store.settings.recent.append(GameEntry(place_id=1001 + i, name=name, ts=time.time() - i))
    store.settings.last_place_id = "1002"           # one tile chosen
    if os.environ.get("ACCENT"):
        theme.set_accent(os.environ["ACCENT"])
    theme.apply(themes[0])
    w = main_window.MainWindow()
    w.model.running = {a.id for a in store.accounts}
    w.resize(1600, 980)
    w.show()
    if os.environ.get("TABLE"):
        w.view_btns.button(1).click()
    if store.accounts:
        w.table.selectRow(0)
    os.makedirs(out, exist_ok=True)
    for th in themes:
        w.apply_theme(th)
        for tab in tabs:
            w.tabs.setCurrentIndex(int(tab))
            for _ in range(5):
                app.processEvents()
            if os.environ.get("SCROLL"):            # SCROLL=1: the bottom of a long tab (e.g. Performance)
                page = w.tabs.currentWidget()
                for sa in [page, *page.findChildren(QScrollArea)]:
                    if isinstance(sa, QScrollArea):
                        sb = sa.verticalScrollBar()
                        sb.setValue(sb.maximum())
                for _ in range(3):
                    app.processEvents()
            w.grab().save(os.path.join(out, f"{th}_{tab}.png"))
    print("saved to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

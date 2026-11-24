"""Soak test: does Cellar's main window keep growing when it runs for hours?

Off-screen, fake accounts, throw-away config / data / cache folders (like tools/screenshot.py), no network: it
fast-forwards what hours of use do - status ticks, log lines, page switches, right-click menus and dialogs (real
exec(), closed by a timer), toasts, Home "Your games" refilled with new games, theme switches - and prints memory and Qt
object counts per round. Each round runs from the real event loop, like a click does, so deleteLater() behaves as in
the app. A count that climbs every round is a leak; RSS that flattens out is fine.

    nix develop -c python tools/soak.py [rounds]          (default 10 rounds)
"""

import gc
import os
import sys
import tempfile
import time
import tracemalloc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp(prefix="cellar-soak-")
for _v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[_v] = os.path.join(_tmp, _v.lower())
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QObject, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])

from cellar import games, paths, store, theme  # noqa: E402
from cellar.games import Game  # noqa: E402
from cellar.models import Account  # noqa: E402
from cellar.ui import dialogs, launch_pages, main_window  # noqa: E402
from cellar.models import LaunchSpec  # noqa: E402
from cellar.ui import common  # noqa: E402
from cellar.ui.common import _icon_buttons, init_threading  # noqa: E402
from cellar.ui.dialogs import EditAccountDialog, GamePicker, PasteDialog, TextDialog  # noqa: E402
from cellar.ui.launch_pages import HistoryDialog  # noqa: E402
from cellar.ui.palette import Palette  # noqa: E402

launch_pages.bg = dialogs.bg = lambda *a, **k: None    # no network: friends, favourites, game details


def closing(fn, *args):
    """Runs fn (which opens a menu or dialog with exec()) and closes that popup as soon as it shows."""
    def close():
        p = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if p is None:
            QTimer.singleShot(5, close)
        elif hasattr(p, "reject"):
            p.reject()
        else:
            p.close()
    QTimer.singleShot(0, close)
    fn(*args)


def rss_mb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def fake_icons(start: int, n: int) -> list:
    """n games with 150x150 icons on disk (the size Roblox thumbnails are fetched at)."""
    out = []
    img = QImage(150, 150, QImage.Format_ARGB32)
    for u in range(start, start + n):
        img.fill(QColor.fromHsv(u * 37 % 360, 160, 200))
        img.save(str(games.icon_path(u)))
        out.append(Game(name=f"Game {u}", place_id=u * 10, universe_id=u, players=u * 3))
    return out


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    init_threading()
    paths.ensure_dirs()
    games.icon_path(1).parent.mkdir(parents=True, exist_ok=True)
    store.load_settings()
    store.loaded = False                    # never write an accounts file
    store.accounts = [Account(username=f"soak_account_{i}", order=i, user_id=1000 + i) for i in range(8)]
    main_window.MainWindow.startup = lambda self: None     # no network, no adopting real clients
    theme.apply("blossom")
    w = main_window.MainWindow()
    w.resize(1600, 980)
    w.show()
    w.table.selectRow(0)
    steps = run(w, rounds)
    end = object()
    timer = QTimer(interval=0, timeout=lambda: next(steps, end) is end and app.quit())
    timer.start()
    app.exec()
    return 0


def run(w, rounds: int):
    """One step per yield: control goes back to the event loop in between (deleteLater runs there)."""
    yield
    pages = [w.tabs.widget(i) for i in range(w.tabs.count())]
    lp = w.launch_page
    tracemalloc.start(1)
    base = None
    print(f"{'round':>5} {'RSS MB':>8} {'widgets':>8} {'QObjects':>9} {'py objs':>8} {'games':>8} "
          f"{'log blocks':>10} {'icon btns':>9}")
    t0 = time.time()
    for r in range(rounds + 1):
        if r:
            for k in range(200):                                    # ~ an evening of log lines
                w.log(f"[soak_account_{k % 8}] round {r} line {k}: joined a game")
            for page in pages:                                      # visit every page
                w.show_page(page)
                yield
            for _ in range(30):                                     # status / usage ticks (2 s each in real use)
                w.tick()
            yield
            for _ in range(5):                                      # right-click menus
                closing(w.context_menu, w.table.visualRect(w.table.model().index(0, 0)).center())
                yield
                closing(lambda: common.popup(launch_pages.play_menu(w, w, LaunchSpec(kind="Game", place_id=1), "x"),
                                             QPoint(40, 40)))
                yield
            for make in (lambda: GamePicker(w, None),
                         lambda: TextDialog(w, "Details", "text " * 500), lambda: PasteDialog(w, "Paste", "hint"),
                         lambda: EditAccountDialog(w, store.accounts[1]), lambda: HistoryDialog(w),
                         lambda: Palette(w)):
                closing(lambda: make().exec())
                yield
            for k in range(4):
                w.toast(f"round {r} toast {k}")
            # Your games refilled with games it has not shown before (recent / favourites change over hours)
            lp.strip._fill(fake_icons(r * 1000, 40), "")
            w.show_page(w.accounts_page)
            yield
            if r % 3 == 0:
                w.apply_theme("midnight" if r % 2 else "blossom")
            yield
        gc.collect()
        yield
        snap = tracemalloc.take_snapshot()
        if r == 1:
            base = snap
        nobj = len(QApplication.allWidgets())
        qobjs = len(w.findChildren(QObject))
        print(f"{r:>5} {rss_mb():>8.1f} {nobj:>8} {qobjs:>9} {len(gc.get_objects()):>8} {lp.strip.list.count():>8} "
              f"{w.logview.document().blockCount():>10} {len(_icon_buttons):>9}", flush=True)
    print(f"\n{rounds} rounds in {time.time() - t0:.0f} s. Python allocations that grew most since round 1:")
    for st in snap.compare_to(base, "lineno")[:8]:
        print("  ", st)


if __name__ == "__main__":
    raise SystemExit(main())

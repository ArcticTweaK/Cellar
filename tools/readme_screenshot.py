"""The README screenshot (docs/screenshot.png): made-up accounts, real game icons from your local Cellar cache.

    nix develop -c python tools/readme_screenshot.py [OUT.png] [theme]      (default: docs/screenshot.png blossom)

Off-screen with throw-away folders, like tools/screenshot.py - your running Cellar and accounts are not touched.
Game names / player counts come from Roblox's public games API (one request, no login); never put real account
names in the README picture.
"""
import os
import shutil
import sys
import tempfile
import time
_tmp = tempfile.mkdtemp(prefix="cellar-readme-")
for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[v] = os.path.join(_tmp, v.lower())
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REAL_CACHE = os.path.expanduser("~/.cache/cellar/games")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshot.png")
THEME = sys.argv[2] if len(sys.argv) > 2 else "blossom"
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication([])
from cellar import games, paths, store, theme  # noqa: E402
from cellar.games import Game  # noqa: E402
from cellar.models import Account, GameEntry  # noqa: E402
from cellar.ui import dialogs, launch_pages, main_window  # noqa: E402
from cellar.ui.common import init_threading  # noqa: E402
launch_pages.bg = dialogs.bg = lambda *a, **k: None
init_threading()
paths.ensure_dirs()
store.load_settings()
store.loaded = False                    # never write an accounts file
want = ["Blox Fruits", "[🐶] Adopt Me!", "Brookhaven 🏡RP", "🌻 Dandy's World [1.0]", "99 Nights in the Forest 🔦",
        "[🛡️] RIVALS", "Fisch 🦃 [FISCHGIVING]", "Steal An Egg", "[🎃] Jujutsu Shenanigans"]
cached = [Game(universe_id=int(f[:-4])) for f in os.listdir(REAL_CACHE) if f.endswith(".png")][:150]
games.fill(cached)                                  # names, players (public API)
popular = sorted((g for g in cached if g.name and g.players), key=lambda g: -g.players)
gl = [g for g in popular if g.name in want] or popular[:9]
gl.sort(key=lambda g: want.index(g.name) if g.name in want else 99)
games.ICON_DIR.mkdir(parents=True, exist_ok=True)
for g in gl:
    shutil.copy(os.path.join(REAL_CACHE, f"{g.universe_id}.png"), games.icon_path(g.universe_id))
    games._uni[g.place_id] = g.universe_id
store.settings.recent = [GameEntry(place_id=g.place_id, name=g.name, ts=time.time() - i) for i, g in enumerate(gl)]
store.settings.last_place_id = str(gl[0].place_id)
names = [("ArcticTweaK", "Main", "blue", True), ("BerryFarm_01", "Farm", "green", False), ("BerryFarm_02", "Farm", "green", False),
         ("BerryFarm_03", "Farm", "green", False), ("PixelPilot07", "Trade", "pink", False), ("SnowyAltz", "Trade", "pink", False)]
store.accounts = []
for i, (n, grp, col, main) in enumerate(names):
    a = Account(username=n, order=i, group=grp, color=col, full_quality=main, user_id=1000 + i)
    a.last_used = time.time() - 600 * (i + 1)
    store.accounts.append(a)
    li = store.live(a)
    li.presence_type, li.where = (2, "Blox Fruits") if i < 5 else (1, "")
main_window.MainWindow.startup = lambda self: None
theme.apply(THEME)
w = main_window.MainWindow()
w.resize(1600, 900)
w.show()
for t in (w.t_tick, w.t_presence, w.t_watcher, w.t_audio, w.t_logs, w.t_friends):
    t.stop()
def run():
    w.model.running = {a.id for a in store.accounts[:5]}
    w.model.usage = {a.id: (0.82 if i == 0 else 0.17 + 0.01 * i, int((1.6 if i == 0 else 1.0 + 0.05 * i) * 2**30))
                     for i, a in enumerate(store.accounts[:5])}
    w.model.refresh_status()
    w.autohide_columns()
    w.stat_run.set("5 / 6", "4 in the background")
    w.stat_cpu.set("10%", "1.5 of 16 cores")
    w.stat_mem.set("5.8 GB", "about 1.2 GB each")
    w.st_multi.setText("●  Multi-instance on")
    w.st_multi.setProperty("state", "good")
    theme.repolish(w.st_multi)
    from PySide6.QtCore import QItemSelectionModel
    sm = w.table.selectionModel()
    for r in range(1, 5):
        sm.select(w.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    w.launch_page.strip._fill(gl, "", dedupe=True)
    w.launch_page.set_place(gl[0].place_id)
    w.logview.clear()
    for line in ("18:02:11  Launching 4 account(s): Blox Fruits",
                 "18:02:14  [BerryFarm_01] started on its invisible screen - right-click it > View screen.",
                 "18:02:23  [BerryFarm_02] started on its invisible screen - right-click it > View screen.",
                 "18:02:31  [BerryFarm_03] started on its invisible screen - right-click it > View screen.",
                 "18:02:40  [PixelPilot07] started on its invisible screen - right-click it > View screen.",
                 "18:02:41  Launch sequence finished.",
                 "18:03:05  [BerryFarm_01] running macro 'Berry farm' (loops until you stop it).",
                 "18:31:52  Anti-AFK: poked 4 background account(s)."):
        w.logview.appendPlainText(line)
    for _ in range(8):
        app.processEvents()
    w.grab().save(OUT)
    print("saved", OUT)
    app.quit()
QTimer.singleShot(150, run)
app.exec()

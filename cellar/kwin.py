"""Window control on KDE Plasma (Wayland or X11) through KWin scripting.

On Wayland no program may move another program's windows - except the compositor. KWin lets
us load a small JavaScript into it over D-Bus; the script can list, move, resize, raise,
minimize and un-decorate windows. Results come back through a D-Bus method this app exports
(callDBus from the script into our KWinBridge object).
"""

import itertools
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import ClassInfo, QEventLoop, QObject, QTimer, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

from . import log

SERVICE = "io.github.ArcticTweaK.Cellar"
OBJ_PATH = "/KWinBridge"
IFACE = "io.github.ArcticTweaK.Cellar.KWinBridge"
SOBER_CLASS = "org.vinegarhq.Sober"


@dataclass
class Win:
    id: str
    pid: int
    caption: str
    x: int
    y: int
    w: int
    h: int
    minimized: bool
    active: bool
    output: str
    no_border: bool
    keep_above: bool


@dataclass
class Screen:
    name: str
    x: int
    y: int
    w: int
    h: int
    wx: int
    wy: int
    ww: int
    wh: int
    active: bool = False

    @property
    def label(self) -> str:
        return f"{self.name}  -  {self.w} x {self.h}"


@ClassInfo({"D-Bus Interface": IFACE})
class _Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.results: Dict[str, str] = {}

    @Slot(str, str)
    def report(self, token: str, payload: str) -> None:
        self.results[token] = payload


class KWin:
    name = "KDE Plasma"

    def __init__(self):
        self.bus = QDBusConnection.sessionBus()
        self.receiver = _Receiver()
        self.registered = False
        self._seq = itertools.count(1)
        self._tmpdir = tempfile.mkdtemp(prefix="cellar-kwin-")
        try:
            self.registered = self.bus.registerService(SERVICE) and \
                self.bus.registerObject(OBJ_PATH, self.receiver, QDBusConnection.ExportAllSlots)
        except Exception as ex:
            log.error("KWin bridge", ex)

    # ------------------------------------------------------------ plumbing
    def available(self) -> bool:
        try:
            iface = self.bus.interface()
            return bool(iface and iface.isServiceRegistered("org.kde.KWin").value())
        except Exception:
            return False

    def _scripting(self) -> QDBusInterface:
        return QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", self.bus)

    def run(self, body: str, want: bool = False, timeout_ms: int = 2500):
        """Runs JavaScript inside KWin. With want=True the script must call report(value) once;
        that value is returned (parsed JSON), or None on timeout."""
        n = next(self._seq)
        token = f"t{os.getpid()}_{n}"
        name = f"cellar_{os.getpid()}_{n}"
        prelude = ("function report(v) { callDBus(%s, %s, %s, 'report', %s, JSON.stringify(v)); }\n"
                   "function soberWindows() { var r = []; var ws = workspace.windowList();"
                   " for (var i = 0; i < ws.length; i++) { var w = ws[i];"
                   " if (w.resourceClass == %s && w.normalWindow) r.push(w); } return r; }\n"
                   "function byId(id) { var ws = workspace.windowList();"
                   " for (var i = 0; i < ws.length; i++) if (ws[i].internalId.toString() == id) return ws[i]; return null; }\n"
                   % (json.dumps(SERVICE), json.dumps(OBJ_PATH), json.dumps(IFACE), json.dumps(token),
                      json.dumps(SOBER_CLASS)))
        path = os.path.join(self._tmpdir, name + ".js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(prelude + "try {\n" + body + "\n} catch (e) { print('cellar script error: ' + e); }\n")
        sc = self._scripting()
        try:
            r = sc.call("loadScript", path, name)
            if r.type() != QDBusMessage.ReplyMessage or not r.arguments():
                log.write("KWin refused the script: " + (r.errorMessage() or "unknown error"))
                return None
            sid = int(r.arguments()[0])
            if sid < 0:
                sc.call("unloadScript", name)
                return None
            QDBusInterface("org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", self.bus).call("run")
            if not want:
                return True
            return self._wait(token, timeout_ms)
        finally:
            sc.call("unloadScript", name)
            try:
                os.unlink(path)
            except OSError:
                pass

    def _wait(self, token: str, timeout_ms: int):
        if token not in self.receiver.results:
            loop = QEventLoop()
            done = QTimer()
            done.setSingleShot(True)
            done.timeout.connect(loop.quit)
            poll = QTimer()
            poll.timeout.connect(lambda: token in self.receiver.results and loop.quit())
            done.start(timeout_ms)
            poll.start(15)
            loop.exec()
            poll.stop()
            done.stop()
        payload = self.receiver.results.pop(token, None)
        if payload is None:
            return None
        try:
            return json.loads(payload)
        except ValueError:
            return None

    # ------------------------------------------------------------ queries
    def windows(self) -> List[Win]:
        res = self.run(
            "var out = []; var ws = soberWindows(); var act = workspace.activeWindow;"
            "for (var i = 0; i < ws.length; i++) { var w = ws[i]; var g = w.frameGeometry;"
            " out.push({id: w.internalId.toString(), pid: w.pid, cap: w.caption, x: g.x, y: g.y, w: g.width, h: g.height,"
            " min: w.minimized, act: w === act, out: w.output ? w.output.name : '', nb: w.noBorder, ka: w.keepAbove}); }"
            "report(out);", want=True)
        if not isinstance(res, list):
            return []
        return [Win(d["id"], int(d["pid"] or 0), d.get("cap", ""), int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]),
                    bool(d.get("min")), bool(d.get("act")), d.get("out", ""), bool(d.get("nb")), bool(d.get("ka")))
                for d in res]

    def screens(self) -> List[Screen]:
        res = self.run(
            "var out = []; var ss = workspace.screens;"
            "for (var i = 0; i < ss.length; i++) { var s = ss[i];"
            " var a = workspace.clientArea(KWin.MaximizeArea, s, workspace.currentDesktop);"
            " out.push({n: s.name, g: [s.geometry.x, s.geometry.y, s.geometry.width, s.geometry.height],"
            " a: [a.x, a.y, a.width, a.height], act: s === workspace.activeScreen}); }"
            "report(out);", want=True)
        if not isinstance(res, list):
            return []
        out = [Screen(d["n"], *[int(v) for v in d["g"]], *[int(v) for v in d["a"]], bool(d.get("act"))) for d in res]
        out.sort(key=lambda s: (s.x, s.y))
        return out

    def active_id(self) -> Optional[str]:
        r = self.run("var a = workspace.activeWindow; report(a ? a.internalId.toString() : '');", want=True)
        return r or None

    # ------------------------------------------------------------ actions
    def place(self, items: List[dict]) -> None:
        """items: {id, x, y, w, h, noBorder, keepAbove, skipTaskbar, raise} - geometry keys optional."""
        self.run(
            "var items = %s;"
            "for (var i = 0; i < items.length; i++) { var it = items[i]; var w = byId(it.id); if (!w) continue;"
            " if (w.minimized) w.minimized = false;"
            " if (w.fullScreen) w.fullScreen = false;"
            " if (w.maximizable) w.setMaximize(false, false);"
            " if ('noBorder' in it) w.noBorder = it.noBorder;"
            " if ('keepAbove' in it) w.keepAbove = it.keepAbove;"
            " if ('skipTaskbar' in it) { w.skipTaskbar = it.skipTaskbar; w.skipSwitcher = it.skipTaskbar; w.skipPager = it.skipTaskbar; }"
            " if ('x' in it) w.frameGeometry = {x: it.x, y: it.y, width: it.w, height: it.h};"
            " if (it.raise) workspace.raiseWindow(w); }" % json.dumps(items))

    def set_flags(self, ids: List[str], **flags) -> None:
        self.place([dict(id=i, **flags) for i in ids])

    def activate(self, wid: str) -> None:
        self.run("var w = byId(%s); if (w) { if (w.minimized) w.minimized = false; workspace.activeWindow = w; }" % json.dumps(wid))

    def minimize(self, ids: List[str]) -> None:
        self.run("var ids = %s; for (var i = 0; i < ids.length; i++) { var w = byId(ids[i]); if (w) w.minimized = true; }"
                 % json.dumps(ids))

    def close(self, ids: List[str]) -> None:
        self.run("var ids = %s; for (var i = 0; i < ids.length; i++) { var w = byId(ids[i]); if (w) w.closeWindow(); }"
                 % json.dumps(ids))

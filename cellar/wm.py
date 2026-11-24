"""Window control on Hyprland and Sway - the same interface as kwin.KWin, so the Windows page, presets and anti-AFK
work on those desktops too. pick() chooses the backend for the running desktop.

Both compositors let a client move other clients through their own IPC (hyprctl / swaymsg). Tiling
compositors only place floating windows freely, so a window is made floating before it is moved. What a backend
cannot do is skipped quietly (Hyprland has no minimize: the window goes to a hidden special workspace).
"""

import json
import os
import shutil
import subprocess
from typing import List, Optional

from . import log
from .kwin import SOBER_CLASS, Screen, Win


def pick():
    """KWin on KDE Plasma, else Hyprland / Sway when running in them, else None."""
    from .kwin import KWin
    try:
        k = KWin()
        if k.available():
            return k
    except Exception as ex:
        log.error("KWin bridge", ex)
    for cls in (Hyprland, Sway):
        if cls.detected():
            b = cls()
            if b.available():
                return b
    return None


def _run(argv: List[str], timeout: float = 5) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _json(argv: List[str]):
    try:
        return json.loads(_run(argv) or "null")
    except ValueError:
        return None


# ---------------------------------------------------------------- Hyprland
class Hyprland:
    name = "Hyprland"

    @staticmethod
    def detected() -> bool:
        return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and bool(shutil.which("hyprctl"))

    def __init__(self):
        self.exe = shutil.which("hyprctl") or "hyprctl"

    def available(self) -> bool:
        return isinstance(_json([self.exe, "-j", "version"]), dict)

    def _clients(self) -> list:
        c = _json([self.exe, "-j", "clients"])
        return [x for x in c or [] if x.get("class") == SOBER_CLASS and x.get("mapped", True)]

    def windows(self) -> List[Win]:
        act = self.active_id()
        mons = {m.get("id"): m.get("name", "") for m in _json([self.exe, "-j", "monitors"]) or []}
        out = []
        for c in self._clients():
            (x, y), (w, h) = c.get("at", [0, 0]), c.get("size", [0, 0])
            ws = (c.get("workspace") or {}).get("name", "")
            out.append(Win(c["address"], int(c.get("pid") or 0), c.get("title", ""), x, y, w, h,
                           ws.startswith("special:"), c["address"] == act, mons.get(c.get("monitor"), ""),
                           False, bool(c.get("pinned"))))
        return out

    def screens(self) -> List[Screen]:
        out = []
        for m in _json([self.exe, "-j", "monitors"]) or []:
            scale = float(m.get("scale") or 1) or 1
            w, h = int(m["width"] / scale), int(m["height"] / scale)
            if int(m.get("transform") or 0) % 2:          # rotated 90 / 270
                w, h = h, w
            left, top, right, bottom = (m.get("reserved") or [0, 0, 0, 0])[:4]
            out.append(Screen(m["name"], m["x"], m["y"], w, h, m["x"] + left, m["y"] + top,
                              w - left - right, h - top - bottom, bool(m.get("focused"))))
        out.sort(key=lambda s: (s.x, s.y))
        return out

    def active_id(self) -> Optional[str]:
        a = _json([self.exe, "-j", "activewindow"])
        return a.get("address") if isinstance(a, dict) else None

    def _batch(self, cmds: List[str]) -> None:
        if cmds:
            _run([self.exe, "--batch", " ; ".join(cmds)])

    def place(self, items: List[dict]) -> None:
        cmds = []
        floating = {c["address"]: c.get("floating") for c in self._clients()}
        for it in items:
            sel = f"address:{it['id']}"
            if "x" in it:
                if not floating.get(it["id"]):
                    cmds.append(f"dispatch setfloating {sel}")
                cmds.append(f"dispatch movewindowpixel exact {it['x']} {it['y']},{sel}")
                cmds.append(f"dispatch resizewindowpixel exact {it['w']} {it['h']},{sel}")
            if "noBorder" in it:
                cmds.append(f"dispatch setprop {sel} noborder {1 if it['noBorder'] else 0}")
            if "keepAbove" in it:
                cmds.append(f"dispatch setprop {sel} alwaysontop {1 if it['keepAbove'] else 0}")
            if it.get("raise"):
                cmds.append(f"dispatch alterzorder top,{sel}")
        self._batch(cmds)

    def set_flags(self, ids: List[str], **flags) -> None:
        self.place([dict(id=i, **flags) for i in ids])

    def activate(self, wid: str) -> None:
        self._batch([f"dispatch focuswindow address:{wid}"])

    def minimize(self, ids: List[str]) -> None:
        self._batch([f"dispatch movetoworkspacesilent special:cellar,address:{i}" for i in ids])

    def close(self, ids: List[str]) -> None:
        self._batch([f"dispatch closewindow address:{i}" for i in ids])


# ---------------------------------------------------------------- Sway
class Sway:
    name = "Sway"

    @staticmethod
    def detected() -> bool:
        return bool(os.environ.get("SWAYSOCK")) and bool(shutil.which("swaymsg"))

    def __init__(self, sock: Optional[str] = None):
        self.exe = shutil.which("swaymsg") or "swaymsg"
        self.sock = sock or os.environ.get("SWAYSOCK", "")

    def _msg(self, *args: str) -> list:
        return [self.exe, "-s", self.sock, *args] if self.sock else [self.exe, *args]

    def available(self) -> bool:
        return isinstance(_json(self._msg("-t", "get_version")), dict)

    def _nodes(self):
        """(node, output name, workspace name) for every Sober window, tiled or floating."""
        tree = _json(self._msg("-t", "get_tree")) or {}
        found = []

        def walk(n, out, ws):
            if n.get("type") == "output":
                out = n.get("name", "")
            if n.get("type") == "workspace":
                ws = n.get("name", "")
            if n.get("pid") and (n.get("app_id") == SOBER_CLASS or
                                 (n.get("window_properties") or {}).get("class") == SOBER_CLASS):
                found.append((n, out, ws))
            for k in ("nodes", "floating_nodes"):
                for c in n.get(k) or []:
                    walk(c, out, ws)
        walk(tree, "", "")
        return found

    def windows(self) -> List[Win]:
        out = []
        for n, output, ws in self._nodes():
            r = n.get("rect") or {}
            # sway reports the content; report the whole frame like KWin does (title bar + borders), so saved
            # layouts put windows back exactly where they were
            # (measured: with a title bar sway adds no side borders; "border pixel N" adds N on every side)
            deco = int((n.get("deco_rect") or {}).get("height") or 0)
            bw = 0 if deco or n.get("border") == "none" else int(n.get("current_border_width") or 0)
            x, y = r.get("x", 0) - bw, r.get("y", 0) - deco - bw
            w, h = r.get("width", 0) + 2 * bw, r.get("height", 0) + deco + 2 * bw
            out.append(Win(str(n["id"]), int(n.get("pid") or 0), n.get("name") or "", x, y, w, h,
                           ws == "__i3_scratch", bool(n.get("focused")), output, n.get("border") == "none",
                           bool(n.get("sticky"))))
        return out

    def screens(self) -> List[Screen]:
        out = []
        for o in _json(self._msg("-t", "get_outputs")) or []:
            if not o.get("active"):
                continue
            r = o.get("rect") or {}
            out.append(Screen(o["name"], r["x"], r["y"], r["width"], r["height"], r["x"], r["y"], r["width"],
                              r["height"], bool(o.get("focused"))))
        out.sort(key=lambda s: (s.x, s.y))
        return out

    def active_id(self) -> Optional[str]:
        return next((w.id for w in self.windows() if w.active), None)

    def _cmd(self, cmds: List[str]) -> None:
        if cmds:
            _run(self._msg(", ".join(cmds)) if len(cmds) == 1 else self._msg("; ".join(cmds)))

    def place(self, items: List[dict]) -> None:
        cmds = []
        for it in items:
            sel = f"[con_id={it['id']}]"
            # order matters in sway: the border first (it changes the content size), then the size, the position last
            if "noBorder" in it:
                cmds.append(f"{sel} border {'none' if it['noBorder'] else 'normal'}")
            if "x" in it:
                cmds.append(f"{sel} floating enable, resize set width {it['w']} px height {it['h']} px, "
                            f"move absolute position {it['x']} {it['y']}")
            if "keepAbove" in it:
                cmds.append(f"{sel} sticky {'enable' if it['keepAbove'] else 'disable'}")
            if it.get("raise"):
                cmds.append(f"{sel} focus")
        self._cmd(cmds)

    def set_flags(self, ids: List[str], **flags) -> None:
        self.place([dict(id=i, **flags) for i in ids])

    def activate(self, wid: str) -> None:
        self._cmd([f"[con_id={wid}] focus"])

    def minimize(self, ids: List[str]) -> None:
        self._cmd([f"[con_id={i}] move scratchpad" for i in ids])

    def close(self, ids: List[str]) -> None:
        self._cmd([f"[con_id={i}] kill" for i in ids])

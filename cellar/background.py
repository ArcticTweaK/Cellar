"""Background mode: an account's Sober runs on its own invisible screen, driven over VNC.

On Wayland one program cannot send input to another program's window, so a Roblox window
you are not looking at cannot be macro'd (anti-AFK has to focus each window for a moment).
A background account therefore gets its own headless sway compositor - one 1280x720 output,
nothing on your desktop - that only its Sober draws on. wayvnc exports that screen on a
private unix socket and keeps a virtual keyboard + pointer connected; the hub speaks RFB
(VNC) over that socket to show the screen and to send keys / clicks. Your own desktop,
mouse, keyboard and focus are never touched.

Measured 2026-11-23 (i5-12600K, RTX 3070 Ti): sway ~0.11 CPU cores + ~150 MB RAM and wayvnc
~0 CPU + ~40 MB per background account (Sober itself costs the same as a normal window).
"""

import os
import socket
import stat
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import log
from .sober import which

W, H = 1280, 720
LINK = "wayland-cellar"         # the invisible screen's socket, as seen from the account's runtime dir


@dataclass
class Screen:
    dir: Path                   # sway's own XDG_RUNTIME_DIR (inside the account's runtime dir)
    vnc: Path                   # wayvnc's unix socket
    units: List[str] = field(default_factory=list)


def support() -> Tuple[bool, str]:
    missing = [t for t in ("sway", "wayvnc", "systemd-run") if not which(t)]
    return (not missing), ("missing: " + ", ".join(missing) if missing else "")


def _render_node() -> str:
    """Render on the GPU Sober uses: a discrete card (NVIDIA / AMD) if there is one."""
    nodes = sorted(Path("/dev/dri").glob("renderD*"))
    for n in nodes:
        try:
            if (Path("/sys/class/drm") / n.name / "device" / "vendor").read_text().strip() in ("0x10de", "0x1002"):
                return str(n)
        except OSError:
            pass
    return str(nodes[0]) if nodes else ""


def _run_unit(unit: str, env: dict, argv: List[str]) -> None:
    props = [f"--setenv={k}={v}" for k, v in env.items()]
    subprocess.run([which("systemd-run") or "systemd-run", "--user", f"--unit={unit}", "--collect", "--quiet",
                    *props, *argv], check=True, capture_output=True, timeout=15)


def _is_socket(p: Path) -> bool:
    try:
        return not p.is_symlink() and stat.S_ISSOCK(p.stat().st_mode)
    except OSError:
        return False


def start(rt: Path, logf: Callable[[str], None] = lambda m: None) -> Screen:
    """Starts the invisible screen for one account. rt = the account's runtime dir (sober.runtime_dir_for);
    its name (cellar-<account>) also names the screen's systemd units.
    Raises RuntimeError with a readable reason."""
    ok, why = support()
    if not ok:
        raise RuntimeError(why + " (install the 'sway' and 'wayvnc' packages)")
    d = rt / "screen"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in d.iterdir():                       # leftovers of an earlier screen
        if p.name.startswith(("wayland-", "sway-ipc", "vnc.sock")):
            try:
                p.unlink()
            except OSError:
                pass
    cfg = d / "sway.cfg"
    cfg.write_text(f"output HEADLESS-1 resolution {W}x{H} position 0 0\n"
                   "default_border none\nfocus_follows_mouse no\n"
                   'for_window [app_id=".*"] fullscreen enable\n')
    base = {"XDG_RUNTIME_DIR": str(d), "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    stamp = int(time.time())
    sway_unit = f"{rt.name}-screen-{stamp}.service"
    vnc_unit = f"{rt.name}-vnc-{stamp}.service"
    env = dict(base, WLR_BACKENDS="headless", WLR_LIBINPUT_NO_DEVICES="1")
    node = _render_node()
    if node:
        env["WLR_RENDER_DRM_DEVICE"] = node
    _run_unit(sway_unit, env, [which("sway"), "--unsupported-gpu", "-c", str(cfg)])
    sock = None
    for _ in range(100):
        time.sleep(0.1)
        sock = next((p for p in d.iterdir() if p.name.startswith("wayland-") and not p.name.endswith(".lock")
                     and _is_socket(p)), None)
        if sock:
            break
    if not sock:
        stop(Screen(d, d / "vnc.sock", [sway_unit]))
        raise RuntimeError(f"its invisible screen (sway) did not start - see: journalctl --user -u {sway_unit}")
    link = rt / LINK
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(sock, link)
    vnc = d / "vnc.sock"
    # 30 fps = the alts' default FPS cap (a viewer costs ~1 ms CPU per frame; nothing is sent while none is open)
    _run_unit(vnc_unit, dict(base, WAYLAND_DISPLAY=sock.name), [which("wayvnc"), "-u", "-f", "30", "-r", str(vnc)])
    for _ in range(50):
        time.sleep(0.1)
        if _is_socket(vnc):
            break
    else:
        stop(Screen(d, vnc, [sway_unit, vnc_unit]))
        raise RuntimeError(f"its screen sharing (wayvnc) did not start - see: journalctl --user -u {vnc_unit}")
    logf(f"invisible {W}x{H} screen ready (nothing will show on your desktop).")
    return Screen(d, vnc, [sway_unit, vnc_unit])


def find_running(rt: Path) -> Optional[Screen]:
    """The screen of a background client that was started before this app (re)started."""
    d = rt / "screen"
    if not _is_socket(d / "vnc.sock"):
        return None
    try:
        out = subprocess.run([which("systemctl") or "systemctl", "--user", "list-units", "--plain", "--no-legend",
                              f"{rt.name}-*"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        out = ""
    units = [l.split()[0] for l in out.splitlines() if "-screen-" in l or "-vnc-" in l]
    return Screen(d, d / "vnc.sock", units) if units else None


def stop(screen: Optional[Screen]) -> None:
    if not screen or not screen.units:
        return
    try:
        subprocess.run([which("systemctl") or "systemctl", "--user", "stop", *screen.units],
                       capture_output=True, timeout=15)
    except Exception as ex:
        log.error("stop screen", ex)


# ------------------------------------------------------------------ VNC (RFB 3.8) client
_KEYSYMS = {
    "space": 0x20, "enter": 0xFF0D, "return": 0xFF0D, "esc": 0xFF1B, "escape": 0xFF1B, "tab": 0xFF09,
    "backspace": 0xFF08, "delete": 0xFFFF, "insert": 0xFF63, "home": 0xFF50, "end": 0xFF57,
    "pageup": 0xFF55, "pagedown": 0xFF56, "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "shift": 0xFFE1, "ctrl": 0xFFE3, "control": 0xFFE3, "alt": 0xFFE9, "super": 0xFFEB,
    "capslock": 0xFFE5, "minus": 0x2D, "equal": 0x3D, "comma": 0x2C, "period": 0x2E, "slash": 0x2F,
    "semicolon": 0x3B, "apostrophe": 0x27, "bracketleft": 0x5B, "bracketright": 0x5D, "backslash": 0x5C,
    "grave": 0x60,
}
_KEYSYMS.update({f"f{i}": 0xFFBE + i - 1 for i in range(1, 13)})


def keysym(name: str) -> int:
    """A key: 'w' / 'W' (both the W key - for capitals type 'shift' too), 'space', 'enter', 'f5', ...
    -> X keysym. ValueError if unknown."""
    n = name.strip()
    if len(n) == 1:
        return char_keysym(n.lower() if n.isascii() and n.isalpha() else n)
    k = _KEYSYMS.get(n.lower())
    if k is None:
        raise ValueError(f"unknown key '{name}'")
    return k


def char_keysym(ch: str) -> int:
    """A character to type (keeps upper / lower case)."""
    c = ord(ch)
    return c if 0x20 <= c < 0x7F else 0x01000000 + c


class VNC:
    """Minimal RFB client for wayvnc's unix socket: no authentication, raw pixels (BGRX)."""

    def __init__(self, path: Path, timeout: float = 5.0):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(timeout)
        self._send_lock = threading.Lock()
        try:
            self._handshake(path)
        except BaseException:
            self.s.close()          # a failed connect left the socket open (every retry of a viewer / wall tile)
            raise

    def _handshake(self, path: Path) -> None:
        self.s.connect(str(path))
        self._rx(12)
        self.s.sendall(b"RFB 003.008\n")
        types = self._rx(self._rx(1)[0])
        if 1 not in types:
            raise RuntimeError("the screen asks for a password")
        self.s.sendall(b"\x01")
        if struct.unpack(">I", self._rx(4))[0] != 0:
            raise RuntimeError("the screen refused the connection")
        self.s.sendall(b"\x01")                                      # shared session
        self.width, self.height = struct.unpack(">HH", self._rx(4))
        self._rx(16)
        self._rx(struct.unpack(">I", self._rx(4))[0])
        # 32 bpp true colour, little endian: bytes B, G, R, X = QImage.Format_RGB32
        self._send(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        self._send(struct.pack(">BxHi", 2, 1, 0))                    # encodings: raw only
        self.fb = bytearray(self.width * self.height * 4)
        self.buttons = 0
        self.x = self.y = 0

    def _rx(self, n: int) -> bytes:
        b = bytearray()
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise ConnectionError("the screen closed the connection")
            b += c
        return bytes(b)

    def _send(self, data: bytes) -> None:
        with self._send_lock:
            self.s.sendall(data)

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass

    # input
    def pointer(self, x: int, y: int, buttons: Optional[int] = None) -> None:
        self.x, self.y = max(0, min(self.width - 1, int(x))), max(0, min(self.height - 1, int(y)))
        if buttons is not None:
            self.buttons = buttons
        self._send(struct.pack(">BBHH", 5, self.buttons, self.x, self.y))

    def click(self, x: int, y: int, button: int = 1, hold: float = 0.06) -> None:
        mask = {1: 1, 2: 2, 3: 4}.get(button, 1)
        self.pointer(x - 1, y)                  # a real motion first, so the game sees the pointer arrive
        time.sleep(0.03)
        self.pointer(x, y)
        time.sleep(0.03)
        self.pointer(x, y, self.buttons | mask)
        time.sleep(hold)
        self.pointer(x, y, self.buttons & ~mask)

    def scroll(self, x: int, y: int, up: bool) -> None:
        mask = 8 if up else 16
        self.pointer(x, y, self.buttons | mask)
        self.pointer(x, y, self.buttons & ~mask)

    def key(self, sym: int, down: bool) -> None:
        self._send(struct.pack(">BBxxI", 4, 1 if down else 0, sym))

    def tap(self, sym: int, hold: float = 0.05) -> None:
        self.key(sym, True)
        time.sleep(hold)
        self.key(sym, False)

    def type_text(self, text: str, gap: float = 0.03) -> None:
        for ch in text:
            self.tap(char_keysym(ch), 0.02)
            time.sleep(gap)

    # screen
    def png(self) -> bytes:
        """The current frame as a PNG (the frame buffer is BGRX)."""
        return encode_png(bytes(self.fb), self.width, self.height)

    def request(self, incremental: bool = True) -> None:
        self._send(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.width, self.height))

    def read_update(self) -> bool:
        """Reads one server message; returns True if pixels changed."""
        t = self._rx(1)[0]
        if t == 0:
            self._rx(1)
            n = struct.unpack(">H", self._rx(2))[0]
            changed = False
            for _ in range(n):
                x, y, w, h, enc = struct.unpack(">HHHHi", self._rx(12))
                if enc == 0:
                    data = self._rx(w * h * 4)
                    stride = self.width * 4
                    for row in range(h):
                        o = (y + row) * stride + x * 4
                        self.fb[o:o + w * 4] = data[row * w * 4:(row + 1) * w * 4]
                    changed = True
                elif enc == -223:                                    # DesktopSize
                    self.width, self.height = w, h
                    self.fb = bytearray(w * h * 4)
            return changed
        if t == 1:                                                   # colour map: not used with true colour
            self._rx(3)
            self._rx(struct.unpack(">H", self._rx(2))[0] * 6)
        elif t == 3:                                                 # clipboard text
            self._rx(3)
            self._rx(struct.unpack(">I", self._rx(4))[0])
        return False


def poke(screen: Screen, action: str) -> bool:
    """Anti-AFK for a background client: no focus change, nothing on your desktop."""
    try:
        v = VNC(screen.vnc)
        try:
            if action == "Space":
                v.tap(0x20, 0.08)
            elif action == "Nudge":
                v.pointer(W // 2, H // 2)
                time.sleep(0.05)
                v.pointer(W // 2 + 6, H // 2 + 4)
            else:                                                    # Zoom: I then O
                v.tap(ord("i"), 0.15)
                time.sleep(0.1)
                v.tap(ord("o"), 0.15)
            return True
        finally:
            v.close()
    except Exception as ex:
        log.write(f"background anti-AFK failed: {ex}")
        return False


# ---------------------------------------------------------------- screenshots (Discord alerts)
def encode_png(bgrx: bytes, width: int, height: int) -> bytes:
    """A BGRX frame (VNC raw, 4 bytes per pixel) -> PNG bytes, without Qt (backend threads use it).
    1280x720 takes ~0.1 s; zlib level 6 gives ~0.3-1 MB for a game screen."""
    import zlib
    rows = bytearray()
    stride = width * 4
    rgb = bytearray(width * 3)
    for y in range(height):
        line = bgrx[y * stride:(y + 1) * stride]
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows += b"\0" + rgb                # filter type 0 per row

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def grab_png(screen: "Screen", timeout: float = 4.0) -> Optional[bytes]:
    """One picture of a background account's screen (None if it can't be reached in time)."""
    v = None
    try:
        v = VNC(screen.vnc, timeout=timeout)
        v.request(False)
        end = time.time() + timeout
        while time.time() < end:
            if v.read_update():
                return v.png()
    except Exception as ex:
        log.write(f"screenshot for Discord failed: {ex}")
    finally:
        if v:
            v.close()
    return None

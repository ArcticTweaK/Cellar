"""Per-account sound: mute alts or turn one account down, through PipeWire (pw-dump + wpctl, on every desktop
with PipeWire). Blocking - call from a worker.

Each Roblox client is its own audio stream. A stream is matched to an account through the process behind it:
PipeWire records the real pid of every client (pipewire.sec.pid, from the socket), and every process of one
Sober client lives in the same Flatpak scope (cgroup) as the client's window process - the same way usage.py
counts CPU per account.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import sober
from .usage import cgroup_of

_applied: Dict[int, Tuple[bool, float]] = {}        # stream id -> (mute, volume) Cellar set last


def available() -> bool:
    return bool(sober.which("pw-dump") and sober.which("wpctl"))


def _streams() -> Dict[int, int]:
    """stream node id -> pid of the program playing it."""
    try:
        out = subprocess.run([sober.which("pw-dump")], capture_output=True, text=True, timeout=10).stdout
        objs = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    clients = {}
    for o in objs:
        if o.get("type") == "PipeWire:Interface:Client":
            p = (o.get("info") or {}).get("props") or {}
            pid = p.get("pipewire.sec.pid") or p.get("application.process.id")
            if pid:
                clients[o["id"]] = int(pid)
    res = {}
    for o in objs:
        p = (o.get("info") or {}).get("props") or {}
        if o.get("type") == "PipeWire:Interface:Node" and p.get("media.class") == "Stream/Output/Audio":
            pid = clients.get(p.get("client.id")) or p.get("pipewire.sec.pid") or p.get("application.process.id")
            if pid:
                res[o["id"]] = int(pid)
    return res


def apply(targets: Dict[Path, Tuple[bool, float]]) -> int:
    """targets: cgroup of an account's client -> (mute, volume 0..1). Sets the streams that differ from what
    Cellar set last (a new stream after a rejoin gets it too). Returns how many streams were changed."""
    if not targets or not available():
        return 0
    wp = sober.which("wpctl")
    changed = 0
    streams = _streams()
    for node, pid in streams.items():
        cg: Optional[Path] = cgroup_of(pid)
        want = targets.get(cg) if cg else None
        if want is None:
            continue
        if _applied.get(node) == want:
            continue
        mute, vol = want
        try:
            subprocess.run([wp, "set-mute", str(node), "1" if mute else "0"], capture_output=True, timeout=5)
            subprocess.run([wp, "set-volume", str(node), f"{max(0.0, min(1.5, vol)):.2f}"], capture_output=True,
                           timeout=5)
            _applied[node] = want
            changed += 1
        except (OSError, subprocess.SubprocessError):
            pass
    for node in [n for n in _applied if n not in streams]:       # streams that ended
        _applied.pop(node, None)
    return changed

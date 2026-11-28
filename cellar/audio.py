"""Per-account sound: mute alts or turn one account down, through PipeWire (pw-dump + wpctl, on every desktop
with PipeWire). Blocking - call from a worker.

Each Roblox client is its own audio stream. A stream is matched to an account through the cgroup (Flatpak scope)
of the client, the same one usage.py counts CPU in. Sober plays through the PulseAudio layer, so PipeWire's
pipewire.sec.pid is pipewire-pulse for every Sober stream, and application.process.id is the pid inside the
sandbox (3) - neither tells clients apart (measured 2026-11-24, PipeWire 1.6.9). What does: the Flatpak instance
id the portal stamps on the client (pipewire.access.portal.instance_id), and each instance runs in the scope
app-flatpak-<app id>-<instance id>.scope. The pid is only used for programs outside Flatpak.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import sober
from .usage import app_slice, cgroup_of

_applied: Dict[int, tuple] = {}        # stream id -> (client cgroup, mute, volume) Cellar set last


def available() -> bool:
    return bool(sober.which("pw-dump") and sober.which("wpctl"))


def _client_cgroup(props: dict) -> Optional[Path]:
    """The cgroup of the program behind a PipeWire client (its props)."""
    app_id = props.get("pipewire.access.portal.app_id")
    inst = props.get("pipewire.access.portal.instance_id")
    if app_id and inst:
        return app_slice() / f"app-flatpak-{app_id}-{inst}.scope"
    pid = props.get("pipewire.sec.pid") or props.get("application.process.id")
    try:
        return cgroup_of(int(pid)) if pid else None
    except (TypeError, ValueError):
        return None


def streams_of(objs: list) -> Dict[int, Path]:
    """pw-dump output -> {audio output stream node id: cgroup of the program playing it}."""
    clients = {}
    for o in objs:
        if o.get("type") == "PipeWire:Interface:Client":
            cg = _client_cgroup((o.get("info") or {}).get("props") or {})
            if cg:
                clients[o["id"]] = cg
    res = {}
    for o in objs:
        p = (o.get("info") or {}).get("props") or {}
        if o.get("type") == "PipeWire:Interface:Node" and p.get("media.class") == "Stream/Output/Audio":
            cg = clients.get(p.get("client.id")) or _client_cgroup(p)
            if cg:
                res[o["id"]] = cg
    return res


def _streams() -> Dict[int, Path]:
    try:
        out = subprocess.run([sober.which("pw-dump")], capture_output=True, text=True, timeout=10).stdout
        return streams_of(json.loads(out or "[]"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def apply(targets: Dict[Path, Tuple[bool, float]]) -> int:
    """targets: cgroup of an account's client -> (mute, volume 0..1). Sets the streams that differ from what
    Cellar set last (a new stream after a rejoin gets it too). Returns how many streams were changed."""
    if not targets or not available():
        return 0
    wp = sober.which("wpctl")
    changed = 0
    streams = _streams()
    for node, cg in streams.items():
        want = targets.get(cg)
        if want is None:
            continue
        stamp = (cg, *want)      # PipeWire can reuse a node id for a different client's new stream
        if _applied.get(node) == stamp:
            continue
        mute, vol = want
        try:
            subprocess.run([wp, "set-mute", str(node), "1" if mute else "0"], capture_output=True, timeout=5,
                           check=True)
            subprocess.run([wp, "set-volume", str(node), f"{max(0.0, min(1.5, vol)):.2f}"], capture_output=True,
                           timeout=5, check=True)
            _applied[node] = stamp
            changed += 1
        except (OSError, subprocess.SubprocessError):
            pass
    for node in [n for n in _applied if n not in streams]:       # streams that ended
        _applied.pop(node, None)
    return changed

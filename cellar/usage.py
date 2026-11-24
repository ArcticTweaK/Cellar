"""CPU and memory of everything Cellar runs for the accounts, from the kernel's own accounting
(cgroup v2). Per account that is its Sober client (in Flatpak's scope) plus Cellar's units for it:
the network helper, and in background mode the invisible screen and its VNC server."""

import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import sober

CGROUP = Path("/sys/fs/cgroup")


def _cgroup_of(pid: int) -> Optional[Path]:
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                if line.startswith("0::/"):
                    return CGROUP / line[4:].strip()
    except OSError:
        pass
    return None


def _app_slice() -> Path:
    uid = os.getuid()
    return CGROUP / "user.slice" / f"user-{uid}.slice" / f"user@{uid}.service" / "app.slice"


def available() -> bool:
    return (CGROUP / "cgroup.controllers").exists()


def groups_for(instances: Iterable) -> List[Path]:
    """The cgroups of the given running instances (each counted once)."""
    own = _cgroup_of(os.getpid())
    app = _app_slice()
    found = set()
    for inst in instances:
        g = _cgroup_of(inst.pid) if inst.pid else None
        if g and g != own:
            found.add(g)
        for prefix in (sober.PREFIX, sober.OLD_PREFIX):
            found.update(app.glob(f"{prefix}{inst.account.id[:12]}-*"))
    return sorted(found)


def _read(g: Path) -> Tuple[int, int]:
    """(CPU time in microseconds, memory in bytes). Memory leaves out inactive file cache, which
    the kernel drops first when it needs room (the same way `docker stats` counts)."""
    usec = 0
    with open(g / "cpu.stat") as f:
        for line in f:
            if line.startswith("usage_usec "):
                usec = int(line.split()[1])
                break
    mem = int((g / "memory.current").read_text())
    with open(g / "memory.stat") as f:
        for line in f:
            if line.startswith("inactive_file "):
                mem -= int(line.split()[1])
                break
    return usec, max(mem, 0)


def mem_available() -> int:
    """Bytes of RAM free for new programs (the kernel's MemAvailable: free + cache it can drop)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def cgroup_of(pid: int) -> Optional[Path]:
    return _cgroup_of(pid)


class Sampler:
    """Call sample() every few seconds; CPU is the average since the previous call."""

    def __init__(self):
        self._last: Dict[Path, Tuple[int, float]] = {}

    def sample_each(self, groups_by_key: Dict[str, List[Path]]) -> Dict[str, Tuple[Optional[float], int]]:
        """Per key (account id): (CPU in cores or None until measured, memory). Plus "" = all of them together."""
        now = time.monotonic()
        new: Dict[Path, Tuple[int, float]] = {}
        per: Dict[Path, Tuple[Optional[float], int]] = {}
        for g in {g for gs in groups_by_key.values() for g in gs}:
            try:
                usec, m = _read(g)
            except (OSError, ValueError):
                continue
            new[g] = (usec, now)
            prev = self._last.get(g)
            cores = max(usec - prev[0], 0) / 1e6 / (now - prev[1]) if prev and now > prev[1] else None
            per[g] = (cores, m)
        self._last = new
        out: Dict[str, Tuple[Optional[float], int]] = {}
        for key, gs in list(groups_by_key.items()) + [("", sorted(per))]:
            vals = [per[g] for g in gs if g in per]
            measured = [c for c, _ in vals if c is not None]
            out[key] = (sum(measured) if measured or not vals else None, sum(m for _, m in vals))
        return out

    def sample(self, groups: List[Path]) -> Tuple[Optional[float], int]:
        """(CPU in cores - None until there is a previous sample to compare with, memory in bytes)."""
        now = time.monotonic()
        cores, mem, compared = 0.0, 0, False
        new: Dict[Path, Tuple[int, float]] = {}
        for g in groups:
            try:
                usec, m = _read(g)
            except (OSError, ValueError):
                continue                    # the unit just ended
            mem += m
            new[g] = (usec, now)
            prev = self._last.get(g)
            if prev and now > prev[1]:      # a unit seen for the first time counts from the next sample
                cores += max(usec - prev[0], 0) / 1e6 / (now - prev[1])
                compared = True
        self._last = new
        return (cores if compared or not groups else None), mem

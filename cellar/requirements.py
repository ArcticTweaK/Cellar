"""What this computer has and what it still needs, with the exact install command for its distro.

Shared by the first-run setup and Settings > System check. No Qt here (cheap, can run on a worker thread).
"""

import os
from dataclasses import dataclass
from typing import List, Optional

from . import antiafk, sober

FLATHUB = "flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo"
SOBER_INSTALL = "flatpak install --user flathub org.vinegarhq.Sober"


@dataclass
class Check:
    key: str
    name: str
    ok: bool
    needed_for: str
    fix: str = ""           # a command to copy, or ''
    note: str = ""          # plain-language extra advice
    required: bool = False  # Cellar cannot launch anything without it


def distro() -> str:
    """nixos / arch / fedora / suse / debian / other (same families as install.sh)."""
    fields = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                fields[k] = v.strip('"')
    except OSError:
        return "other"
    ids = f" {fields.get('ID', '')} {fields.get('ID_LIKE', '')} "
    for fam, keys in (("nixos", (" nixos ",)), ("arch", (" arch ",)), ("fedora", (" fedora ",)),
                      ("suse", (" opensuse", " suse ")), ("debian", (" debian ", " ubuntu "))):
        if any(k in ids for k in keys):
            return fam
    return "other"


def install_cmd(pkgs: List[str], fam: Optional[str] = None) -> str:
    fam = fam or distro()
    p = " ".join(pkgs)
    return {"arch": f"sudo pacman -S --needed {p}", "fedora": f"sudo dnf install {p}",
            "suse": f"sudo zypper install {p}", "debian": f"sudo apt install {p}"}.get(fam, "")


def _pkg_fix(pkgs: List[str], nix_attrs: str, fam: str):
    """(command, note) for missing distro packages."""
    if fam == "nixos":
        return "", (f"Cellar's Nix package brings these itself - start Cellar from the package (nix run / your "
                    f"config), or add {nix_attrs} to environment.systemPackages.")
    cmd = install_cmd(pkgs, fam)
    return cmd, ("" if cmd else f"Install these with your package manager: {' '.join(pkgs)}")


def run(kwin_ok: bool) -> List[Check]:
    fam = distro()
    out: List[Check] = []

    fp = sober.which("flatpak")
    if not fp:
        cmd = install_cmd(["flatpak"], fam)
        out.append(Check("flatpak", "Flatpak", False, "installing Sober (Roblox for Linux)", cmd,
                         "NixOS: services.flatpak.enable = true;" if fam == "nixos" else
                         ("" if cmd else "Install Flatpak with your package manager."), required=True))
    inst = bool(fp) and sober.sober_installed()
    out.append(Check("sober", "Sober", inst, "running Roblox at all", "" if inst else f"{FLATHUB} && {SOBER_INSTALL}",
                     "" if inst else "Sober is the Linux Roblox client Cellar starts for every account.",
                     required=True))
    ver = sober.app_version(sober.main_app()) if inst else ""
    out.append(Check("profile", "Sober set up once", bool(ver), "copying Roblox into each account's own profile",
                     "", "" if ver else "Open Sober once and let it finish downloading Roblox. You do not have to "
                                        "log in there - Cellar logs every account in by itself.", required=True))

    miss = [t for t in ("pasta", "unshare") if not sober.which(t)]
    cmd, note = _pkg_fix(["passt"] + (["util-linux"] if "unshare" in miss else []), "pkgs.passt", fam)
    out.append(Check("multi", "pasta + unshare", not miss, "running several accounts at the same time",
                     "" if not miss else cmd, "" if not miss else note))

    miss = [t for t in ("sway", "wayvnc") if not sober.which(t)]
    cmd, note = _pkg_fix(miss, " and ".join(f"pkgs.{m}" for m in miss), fam)
    out.append(Check("background", "sway + wayvnc", not miss, "background mode (accounts on invisible screens) "
                     "and macros", "" if not miss else cmd, "" if not miss else note))

    afk = antiafk.status()
    if not afk:
        out.append(Check("ydotool", "ydotool", True, "anti-AFK for normal (visible) windows"))
    elif not antiafk.ydotool_path():
        cmd, _ = _pkg_fix(["ydotool"], "", fam)
        out.append(Check("ydotool", "ydotool", False, "anti-AFK for normal (visible) windows",
                         "" if fam == "nixos" else cmd,
                         "NixOS: programs.ydotool.enable = true; then add yourself to the ydotool group."
                         if fam == "nixos" else "Then start its service: systemctl --user enable --now ydotool"))
    else:
        out.append(Check("ydotool", "ydotool", False, "anti-AFK for normal (visible) windows",
                         "" if fam == "nixos" or "permission" in afk else "systemctl --user enable --now ydotool",
                         afk[0].upper() + afk[1:] + "."))

    desk = os.environ.get("XDG_CURRENT_DESKTOP", "")
    out.append(Check("kwin", "Window control", kwin_ok, "arranging windows into a grid (Windows page)", "",
                     "" if kwin_ok else f"Window layouts work on KDE Plasma, Hyprland and Sway (you use {desk or 'another desktop'})."
                     " Everything else works anywhere."))
    return out

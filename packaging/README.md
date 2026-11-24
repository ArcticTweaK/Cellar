# Packaging

- `cellar.desktop` - the desktop entry every package should install (it lists the `roblox-player:` / `roblox:`
  schemes so "Open the website's Play button with Cellar" can be turned on; Sober stays the default until then).
- `aur/PKGBUILD` - Arch User Repository package `cellar-git`.
- Nix: the flake in the repository root (`nix/package.nix`).

A package needs: Python 3.10+, PySide6 (with QtWebEngine for the browser login), requests, cryptography,
secretstorage; at run time flatpak (Sober), pasta (passt), unshare (util-linux), systemd-run, sway + wayvnc
(background mode), xdg-utils; optional ydotool, KWin.

#!/usr/bin/env bash
# Installs (or updates) Cellar for your user only - no sudo, nothing outside your home folder.
#   ./install.sh            install or update
#   ./uninstall.sh          remove it again (your accounts stay)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_home/cellar-app"        # the program; your accounts live in $data_home/cellar
bin_dir="$HOME/.local/bin"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- distro (for the hints below)
family=other
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" nixos "*) family=nixos ;;
        *" arch "*) family=arch ;;
        *" fedora "*) family=fedora ;;
        *" opensuse"* | *" suse "*) family=suse ;;
        *" debian "* | *" ubuntu "*) family=debian ;;
    esac
fi
install_cmd() {   # $@ = package names
    case "$family" in
        nixos) echo "NixOS: use the flake instead - nix run github:ArcticTweaK/Cellar" ;;
        arch) echo "sudo pacman -S --needed $*" ;;
        fedora) echo "sudo dnf install $*" ;;
        suse) echo "sudo zypper install $*" ;;
        debian) echo "sudo apt install $*" ;;
        *) echo "install these packages: $*" ;;
    esac
}
pkg_for_lib() {   # $1 = a library Qt could not find -> the package that has it on this distro
    local l="$1" n v
    case "$family" in
        fedora | suse) echo "'$l()(64bit)'" ;;          # dnf and zypper install a library by its own name
        arch)
            case "$l" in
                libGL.so* | libEGL.so*) echo libglvnd ;;
                libX11*) echo libx11 ;;
                libXcomposite*) echo libxcomposite ;;
                libXdamage*) echo libxdamage ;;
                libXrandr*) echo libxrandr ;;
                libXtst*) echo libxtst ;;
                libXext*) echo libxext ;;
                libXfixes*) echo libxfixes ;;
                libxcb-keysyms*) echo xcb-util-keysyms ;;
                libxcb-icccm*) echo xcb-util-wm ;;
                libxcb-image*) echo xcb-util-image ;;
                libxcb-render-util*) echo xcb-util-renderutil ;;
                libxcb-cursor*) echo xcb-util-cursor ;;
                libxcb-util*) echo xcb-util ;;
                libxcb*) echo libxcb ;;
                libxkbcommon-x11*) echo libxkbcommon-x11 ;;
                libxkbcommon*) echo libxkbcommon ;;
                libxkbfile*) echo libxkbfile ;;
                libnspr4*) echo nspr ;;
                libnss3* | libnssutil3* | libsmime3*) echo nss ;;
                libglib-2.0* | libgthread-2.0*) echo glib2 ;;
                libgbm*) echo mesa ;;
                libasound*) echo alsa-lib ;;
                libdbus-1*) echo dbus ;;
                libfontconfig*) echo fontconfig ;;
                libfreetype*) echo freetype2 ;;
                libgssapi_krb5*) echo krb5 ;;
                libbrotli*) echo brotli ;;
                libwayland*) echo wayland ;;
                libpulse*) echo libpulse ;;
                *) echo "$l" ;;
            esac ;;
        debian)
            case "$l" in
                libnss3* | libnssutil3* | libsmime3*) echo libnss3 ;;
                libglib-2.0* | libgthread-2.0*) echo libglib2.0-0t64 ;;
                libbrotli*) echo libbrotli1 ;;
                libasound*) echo libasound2t64 ;;
                *)  # Debian's rule: libXtst.so.6 -> libxtst6, libdbus-1.so.3 -> libdbus-1-3
                    n="${l%%.so*}"; v="${l#*.so}"; v="${v#.}"; n="${n,,}"; n="${n//_/-}"
                    if [ -n "$v" ] && [[ "$n" =~ [0-9]$ ]]; then n="$n-"; fi
                    echo "$n$v" ;;
            esac ;;
        *) echo "$l" ;;
    esac
}

# ---------------------------------------------------------------- Python
py="$(command -v python3 || true)"
[ -n "$py" ] || fail "Python 3 is missing. $(install_cmd python3)"
"$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
    fail "Cellar needs Python 3.10 or newer (found $("$py" -V 2>&1))."
"$py" -c 'import venv, ensurepip' 2>/dev/null ||
    fail "Python's venv module is missing. $(install_cmd python3-venv)"

bold "Installing Cellar into $app_dir"
if [ ! -x "$app_dir/venv/bin/python" ] || ! "$app_dir/venv/bin/python" -c '' 2>/dev/null; then
    rm -rf "$app_dir/venv"
    "$py" -m venv "$app_dir/venv"
fi
"$app_dir/venv/bin/python" -m pip install --quiet --upgrade pip
echo "Downloading Qt (PySide6) the first time takes a few minutes..."
"$app_dir/venv/bin/python" -m pip install --quiet --upgrade "$here"

# ---------------------------------------------------------------- command, menu entry, icon
mkdir -p "$bin_dir" "$data_home/applications" "$data_home/icons/hicolor/scalable/apps" \
         "$data_home/icons/hicolor/256x256/apps"
ln -sf "$app_dir/venv/bin/cellar" "$bin_dir/cellar"
install -m644 "$here/data/cellar.svg" "$data_home/icons/hicolor/scalable/apps/cellar.svg"
install -m644 "$here/cellar/data/cellar.png" "$data_home/icons/hicolor/256x256/apps/cellar.png"
cat > "$data_home/applications/cellar.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cellar
GenericName=Roblox account launcher
Comment=Run many Roblox accounts at once through Sober
Exec="$bin_dir/cellar"
Icon=cellar
Terminal=false
Categories=Game;Utility;
Keywords=roblox;sober;alts;accounts;multi;instance;macro;
StartupWMClass=cellar
EOF
command -v update-desktop-database >/dev/null && update-desktop-database -q "$data_home/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$data_home/icons/hicolor" || true

# ---------------------------------------------------------------- system libraries Qt needs
# (a desktop has nearly all of them; this names the ones that are missing instead of a crash later)
missing_libs="$("$app_dir/venv/bin/python" - <<'PY'
import glob, os, subprocess, PySide6
qt = os.path.join(os.path.dirname(PySide6.__file__), "Qt")
mods = ("Core Gui Widgets Network DBus Svg OpenGL WebEngineCore WebEngineWidgets WebChannel Qml Quick "
        "Positioning WaylandClient XcbQpa").split()
files = [f for m in mods for f in glob.glob(f"{qt}/lib/libQt6{m}.so.6")]
files += glob.glob(f"{qt}/plugins/platforms/libqxcb.so") + glob.glob(f"{qt}/plugins/platforms/libqwayland*.so")
files += glob.glob(f"{qt}/libexec/QtWebEngineProcess")
missing = set()
for f in files:
    out = subprocess.run(["ldd", f], capture_output=True, text=True).stdout
    missing.update(line.split()[0] for line in out.splitlines() if "not found" in line)
print(" ".join(sorted(missing)))
PY
)"

# ---------------------------------------------------------------- what else this computer needs
missing=()
pkgs=()
need() {   # $1 = command, $2 = package that brings it
    if ! command -v "$1" >/dev/null; then missing+=("$1"); pkgs+=("$2"); fi
}
need flatpak flatpak
need pasta passt
need unshare util-linux
need systemd-run systemd
need sway sway
need wayvnc wayvnc

echo
bold "Cellar $("$app_dir/venv/bin/python" -c 'import cellar; print(cellar.__version__)') is installed."
echo "Start it from your app menu, or run:  cellar"
case ":$PATH:" in *":$bin_dir:"*) ;; *) echo "($bin_dir is not on your PATH - use $bin_dir/cellar)" ;; esac

if [ -n "$missing_libs" ]; then
    lib_pkgs=()
    for l in $missing_libs; do lib_pkgs+=("$(pkg_for_lib "$l")"); done
    echo
    bold "Cellar can't start yet - Qt needs these system libraries: $missing_libs"
    echo "  $(install_cmd $(printf '%s\n' "${lib_pkgs[@]}" | sort -u))"
fi
if [ ${#missing[@]} -gt 0 ]; then
    echo
    bold "Still missing: ${missing[*]}"
    echo "  $(install_cmd "${pkgs[@]}")"
    echo "  (sway + wayvnc are only for background mode; pasta + unshare for running several accounts at once)"
fi
if command -v flatpak >/dev/null && ! flatpak info org.vinegarhq.Sober >/dev/null 2>&1; then
    echo
    bold "Sober (Roblox for Linux) is not installed yet:"
    echo "  flatpak install flathub org.vinegarhq.Sober"
    echo "  then start Sober once and log in."
fi

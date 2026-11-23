#!/usr/bin/env bash
# Removes the Cellar program. Your accounts, settings and alt profiles are kept.
set -euo pipefail

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"

rm -rf "$data_home/cellar-app"
rm -f "$HOME/.local/bin/cellar" \
      "$data_home/applications/cellar.desktop" \
      "$data_home/icons/hicolor/scalable/apps/cellar.svg" \
      "$data_home/icons/hicolor/256x256/apps/cellar.png" \
      "$config_home/autostart/cellar.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$data_home/applications" || true

echo "Cellar is removed."
echo "Your accounts and settings are still here - delete these folders too to remove everything:"
echo "  $data_home/cellar"
echo "  $config_home/cellar"
echo "  ${XDG_CACHE_HOME:-$HOME/.cache}/cellar"

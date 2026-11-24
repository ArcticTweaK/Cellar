"""Graphics Fast Flags (port of Gfx.cs).

Roblox only honours flags on its official allowlist (since Sep 2025). Under Sober they are
written into the "fflags" object of each per-account profile's config.json.
"""

import json
from typing import Dict, List, Tuple

from .models import AppSettings, GfxSettings

ALLOWLIST = [
    "DFIntCSGLevelOfDetailSwitchingDistance",
    "DFIntCSGLevelOfDetailSwitchingDistanceL12",
    "DFIntCSGLevelOfDetailSwitchingDistanceL23",
    "DFIntCSGLevelOfDetailSwitchingDistanceL34",
    "FFlagHandleAltEnterFullscreenManually",
    "DFFlagTextureQualityOverrideEnabled",
    "DFIntTextureQualityOverride",
    "FIntDebugForceMSAASamples",
    "DFFlagDisableDPIScale",
    "FFlagDebugSkyGray",
    "DFFlagDebugPauseVoxelizer",
    "DFIntDebugFRMQualityLevelOverride",
    "FIntFRMMaxGrassDistance",
    "FIntFRMMinGrassDistance",
    "FIntGrassMovementReducedMotionFactor",
]
_ALLOW = set(ALLOWLIST)

PRESETS = ["Default", "Light", "LowCpu", "Lowest", "Custom"]
PRESET_LABELS = {
    "Default": "Roblox default",
    "Light": "Light (lower textures, no anti-aliasing)",
    "LowCpu": "Low CPU (many accounts)",
    "Lowest": "Lowest (maximum accounts)",
    "Custom": "Custom",
}


def apply_preset(g: GfxSettings, key: str) -> None:
    g.quality, g.texture, g.msaa = 0, -1, 0
    g.no_grass = g.pause_voxelizer = g.gray_sky = g.low_csg = False
    if key == "Light":
        g.texture, g.msaa = 2, 1
    elif key == "LowCpu":
        g.quality, g.texture, g.msaa, g.no_grass = 3, 1, 1, True
    elif key == "Lowest":
        g.quality, g.texture, g.msaa = 1, 0, 1
        g.no_grass = g.pause_voxelizer = g.gray_sky = g.low_csg = True
    g.preset = key


def managed(g: GfxSettings) -> Dict[str, object]:
    d: Dict[str, object] = {}
    if g.quality > 0:
        d["DFIntDebugFRMQualityLevelOverride"] = str(g.quality)
    if g.texture >= 0:
        d["DFFlagTextureQualityOverrideEnabled"] = "True"
        d["DFIntTextureQualityOverride"] = str(g.texture)
    if g.msaa > 0:
        d["FIntDebugForceMSAASamples"] = str(g.msaa)
    if g.no_grass:
        d["FIntFRMMinGrassDistance"] = "0"
        d["FIntFRMMaxGrassDistance"] = "0"
    if g.pause_voxelizer:
        d["DFFlagDebugPauseVoxelizer"] = "True"
    if g.gray_sky:
        d["FFlagDebugSkyGray"] = "True"
    if g.low_csg:
        for k in ALLOWLIST[:4]:
            d[k] = "0"
    return d


def final(s: AppSettings, full_quality: bool = False, preset: str = "") -> Tuple[Dict[str, object], List[str]]:
    """Everything that will really be written: managed flags + the user's own (filtered).
    full_quality (your main): only the user's own flags, not the graphics preset meant for alts.
    preset: an account's own graphics preset (Edit account) instead of the global one."""
    ignored: List[str] = []
    g = s.gfx
    if preset and preset in PRESETS and preset != "Custom":
        import copy
        g = copy.copy(s.gfx)
        apply_preset(g, preset)
    d = {} if full_quality and not preset else managed(g)
    custom = (s.custom_flags or "").strip()
    if custom:
        try:
            c = json.loads(custom)
            if not isinstance(c, dict):
                ignored.append('(custom flags must be a JSON object like {"FlagName": "True"})')
            else:
                for k, v in c.items():
                    if k in _ALLOW or s.gfx.write_unlisted:
                        d[k] = v
                    else:
                        ignored.append(k)
        except ValueError:
            ignored.append("(custom flags are not valid JSON)")
    return d, ignored


def preview(s: AppSettings) -> str:
    f, ignored = final(s)
    out = json.dumps(f, indent=2) if f else "(nothing - Roblox runs with its own default settings)"
    for k in ignored:
        out += "\nNOT written (not on Roblox's list): " + k
    return out

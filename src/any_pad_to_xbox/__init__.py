"""Package constants and path helpers."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
# Prefer bundled assets next to package; fall back to repo assets/
REPO_ROOT = PACKAGE_ROOT.parents[1] if (PACKAGE_ROOT.parents[1] / "assets").exists() else PACKAGE_ROOT


def asset_path(*parts: str) -> Path:
    for base in (
        REPO_ROOT / "assets",
        PACKAGE_ROOT / "assets",
        Path(__file__).resolve().parents[2] / "assets",
    ):
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return (REPO_ROOT / "assets").joinpath(*parts)


def packaging_path(*parts: str) -> Path:
    for base in (
        REPO_ROOT / "packaging",
        PACKAGE_ROOT / "packaging",
        Path(__file__).resolve().parents[2] / "packaging",
    ):
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return (REPO_ROOT / "packaging").joinpath(*parts)


SYSTEM_CONFIG_DIR = Path("/etc/any-pad-to-xbox")
SYSTEM_PROFILES = SYSTEM_CONFIG_DIR / "profiles.json"
USER_CONFIG_DIR = Path.home() / ".config" / "any-pad-to-xbox"
USER_PROFILES = USER_CONFIG_DIR / "profiles.json"

RUNNER_PATH = Path("/usr/local/bin/any-pad-to-xbox-runner")
BRIDGE_PATH = Path("/usr/local/lib/any-pad-to-xbox/xpad_bridge.py")
SERVICE_PATH = Path("/etc/systemd/system/xboxdrv@.service")
UDEV_RULES_PATH = Path("/etc/udev/rules.d/99-any-pad-to-xbox.rules")

# Legacy — no longer required (bridge replaces xboxdrv)
XBOXDRV_BIN = Path("/usr/bin/xboxdrv")

# Dev-only: when True, bridge skips EVIOCGRAB so UI can also read the pad.
# Not exposed in the UI — set True only while debugging, then Enable once.
DIAG_NO_GRAB = False
DIAG_NO_GRAB_FLAG = SYSTEM_CONFIG_DIR / "diag_no_grab"

XBOX_BUTTONS = [
    "a", "b", "x", "y",
    "lb", "rb", "lt", "rt",
    "back", "start", "guide",
    "tl", "tr",
    "du", "dd", "dl", "dr",
]

XBOX_AXES = [
    "x1", "y1", "x2", "y2",
    "lt", "rt",
    "dpad_x", "dpad_y",
]

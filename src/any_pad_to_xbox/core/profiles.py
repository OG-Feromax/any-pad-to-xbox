"""Profile load/save and migration of known pads."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from any_pad_to_xbox import SYSTEM_PROFILES, USER_CONFIG_DIR, USER_PROFILES


# Migrated from the existing xboxdrv_instance.sh on this machine.
DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "0079:0006": {
        "name": "DragonRise Fliperama",
        "enabled": True,
        "slot": 1,
        "evdev_keymap": {
            "BTN_TOP": "x",
            "BTN_TRIGGER": "y",
            "BTN_THUMB2": "rb",
            "BTN_THUMB": "a",
            "BTN_BASE3": "back",
            "BTN_BASE4": "start",
            "BTN_BASE": "lb",
            "BTN_BASE2": "b",
            "BTN_TOP2": "lt",
            "BTN_PINKIE": "rt",
        },
        "evdev_absmap": {
            "ABS_X": "dpad_x",
            "ABS_Y": "dpad_y",
        },
        "axismap": ["-Y1=Y1", "-Y2=Y2"],
        "extra_opts": [],
    },
    "0810:0001": {
        "name": "USB Gamepad",
        "enabled": True,
        "slot": 2,
        "evdev_keymap": {
            "BTN_BASE3": "back",
            "BTN_BASE4": "start",
            "BTN_THUMB2": "a",
            "BTN_THUMB": "b",
            "BTN_TOP": "x",
            "BTN_TRIGGER": "y",
            "BTN_TOP2": "lb",
            "BTN_PINKIE": "rb",
        },
        "evdev_absmap": {
            "ABS_X": "dpad_x",
            "ABS_Y": "dpad_y",
        },
        "axismap": ["-Y1=Y1", "-Y2=Y2"],
        "extra_opts": [],
    },
    "1b4f:9206": {
        "name": "SparkFun Pro Micro",
        "enabled": True,
        "slot": 3,
        "evdev_keymap": {
            "BTN_9": "start",
            "BTN_0": "b",
            "BTN_1": "a",
            "BTN_6": "lb",
            "BTN_7": "rb",
            "BTN_8": "rt",
            "BTN_4": "du",
            "BTN_2": "dl",
            "BTN_3": "dd",
            "BTN_5": "dr",
        },
        "evdev_absmap": {
            "ABS_X": "x1",
            "ABS_Y": "y1",
            "ABS_RX": "x2",
            "ABS_RY": "y2",
        },
        "axismap": [],
        "extra_opts": ["--trigger-as-button", "--dpad-as-button"],
    },
}


@dataclass
class Profile:
    key: str  # vendor:product lowercase
    name: str
    enabled: bool = True
    slot: int = 1
    evdev_keymap: dict[str, str] = field(default_factory=dict)  # CODE -> xbox
    evdev_absmap: dict[str, str] = field(default_factory=dict)
    axismap: list[str] = field(default_factory=list)
    extra_opts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "slot": self.slot,
            "evdev_keymap": dict(self.evdev_keymap),
            "evdev_absmap": dict(self.evdev_absmap),
            "axismap": list(self.axismap),
            "extra_opts": list(self.extra_opts),
        }

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "Profile":
        return cls(
            key=key.lower(),
            name=data.get("name") or key,
            enabled=bool(data.get("enabled", True)),
            slot=int(data.get("slot", 1)),
            evdev_keymap=dict(data.get("evdev_keymap") or {}),
            evdev_absmap=dict(data.get("evdev_absmap") or {}),
            axismap=list(data.get("axismap") or []),
            extra_opts=list(data.get("extra_opts") or []),
        )

    def xbox_to_evdev_buttons(self) -> dict[str, str]:
        """Invert keymap: xbox button -> evdev code."""
        return {xbox: code for code, xbox in self.evdev_keymap.items()}

    def xbox_to_evdev_axes(self) -> dict[str, str]:
        return {xbox: code for code, xbox in self.evdev_absmap.items()}

    def has_mapping(self) -> bool:
        return bool(self.evdev_keymap or self.evdev_absmap)


def normalize_id(vendor: str | None, product: str | None) -> str | None:
    if not vendor or not product:
        return None
    return f"{vendor.lower().removeprefix('0x')}:{product.lower().removeprefix('0x')}"


def _load_file(path: Path) -> dict[str, Profile]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles_raw = raw.get("profiles", raw)
    out: dict[str, Profile] = {}
    for key, data in profiles_raw.items():
        out[key.lower()] = Profile.from_dict(key.lower(), data)
    return out


def load_profiles() -> dict[str, Profile]:
    """Prefer system profiles if present, else user, else built-in defaults."""
    if SYSTEM_PROFILES.exists():
        return _load_file(SYSTEM_PROFILES)
    if USER_PROFILES.exists():
        return _load_file(USER_PROFILES)
    return {
        key: Profile.from_dict(key, deepcopy(data))
        for key, data in DEFAULT_PROFILES.items()
    }


def ensure_user_profiles() -> dict[str, Profile]:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_PROFILES.exists():
        save_user_profiles(load_profiles())
    return _load_file(USER_PROFILES)


def save_user_profiles(profiles: dict[str, Profile]) -> Path:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "profiles": {k: p.to_dict() for k, p in sorted(profiles.items())},
    }
    USER_PROFILES.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return USER_PROFILES


def profiles_to_system_json(profiles: dict[str, Profile]) -> str:
    payload = {
        "version": 1,
        "require_remote_access": False,
        "profiles": {k: p.to_dict() for k, p in sorted(profiles.items())},
    }
    return json.dumps(payload, indent=2) + "\n"


def get_profile(profiles: dict[str, Profile], vendor: str | None, product: str | None) -> Profile | None:
    key = normalize_id(vendor, product)
    if not key:
        return None
    return profiles.get(key)


def empty_profile_for_device(vendor: str, product: str, name: str) -> Profile:
    key = normalize_id(vendor, product) or f"{vendor}:{product}"
    return Profile(key=key, name=name or key, enabled=False, slot=1)

"""Shared fixtures for the pure-logic tests (no root, no hardware, no Qt)."""

from __future__ import annotations

import pytest

from any_pad_to_xbox.core.profiles import Profile


def make_profile(
    key: str,
    name: str = "Test Pad",
    enabled: bool = True,
    buttons: dict[str, str] | None = None,
    axes: dict[str, str] | None = None,
) -> Profile:
    """Build a Profile; defaults to a mapped, enabled pad."""
    return Profile(
        key=key,
        name=name,
        enabled=enabled,
        slot=1,
        evdev_keymap=buttons if buttons is not None else {"BTN_THUMB": "a"},
        evdev_absmap=axes if axes is not None else {"ABS_X": "dpad_x"},
    )


@pytest.fixture
def two_pads() -> dict[str, Profile]:
    return {
        "0079:0006": make_profile("0079:0006", "DragonRise Fliperama"),
        "1b4f:9206": make_profile("1b4f:9206", "SparkFun Pro Micro"),
    }

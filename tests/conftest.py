"""Shared fixtures for the pure-logic tests (no root, no hardware, no Qt)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from any_pad_to_xbox.core.profiles import Profile


def root_imports(path: Path) -> set[str]:
    """Top-level module names imported by a file (relative imports ignored)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.add((node.module or "").split(".")[0])
    return {n for n in names if n}


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

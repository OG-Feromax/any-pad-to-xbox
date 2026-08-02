"""Reverse-map helpers: infer physical codes from virtual Xbox state + profile."""

from __future__ import annotations

from any_pad_to_xbox.core.evdev_monitor import (
    XBOX_ABS_FROM_EVDEV,
    XBOX_BTN_FROM_EVDEV,
    axis_is_active,
    phys_button_down,
)
from any_pad_to_xbox.core.profiles import Profile


def xbox_controls_from_virtual(
    virt_buttons: dict[str, bool],
    virt_axes: dict[str, float],
) -> tuple[set[str], dict[str, float]]:
    """Virtual evdev state → short xbox control ids + axis norms."""
    active: set[str] = set()
    axes: dict[str, float] = {}

    for code, pressed in virt_buttons.items():
        if not pressed:
            continue
        xbox = XBOX_BTN_FROM_EVDEV.get(code)
        if xbox:
            active.add(xbox)

    for code, val in virt_axes.items():
        xbox = XBOX_ABS_FROM_EVDEV.get(code)
        if not xbox:
            continue
        axes[xbox] = val
        if axis_is_active(code, val) or axis_is_active(xbox, val):
            active.add(xbox)
            if xbox == "dpad_x":
                active.add("dl" if val < 0 else "dr")
            elif xbox == "dpad_y":
                # On Xbox/HAT, -1 is up, +1 is down (same as linux hat)
                active.add("du" if val < 0 else "dd")
            elif xbox in {"lt", "rt"}:
                # Virtual triggers are analog, but many pads (DragonRise) map them
                # from digital buttons — still highlight as pressed when active.
                pass

    return active, axes


def physical_from_virtual(
    profile: Profile,
    virt_buttons: dict[str, bool],
    virt_axes: dict[str, float],
) -> tuple[dict[str, bool], dict[str, float], set[str], dict[str, float]]:
    """Infer physical raw codes from virtual pad + profile (info only under grab)."""
    xbox_active, xbox_axes = xbox_controls_from_virtual(virt_buttons, virt_axes)

    xbox_to_btn = {xbox: code for code, xbox in profile.evdev_keymap.items()}
    xbox_to_abs = {xbox: code for code, xbox in profile.evdev_absmap.items()}

    phys_buttons: dict[str, bool] = {}
    phys_axes: dict[str, float] = {}

    # Button-mapped xbox controls (incl. DragonRise lt/rt as BTN_*)
    for xbox, code in xbox_to_btn.items():
        if xbox in xbox_active:
            phys_buttons[code] = True

    # Axis-mapped controls (DragonRise dpad via ABS_X/ABS_Y)
    for xbox, code in xbox_to_abs.items():
        if xbox in {"dpad_x", "dpad_y"}:
            val = xbox_axes.get(xbox, 0.0)
            # Present as digital deflection for display even if physical was 0..255 stick
            phys_axes[code] = val
        elif xbox in xbox_axes:
            phys_axes[code] = xbox_axes[xbox]

    return phys_buttons, phys_axes, xbox_active, xbox_axes


def physical_mapped_from_direct(
    profile: Profile,
    phys_buttons: dict[str, bool],
    phys_axes: dict[str, float],
) -> tuple[set[str], dict[str, float]]:
    """Direct physical read → xbox highlights (learn / bridge offline)."""
    active: set[str] = set()
    axes: dict[str, float] = {}

    for code, xbox in profile.evdev_keymap.items():
        # Match aliases (BTN_TRIGGER ↔ BTN_JOYSTICK) so holds light while mapped.
        if phys_button_down(phys_buttons, code):
            active.add(xbox)

    for code, xbox in profile.evdev_absmap.items():
        val = phys_axes.get(code, 0.0)
        axes[xbox] = val
        # Physical DragonRise dpad uses ABS_X/Y 0..255 (bipolar-normalized in monitor
        # as stick). Treat like stick for direct mode.
        if axis_is_active(code, val) or axis_is_active(xbox, val):
            active.add(xbox)
            if xbox == "dpad_x":
                active.add("dl" if val < 0 else "dr")
            if xbox == "dpad_y":
                active.add("du" if val < 0 else "dd")

    return active, axes

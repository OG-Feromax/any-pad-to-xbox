"""Bootstrap helpers (status messaging)."""

from __future__ import annotations

from any_pad_to_xbox.core.system import SystemStatus, bridge_install_hint, check_system


def needs_setup(status: SystemStatus | None = None) -> bool:
    status = status or check_system()
    return not (status.uinput_ok and status.integration_installed)


def setup_summary(status: SystemStatus | None = None) -> str:
    status = status or check_system()
    lines = []
    lines.append(
        f"Virtual controller support: {'OK' if status.uinput_ok else 'missing'}"
    )
    lines.append(
        f"System component: {'OK' if status.integration_installed else 'needs install — ' + bridge_install_hint()}"
    )
    lines.append(
        f"Pad read permission: {'OK' if status.in_input_group else 'recommended'}"
    )
    for d in status.details:
        lines.append(f"• {d}")
    return "\n".join(lines)

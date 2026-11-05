"""System integration: detect, install, udev, systemctl via pkexec.

The shell that runs as root is rendered by `core.installer` — this module only decides
*which* profiles to hand it and which unit lifecycle to request.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from any_pad_to_xbox import (
    BRIDGE_PATH,
    DIAG_NO_GRAB,
    DIAG_NO_GRAB_FLAG,
    RUNNER_PATH,
    SERVICE_PATH,
    SYSTEM_CONFIG_DIR,
    SYSTEM_PROFILES,
    packaging_path,
)
from any_pad_to_xbox.core.installer import (
    BRIDGE_SRC,
    RUNNER_SRC,
    UNIT_SRC,
    InstallSources,
    _event_node,
    drift,
    failure_message,
    generate_artifacts,
    install_possible,
    render_install_script,
    run_privileged,
    system_components_present,
)
from any_pad_to_xbox.core.profiles import Profile, _load_file


@dataclass
class SystemStatus:
    bridge_installed: bool
    uinput_ok: bool
    integration_installed: bool
    runner_ok: bool
    service_ok: bool
    config_dir_ok: bool
    in_input_group: bool
    details: list[str]
    stale_paths: list[Path] = field(default_factory=list)
    diag_enabled: bool = False

    # Back-compat for older UI that checked xboxdrv_installed
    @property
    def xboxdrv_installed(self) -> bool:
        return self.bridge_installed

    @property
    def system_stale(self) -> bool:
        """The install exists but is not what this build would write."""
        return bool(self.stale_paths)


def check_system() -> SystemStatus:
    details: list[str] = []
    bridge_ok = BRIDGE_PATH.exists() or packaging_path("xpad_bridge.py").exists()
    uinput_ok = Path("/dev/uinput").exists()
    if not uinput_ok:
        details.append("Virtual controller support missing — try: sudo modprobe uinput")
    runner_ok = RUNNER_PATH.exists() and RUNNER_PATH.is_file()
    service_ok = False
    if SERVICE_PATH.exists():
        try:
            text = SERVICE_PATH.read_text(encoding="utf-8")
            service_ok = "any-pad-to-xbox-runner" in text
        except OSError:
            service_ok = False
    config_ok = SYSTEM_CONFIG_DIR.is_dir() and SYSTEM_PROFILES.exists()
    # Bridge file on disk after install is what matters for hotplug
    bridge_system = BRIDGE_PATH.exists()
    if not bridge_system:
        details.append("System helper not installed yet.")
    integration = runner_ok and service_ok and config_ok and bridge_system
    if not integration:
        details.append("System setup is not complete.")

    in_input = False
    try:
        out = subprocess.check_output(["id", "-nG"], text=True)
        in_input = "input" in out.split()
    except Exception:
        in_input = False
    if not in_input:
        details.append("User not in the input group (optional; recommended for live preview).")

    # A git pull moves the code; it does not move /etc. Without this the two can sit
    # apart forever with nothing in the UI saying so.
    stale: list[Path] = []
    # The mode is what the flag file says, independent of any drift: a no-grab bridge
    # duplicates the pad in games whether or not this app agrees with it.
    diag_enabled = DIAG_NO_GRAB_FLAG.exists()
    diag_pending = False
    if integration:
        try:
            found = drift(_load_file(SYSTEM_PROFILES))
        except (OSError, ValueError):
            found = []
        # The diagnostics flag is a mode someone switched on, not a file that went out
        # of date. Listing it as "system files are behind this app" reads like an install
        # problem and hides the thing that actually matters: the pad is not grabbed.
        stale = [p for p in found if p != DIAG_NO_GRAB_FLAG]
        diag_pending = DIAG_NO_GRAB_FLAG in found and not diag_enabled
        if stale:
            details.append(
                f"System files are behind this app ({len(stale)}): "
                + ", ".join(p.name for p in stale)
                + " — click Enable."
            )
    if diag_enabled:
        details.append(
            "Diagnostics mode is ON: the bridge is not grabbing the pad, so games list "
            "the physical device next to the Xbox one. Enable again without "
            "ANY_PAD_DIAG_NO_GRAB to go back to normal play."
        )
    elif diag_pending:
        details.append(
            "This app was started with ANY_PAD_DIAG_NO_GRAB, but /etc has no flag yet — "
            "Enable writes it."
        )

    return SystemStatus(
        bridge_installed=bridge_system or bridge_ok,
        uinput_ok=uinput_ok,
        integration_installed=integration,
        runner_ok=runner_ok,
        service_ok=service_ok,
        config_dir_ok=config_ok,
        in_input_group=in_input,
        details=details,
        stale_paths=stale,
        diag_enabled=diag_enabled,
    )


def install_integration() -> tuple[bool, str]:
    """Install runner, bridge, unit, config dir, udev rules — via pkexec.

    Keeps whatever profiles.json is already on disk and re-starts the bridge for pads
    that are plugged in right now.
    """
    sources = InstallSources.resolve()
    if not install_possible(sources, package_managed=system_components_present()):
        missing = [
            str(packaging_path(name))
            for name in (RUNNER_SRC, BRIDGE_SRC, UNIT_SRC)
            if not packaging_path(name).exists()
        ]
        return False, "Packaging files not found: " + ", ".join(missing)

    script = render_install_script(
        generate_artifacts(_load_file(SYSTEM_PROFILES)),
        sources=sources,
        restart_connected=True,
        preserve_existing_profiles=True,
    )
    result = run_privileged(script)
    if result.returncode != 0:
        return False, failure_message(result)
    return True, "System component installed."


def apply_profiles(
    profiles: dict[str, Profile],
    start_event: str | None = None,
    stop_event: str | None = None,
) -> tuple[bool, str]:
    """Write system profiles + udev, refresh what this checkout still carries.

    One pkexec for the whole operation — pass stop_event to halt a unit without a
    second password prompt (used by Disable).
    """
    script = render_install_script(
        generate_artifacts(profiles),
        start_event=start_event,
        stop_event=stop_event,
    )
    result = run_privileged(script)
    if result.returncode != 0:
        return False, failure_message(result)
    mode = " (diag no-grab)" if DIAG_NO_GRAB else ""
    return True, "Configuration applied" + mode + "."


def stop_instance(event_node: str) -> tuple[bool, str]:
    event = _event_node(event_node)
    script = f"""#!/bin/bash
set -euo pipefail
systemctl stop 'xboxdrv@{event}.service' 2>/dev/null || true
echo OK
"""
    result = run_privileged(script)
    if result.returncode != 0:
        return False, failure_message(result)
    return True, "Stopped."


def start_instance(event_node: str) -> tuple[bool, str]:
    event = _event_node(event_node)
    script = f"""#!/bin/bash
set -euo pipefail
systemctl start 'xboxdrv@{event}.service'
echo OK
"""
    result = run_privileged(script)
    if result.returncode != 0:
        return False, failure_message(result)
    return True, "Started."


def is_instance_active(event_node: str) -> bool:
    event = event_node.removeprefix("/dev/input/")
    try:
        r = subprocess.run(
            ["systemctl", "is-active", f"xboxdrv@{event}.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def xboxdrv_install_hint() -> str:
    """Legacy name — bridge needs no AUR package."""
    return "sudo modprobe uinput"


def bridge_install_hint() -> str:
    return "Click Install (asks for password)"

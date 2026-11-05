"""Single source of truth for the privileged install/apply script.

Every path that writes to `/etc`, `/usr/local` or the udev database renders through
`render_install_script`: the GUI's Install button, the GUI's Apply button,
`packaging/install-system.sh` and `python -m any_pad_to_xbox --reapply`. Having four
hand-written shell scripts instead of one renderer is what let them drift — the shell
installer never wrote the udev rules, so pulling a commit that changed rule generation
left the running system on the old rules with no error anywhere.

Two kinds of thing are treated differently on purpose:

* **Generated** artifacts (profiles, both udev rule files) are always installed — no
  entry point may skip them, since together they are what makes `/etc` describe the pads.
* **Source** artifacts (runner, bridge, unit) come from `packaging/` and are skipped when
  absent. An AUR install ships only the built wheel, which does not contain `packaging/`,
  and there the package manager has already placed those files in `/usr/local`.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from any_pad_to_xbox import (
    BRIDGE_PATH,
    DIAG_NO_GRAB,
    DIAG_NO_GRAB_FLAG,
    RUNNER_PATH,
    SERVICE_PATH,
    SYSTEM_CONFIG_DIR,
    SYSTEM_PROFILES,
    UDEV_HIDE_RULES_PATH,
    UDEV_RULES_PATH,
    packaging_path,
)
from any_pad_to_xbox.core.profiles import Profile, profiles_to_system_json
from any_pad_to_xbox.core.udev import generate_hide_rules, generate_udev_rules

RUNNER_SRC = "xboxdrv_runner.py"
BRIDGE_SRC = "xpad_bridge.py"
UNIT_SRC = "xboxdrv@.service"

_EVENT_NODE_RE = re.compile(r"event\d+")


def _event_node(event: str) -> str:
    """Device node from a path like `/dev/input/event20`, validated.

    Both `apply_profiles` and the Enable/Disable helpers paste this into a script that
    root executes, so anything that is not `event<digits>` is refused rather than
    interpolated.
    """
    node = event.removeprefix("/dev/input/").strip("/")
    if not _EVENT_NODE_RE.fullmatch(node):
        raise ValueError(f"not an event device name: {event!r}")
    return node


@dataclass(frozen=True)
class InstallSources:
    """Repo files copied into place, when this install still has them."""

    runner: Path | None = None
    bridge: Path | None = None
    unit: Path | None = None

    @classmethod
    def resolve(cls) -> "InstallSources":
        def existing(name: str) -> Path | None:
            path = packaging_path(name)
            return path if path.exists() else None

        return cls(
            runner=existing(RUNNER_SRC),
            bridge=existing(BRIDGE_SRC),
            unit=existing(UNIT_SRC),
        )


@dataclass(frozen=True)
class GeneratedArtifacts:
    """Content of the files the install writes, carried inside the script itself."""

    profiles_json: str
    udev_rules: str
    hide_rules: str


def generate_artifacts(profiles: dict[str, Profile]) -> GeneratedArtifacts:
    return GeneratedArtifacts(
        profiles_json=profiles_to_system_json(profiles),
        udev_rules=generate_udev_rules(profiles),
        hide_rules=generate_hide_rules(profiles),
    )


TMP_VAR = "aptx_tmp"
_HEREDOC_MARKERS = {
    "profiles_json": "APTX_PROFILES_JSON",
    "udev_rules": "APTX_UDEV_BRIDGE_RULES",
    "hide_rules": "APTX_UDEV_HIDE_RULES",
}


def _heredoc(name: str, dest: str, content: str) -> str:
    """Embed `content` in the script at `dest`, unexpanded and unmodified.

    The generated files have to travel *inside* the script: the renderer's own temp dir
    is gone by the time root runs it (`install-system.sh` captures stdout first), so a
    path to a staged file would be a dangling reference.
    """
    marker = _HEREDOC_MARKERS[name]
    while any(line.strip() == marker for line in content.splitlines()):
        marker += "X"
    body = content if content.endswith("\n") else content + "\n"
    return f'cat > "{dest}" <<\u0027{marker}\u0027\n{body}{marker}\n'


def purge_legacy_xboxdrv_bash() -> str:
    """Shell snippet: disable old xboxdrv paths so only our bridge owns the pad."""
    return r"""
# --- purge legacy xboxdrv (binary daemon + old hotplug) ---
systemctl stop xboxdrv.service 2>/dev/null || true
systemctl disable xboxdrv.service 2>/dev/null || true
systemctl mask xboxdrv.service 2>/dev/null || true
# Kill leftover userspace xboxdrv binaries (not our python bridge)
pkill -x xboxdrv 2>/dev/null || true
sleep 0.2
pkill -x xboxdrv 2>/dev/null || true
# Retire old hotplug script / udev if still present
if [[ -f /usr/local/bin/xboxdrv_instance.sh ]]; then
  mv -f /usr/local/bin/xboxdrv_instance.sh /usr/local/bin/xboxdrv_instance.sh.bak
fi
if [[ -f /etc/udev/rules.d/99-joystick.rules ]]; then
  # Only retire if it looks like the old xboxdrv hotplug rule
  if grep -qE 'xboxdrv_instance|xboxdrv@' /etc/udev/rules.d/99-joystick.rules 2>/dev/null; then
    mv -f /etc/udev/rules.d/99-joystick.rules /etc/udev/rules.d/99-joystick.rules.bak
  fi
fi
"""


# Runs as root inside the generated script; stdlib only, reads the profiles it just wrote.
RESTART_CONNECTED_PY = r'''
import json, subprocess
from pathlib import Path
data = json.loads(Path("/etc/any-pad-to-xbox/profiles.json").read_text())
wanted = {
    k.lower() for k, p in (data.get("profiles") or {}).items()
    if p.get("enabled", True) and (p.get("evdev_keymap") or p.get("evdev_absmap"))
}
if not wanted:
    raise SystemExit(0)
for ev in Path("/dev/input").glob("event*"):
    try:
        out = subprocess.check_output(
            ["udevadm", "info", "--query=property", f"--name={ev}"], text=True
        )
    except Exception:
        continue
    vendor = product = None
    for line in out.splitlines():
        if line.startswith("ID_VENDOR_ID="):
            vendor = line.split("=", 1)[1].lower()
        elif line.startswith("ID_MODEL_ID="):
            product = line.split("=", 1)[1].lower()
    if not vendor or not product:
        continue
    if f"{vendor}:{product}" not in wanted:
        continue
    unit = f"xboxdrv@{ev.name}.service"
    subprocess.run(["systemctl", "stop", unit], check=False, capture_output=True)
    subprocess.run(["systemctl", "reset-failed", unit], check=False, capture_output=True)
    r = subprocess.run(["systemctl", "start", unit], check=False, capture_output=True, text=True)
    print(f"start {unit}: {r.returncode}")
'''


def _unit_lifecycle_bash(event: str, *, start: bool) -> str:
    node = _event_node(event)
    if not start:
        return (
            f"systemctl stop 'xboxdrv@{node}.service' 2>/dev/null || true\n"
            f"systemctl reset-failed 'xboxdrv@{node}.service' 2>/dev/null || true\n"
        )
    return f"""
systemctl stop 'xboxdrv@{node}.service' 2>/dev/null || true
systemctl reset-failed 'xboxdrv@{node}.service' 2>/dev/null || true
# Give previous grab holder time to release the fd
sleep 0.6
systemctl start 'xboxdrv@{node}.service'
sleep 0.4
if ! systemctl is-active --quiet 'xboxdrv@{node}.service'; then
  echo "bridge failed to stay active for {node}" >&2
  systemctl status 'xboxdrv@{node}.service' --no-pager -l >&2 || true
  journalctl -u 'xboxdrv@{node}.service' -n 30 --no-pager >&2 || true
  exit 1
fi
"""


def render_install_script(
    artifacts: GeneratedArtifacts,
    *,
    sources: InstallSources | None = None,
    start_event: str | None = None,
    stop_event: str | None = None,
    restart_connected: bool = False,
    preserve_existing_profiles: bool = False,
    diag_no_grab: bool = DIAG_NO_GRAB,
) -> str:
    """Build the complete script that makes `/etc` match the given profiles.

    Self-contained and copy-pasteable: the generated files ride in as heredocs and the
    scratch dir is created by the script itself, so `install-system.sh` may capture this
    text and run it later. The artifact set is fixed — generated files always installed,
    sources only when this checkout still carries them — and every path goes through
    `shlex.quote` because the result runs as root.
    """
    sources = sources if sources is not None else InstallSources.resolve()
    q = shlex.quote
    tmp = f"${{{TMP_VAR}}}"

    payload = (
        _heredoc("profiles_json", f"{tmp}/{SYSTEM_PROFILES.name}", artifacts.profiles_json)
        + _heredoc("udev_rules", f"{tmp}/{UDEV_RULES_PATH.name}", artifacts.udev_rules)
        + _heredoc("hide_rules", f"{tmp}/{UDEV_HIDE_RULES_PATH.name}", artifacts.hide_rules)
    )

    installs = ""
    if sources.runner:
        installs += f'install -m 755 {q(str(sources.runner))} {q(str(RUNNER_PATH))}\n'
    if sources.bridge:
        installs += (
            f'install -d -m 755 {q(str(BRIDGE_PATH.parent))}\n'
            f'install -m 755 {q(str(sources.bridge))} {q(str(BRIDGE_PATH))}\n'
        )
    if sources.unit:
        installs += f'install -m 644 {q(str(sources.unit))} {q(str(SERVICE_PATH))}\n'

    staged_profiles = f'{tmp}/{SYSTEM_PROFILES.name}'
    profiles_install = f'install -m 644 "{staged_profiles}" {q(str(SYSTEM_PROFILES))}\n'
    if preserve_existing_profiles:
        profiles_install = (
            f'if [[ ! -f {q(str(SYSTEM_PROFILES))} ]]; then\n'
            f'  {profiles_install.rstrip()}\n'
            f'fi\n'
        )

    diag_cmd = f'touch {q(str(DIAG_NO_GRAB_FLAG))}\n' if diag_no_grab else f'rm -f {q(str(DIAG_NO_GRAB_FLAG))}\n'

    actions = purge_legacy_xboxdrv_bash()
    if start_event:
        actions += _unit_lifecycle_bash(start_event, start=True)
    else:
        if stop_event:
            actions += _unit_lifecycle_bash(stop_event, start=False)
        if restart_connected:
            actions += f"python3 - <<'PY'\n{RESTART_CONNECTED_PY}\nPY\n"

    return f"""#!/bin/bash
set -euo pipefail
{TMP_VAR}="$(mktemp -d)"
trap 'rm -rf "{tmp}"' EXIT
{payload}install -d -m 755 {q(str(SYSTEM_CONFIG_DIR))}
install -d -m 755 {q(str(RUNNER_PATH.parent))}
{installs}{profiles_install}install -m 644 "{tmp}/{UDEV_RULES_PATH.name}" {q(str(UDEV_RULES_PATH))}
install -m 644 "{tmp}/{UDEV_HIDE_RULES_PATH.name}" {q(str(UDEV_HIDE_RULES_PATH))}
{diag_cmd}modprobe uinput 2>/dev/null || true
udevadm control --reload
# "change" re-evaluates the hide rules for pads already plugged in without
# firing the ACTION=="add" bridge rules again.
udevadm trigger --subsystem-match=input --action=change
systemctl daemon-reload
{actions}
echo OK
"""


def run_privileged(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(script)
        path = fh.name
    os.chmod(path, 0o700)
    try:
        return subprocess.run(
            ["pkexec", "bash", path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def failure_message(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or f"exit {result.returncode}").strip()

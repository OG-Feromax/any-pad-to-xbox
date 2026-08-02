#!/usr/bin/env python3
"""Hotplug runner: stdlib only. Loads profile and runs the uinput Xbox bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROFILES_PATH = Path("/etc/any-pad-to-xbox/profiles.json")
LOG_PATH = Path("/var/log/any-pad-to-xbox.log")
# Present → bridge runs with --no-grab (PHYS+VIRT timestamp pairing)
DIAG_NO_GRAB_FLAG = Path("/etc/any-pad-to-xbox/diag_no_grab")
# Bridge ground-truth log (PHYS in + EMIT out); enabled whenever diag flag is present
BRIDGE_DIAG_LOG = Path("/tmp/any-pad-bridge.diag")
BRIDGE_CANDIDATES = [
    Path("/usr/local/lib/any-pad-to-xbox/xpad_bridge.py"),
    Path(__file__).resolve().parent / "xpad_bridge.py",
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line, end="", file=sys.stderr)


def find_bridge() -> Path | None:
    for path in BRIDGE_CANDIDATES:
        if path.is_file():
            return path
    return None


def udev_ids(event: str) -> tuple[str | None, str | None]:
    path = f"/dev/input/{event}" if not event.startswith("/") else event
    try:
        out = subprocess.check_output(
            ["udevadm", "info", "--query=property", f"--name={path}"],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        log(f"udevadm failed: {exc}")
        return None, None
    vendor = product = None
    for line in out.splitlines():
        if line.startswith("ID_VENDOR_ID="):
            vendor = line.split("=", 1)[1].lower()
        elif line.startswith("ID_MODEL_ID="):
            product = line.split("=", 1)[1].lower()
    return vendor, product


def load_profile(vendor: str, product: str) -> dict | None:
    if not PROFILES_PATH.exists():
        log(f"missing {PROFILES_PATH}")
        return None
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    if data.get("require_remote_access"):
        env_path = Path("/etc/environment")
        remote = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("remote_access="):
                    remote = line.split("=", 1)[1].strip().strip('"') == "true"
        if not remote:
            log("require_remote_access set but remote_access!=true — skipping")
            return None
    key = f"{vendor}:{product}"
    profiles = data.get("profiles", {})
    profile = profiles.get(key) or profiles.get(key.lower())
    if not profile:
        log(f"no profile for {key}")
        return None
    if not profile.get("enabled", True):
        log(f"profile {key} disabled")
        return None
    return profile


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} eventN", file=sys.stderr)
        return 2
    event = sys.argv[1].removeprefix("/dev/input/")
    log(f"start bridge for {event}")
    vendor, product = udev_ids(event)
    if not vendor or not product:
        log("could not resolve vendor/product")
        return 1
    log(f"id {vendor}:{product}")
    profile = load_profile(vendor, product)
    if not profile:
        return 1
    bridge = find_bridge()
    if not bridge:
        log("xpad_bridge.py not found")
        return 1
    # Hand off to bridge with inline profile (avoids a second udev round-trip race)
    argv = [
        sys.executable,
        str(bridge),
        event,
        "--profile-json",
        json.dumps(profile, separators=(",", ":")),
    ]
    # Test-phase / explicit flag: allow PHYS+VIRT dual read for latency logs
    if DIAG_NO_GRAB_FLAG.exists():
        argv.append("--no-grab")
        argv.extend(["--diag-log", str(BRIDGE_DIAG_LOG)])
        log(f"diag: --no-grab + --diag-log {BRIDGE_DIAG_LOG}")
    log(
        "exec: "
        + " ".join(argv[:3])
        + (" --no-grab" if DIAG_NO_GRAB_FLAG.exists() else "")
        + (" --diag-log" if DIAG_NO_GRAB_FLAG.exists() else "")
        + " --profile-json <…>"
    )
    os.execv(sys.executable, argv)


if __name__ == "__main__":
    sys.exit(main())

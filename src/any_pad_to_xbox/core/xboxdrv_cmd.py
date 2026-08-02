"""Build bridge command lines from profiles (preview in UI)."""

from __future__ import annotations

import json
import shlex

from any_pad_to_xbox.core.profiles import Profile

BRIDGE_BIN = "/usr/local/lib/any-pad-to-xbox/xpad_bridge.py"


def build_bridge_argv(profile: Profile, event_node: str) -> list[str]:
    event = event_node if event_node.startswith("/dev/") else f"/dev/input/{event_node}"
    return [
        "python3",
        BRIDGE_BIN,
        event,
        "--profile-json",
        json.dumps(profile.to_dict(), separators=(",", ":")),
    ]


def build_bridge_shell(profile: Profile, event_node: str) -> str:
    return " ".join(shlex.quote(p) for p in build_bridge_argv(profile, event_node))


# Back-compat aliases used by older UI imports
build_xboxdrv_argv = build_bridge_argv
build_xboxdrv_shell = build_bridge_shell

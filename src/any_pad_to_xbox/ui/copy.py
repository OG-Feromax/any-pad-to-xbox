"""Centralized English UI strings (happy path: no jargon)."""

from __future__ import annotations

TAGLINE = "Turn any gamepad into an Xbox 360 controller on Linux."

# System traffic light
SYSTEM_READY = "System ready"
SYSTEM_ATTENTION = "Needs attention"
SYSTEM_REQUIRED = "System setup required"
INSTALL = "Install (asks for password)"
RECHECK = "Recheck"
WHY_PASSWORD = "Why password?"
WHY_PASSWORD_BODY = (
    "A one-time install places a small helper on your system so plugged-in "
    "pads can appear as Xbox controllers. Your desktop will ask for your "
    "password (administrator approval)."
)
CHECK_COMPONENT = "System component"
CHECK_UINPUT = "Virtual controller support"
CHECK_INPUT_GROUP = "Pad read permission (recommended)"
INSTALL_CANCELLED = "Install cancelled — try again."
INSTALLING = "Installing… (password prompt may appear)"
SETUP_FIRST = "Set up the system first (use Install above)."

# Devices
CONNECTED_PADS = "Connected controllers"
REFRESH = "Refresh"
NO_PADS = "No controller detected. Plug one in, then click Refresh."
BADGE_UNMAPPED = "Unmapped"
BADGE_READY = "Ready"
BADGE_ACTIVE = "Active"
SELECT_PAD = "Select a controller"

# Primary actions
START_MAPPING = "Start mapping"
ENABLE = "Enable"
DISABLE = "Disable"
REMAP = "Remap"
TEST = "Test"
ADVANCED = "Advanced"
CANCEL = "Cancel"

# Status / tips
TIP_IDLE = "Select a controller, map its buttons, then Enable."
TIP_UNMAPPED = "Click Start mapping, then press each button on your pad when prompted."
TIP_READY = "Mapping saved. Click Enable to apply it to the virtual Xbox pad."
TIP_ACTIVE = "Active — games should see an Xbox 360 pad. Press Test to verify."
TIP_TEST = "Press buttons on your pad — the diagram should light up green."
TIP_TEST_OFF = "Enable the controller first, then test."
TIP_MAP_DONE = "Mapping ready — want to test?"
VIRTUAL_OFF = "Virtual Xbox off"
VIRTUAL_ON = "Virtual Xbox on"
LEARNING = "Learning"
PRESSED = "Pressed"

# Map mode
MAP_TITLE = "Map buttons"
PRESS_FOR = "Press the button on your pad that should be {label}"
PRESS_AXIS = "Move the stick or trigger for {label}"
SKIP = "Skip"
PAUSE_TITLE = "Turn off virtual pad to remap?"
PAUSE_BODY = (
    "Your mapping is saved in your user folder — no admin needed for that.\n\n"
    "While the pad is Active, the virtual Xbox holds exclusive access to the "
    "hardware, so we can't hear your presses. We'll turn it off once for this "
    "remap session (asks for password), then you map freely.\n\n"
    "Click Enable when you're done."
)
PAUSE_FAIL = "Could not pause"
MAPPED_OK = "Mapped {label} — saved. Click Enable to apply (restarts the virtual pad)."
MAPPED_OK_MORE = "Mapped {label}. Keep remapping, then click Enable when done."
MAP_AXIS_HINT = "That target needs a stick or trigger — move an axis."
DEVICE_GONE = "Controller disconnected."
CLEAR_CONFIRM_TITLE = "Clear mapping?"
CLEAR_CONFIRM = "Remove all button assignments for this controller?"
CLEARED = "Mapping cleared."
ENABLE_NO_ID = "This device has no USB id — cannot enable system-wide."
ENABLE_NO_MAP = "Map at least one button before enabling."
ENABLE_OK = "Enabled. The diagram lights up from the real virtual Xbox pad."
ENABLE_FAIL = "Could not enable"
DISABLE_OK = "Disabled."
APPLY_REMAP_TITLE = "Apply new mapping?"
APPLY_REMAP_BODY = (
    "{label} is saved in your profile.\n\n"
    "Click Enable to restart the virtual pad with the new mapping "
    "(games only see the change after that)."
)
SLOT_LABEL = "Xbox player slot"
CLEAR_MAPPING = "Clear mapping"
READABLE_MAP = "Current mapping"
DIAGNOSTICS = "Diagnostics"
WHAT_INSTALLED = "What gets installed"
WHAT_INSTALLED_BODY = (
    "Install copies a helper script, a background service unit, and udev rules "
    "so connecting a mapped pad starts the virtual Xbox controller automatically."
)
EMPTY_MAP = "(nothing mapped yet)"
LEGEND_HINT = "Amber = learning · Green = live output · Blue = pad direct (diag)"

# Checklist groups
ESSENTIALS = [
    ("a", "A"),
    ("b", "B"),
    ("x", "X"),
    ("y", "Y"),
    ("lb", "LB"),
    ("rb", "RB"),
    ("lt", "LT"),
    ("rt", "RT"),
    ("back", "Back"),
    ("start", "Start"),
    ("du", "D-pad Up"),
    ("dd", "D-pad Down"),
    ("dl", "D-pad Left"),
    ("dr", "D-pad Right"),
]

AXIS_TARGETS = frozenset({"x1", "y1", "x2", "y2", "lt", "rt", "dpad_x", "dpad_y"})
BUTTON_TARGETS = frozenset({
    "a", "b", "x", "y", "lb", "rb", "back", "start", "guide",
    "tl", "tr", "du", "dd", "dl", "dr",
})

FRIENDLY_CODE = {
    "BTN_A": "Button A",
    "BTN_B": "Button B",
    "BTN_X": "Button X",
    "BTN_Y": "Button Y",
    "BTN_TL": "Button LB",
    "BTN_TR": "Button RB",
    "BTN_SELECT": "Select",
    "BTN_START": "Start",
    "BTN_MODE": "Guide",
    "BTN_THUMB": "Thumb",
    "BTN_THUMB2": "Thumb 2",
    "BTN_TOP": "Top",
    "BTN_TOP2": "Top 2",
    "BTN_PINKIE": "Pinkie",
    "BTN_BASE": "Base",
    "BTN_BASE2": "Base 2",
    "BTN_BASE3": "Base 3",
    "BTN_BASE4": "Base 4",
    "BTN_TRIGGER": "Trigger",
    "BTN_JOYSTICK": "Joystick",
    "ABS_X": "Axis X",
    "ABS_Y": "Axis Y",
    "ABS_Z": "Axis Z",
    "ABS_RX": "Axis RX",
    "ABS_RY": "Axis RY",
    "ABS_RZ": "Axis RZ",
    "ABS_HAT0X": "Hat X",
    "ABS_HAT0Y": "Hat Y",
}


def friendly_code(code: str) -> str:
    if code in FRIENDLY_CODE:
        return FRIENDLY_CODE[code]
    if code.startswith("BTN_"):
        return code.replace("BTN_", "Button ")
    if code.startswith("ABS_"):
        return code.replace("ABS_", "Axis ")
    return code


def xbox_label(xbox: str) -> str:
    for key, label in ESSENTIALS:
        if key == xbox:
            return label
    return xbox.upper()

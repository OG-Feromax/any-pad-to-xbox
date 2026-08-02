#!/bin/bash
# One-shot migration / system install for this machine (requires sudo).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing system integration..."
sudo "$ROOT/packaging/install-system.sh"

echo "Installing migrated profiles..."
sudo install -m 644 "$ROOT/data/profiles.example.json" /etc/any-pad-to-xbox/profiles.json

echo "Generating udev rules..."
export PATH="${HOME}/.local/bin:${PATH}"
cd "$ROOT"
uv run python - <<'PY'
from pathlib import Path
from any_pad_to_xbox.core.profiles import load_profiles
from any_pad_to_xbox.core.system import generate_udev_rules
Path("/tmp/99-any-pad-to-xbox.rules").write_text(generate_udev_rules(load_profiles()), encoding="utf-8")
print("wrote /tmp/99-any-pad-to-xbox.rules")
PY
sudo install -m 644 /tmp/99-any-pad-to-xbox.rules /etc/udev/rules.d/99-any-pad-to-xbox.rules

if [[ -f /etc/udev/rules.d/99-joystick.rules ]]; then
  sudo mv -n /etc/udev/rules.d/99-joystick.rules /etc/udev/rules.d/99-joystick.rules.bak
  echo "Backed up old 99-joystick.rules"
fi
if [[ -f /usr/local/bin/xboxdrv_instance.sh ]]; then
  sudo mv -n /usr/local/bin/xboxdrv_instance.sh /usr/local/bin/xboxdrv_instance.sh.bak
  echo "Backed up old xboxdrv_instance.sh"
fi

sudo udevadm control --reload
sudo systemctl daemon-reload

mkdir -p "$HOME/.local/share/applications"
sed "s|/home/feromax/Builds/any-pad-to-xbox|$ROOT|g" \
  "$ROOT/packaging/any-pad-to-xbox.desktop" \
  > "$HOME/.local/share/applications/any-pad-to-xbox.desktop"

echo
echo "Done. Launch with: $ROOT/scripts/any-pad-to-xbox"
echo "Or use the desktop entry: Any Pad to Xbox"
echo "Keep /etc/udev/rules.d/99-ignore-led-controller.rules untouched."

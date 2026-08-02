#!/bin/bash
# Install system integration (run via pkexec or as root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install -d -m 755 /etc/any-pad-to-xbox
install -d -m 755 /usr/local/bin
install -d -m 755 /usr/local/lib/any-pad-to-xbox
install -m 755 "$ROOT/packaging/xboxdrv_runner.py" /usr/local/bin/any-pad-to-xbox-runner
install -m 755 "$ROOT/packaging/xpad_bridge.py" /usr/local/lib/any-pad-to-xbox/xpad_bridge.py
install -m 644 "$ROOT/packaging/xboxdrv@.service" /etc/systemd/system/xboxdrv@.service

if [[ ! -f /etc/any-pad-to-xbox/profiles.json ]]; then
  if [[ -f "$ROOT/data/profiles.example.json" ]]; then
    install -m 644 "$ROOT/data/profiles.example.json" /etc/any-pad-to-xbox/profiles.json
  else
    echo '{"version":1,"require_remote_access":false,"profiles":{}}' > /etc/any-pad-to-xbox/profiles.json
  fi
fi

modprobe uinput 2>/dev/null || true

# Purge legacy xboxdrv so only our bridge owns mapped pads
systemctl stop xboxdrv.service 2>/dev/null || true
systemctl disable xboxdrv.service 2>/dev/null || true
systemctl mask xboxdrv.service 2>/dev/null || true
pkill -x xboxdrv 2>/dev/null || true
sleep 0.2
pkill -x xboxdrv 2>/dev/null || true
if [[ -f /usr/local/bin/xboxdrv_instance.sh ]]; then
  mv -f /usr/local/bin/xboxdrv_instance.sh /usr/local/bin/xboxdrv_instance.sh.bak
fi
if [[ -f /etc/udev/rules.d/99-joystick.rules ]] && grep -qE 'xboxdrv_instance|xboxdrv@' /etc/udev/rules.d/99-joystick.rules 2>/dev/null; then
  mv -f /etc/udev/rules.d/99-joystick.rules /etc/udev/rules.d/99-joystick.rules.bak
fi

systemctl daemon-reload
udevadm control --reload
echo "any-pad-to-xbox system integration installed (uinput bridge; legacy xboxdrv masked)."

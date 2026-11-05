#!/bin/bash
# Install system integration (run via pkexec or as root).
#
# Deliberately contains no install logic: the commands come from the app's own installer
# module, so this entry point cannot fall behind the GUI. The gap used to be real — this
# file never wrote the udev rules, so pulling a commit that changed rule generation left
# /etc on the old rules with no error anywhere.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 not found — set PYTHON=/path/to/python3 (3.11+)" >&2
  exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "$PYTHON is older than 3.11, the project's minimum" >&2
  exit 1
fi

# Rendered from the checkout in $ROOT, not from any copy installed site-wide.
script="$(PYTHONPATH="$ROOT/src" "$PYTHON" -m any_pad_to_xbox --print-script)"

if [[ -z "$script" ]]; then
  echo "installer renderer produced nothing — refusing to run an empty script" >&2
  exit 1
fi

bash -c "$script"
echo "any-pad-to-xbox system integration installed (uinput bridge, udev rules; legacy xboxdrv masked)."

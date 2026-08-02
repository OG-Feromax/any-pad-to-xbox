"""First-run / system status — re-exports SystemStatusBar for compatibility."""

from __future__ import annotations

from any_pad_to_xbox.ui.system_status import SystemStatusBar

# Back-compat alias used by older imports
SetupBanner = SystemStatusBar

__all__ = ["SystemStatusBar", "SetupBanner"]

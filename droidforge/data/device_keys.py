"""Device-side keys droidforge reads (never writes)."""

from __future__ import annotations

# The system property behind Developer options > "Disable permission monitoring" / "Disable system optimization"
# (INCIDENT-2026-09-25). Recorded 2026-09-25 by the owner on the Neo 8 (RMX8899, Android 16): flipping the switch
# on changed `persist.sys.permission.enable` from `true` to `false` (docs/COMMANDS.md "Health probes").
# `true` = monitoring on (switch off, healthy); `false` = switch on. Missing on a ROM -> "unknown".
# droidforge only ever READS it (guard FORBIDDEN refuses any write).
PERMISSION_MONITORING_PROP = "persist.sys.permission.enable"
PERMISSION_MONITORING_CONFIRMED = True

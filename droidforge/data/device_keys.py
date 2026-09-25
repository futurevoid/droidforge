"""Device-side keys droidforge reads (never writes)."""

from __future__ import annotations

# The setting behind Developer options > "Disable permission monitoring" / "Disable system optimization"
# (INCIDENT-2026-09-25). The real key is recorded in Phase 9 (docs/PLAN.md, docs/COMMANDS.md "Health probes").
# Until then this placeholder is only answered by the simulator; on a real phone it reads `null` -> "unknown".
# droidforge only ever READS it (guard FORBIDDEN refuses any write).
PERMISSION_MONITORING_NS = "global"
PERMISSION_MONITORING_KEY = "droidforge_placeholder_permission_monitoring_disabled"
PERMISSION_MONITORING_CONFIRMED = False

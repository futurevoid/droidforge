"""Header bar: device / profile / root / Shizuku / verbosity / dry-run / expert state (R-12.1)."""

from __future__ import annotations

from typing import Dict

from textual.widgets import Static


class DeviceBar(Static):
    DEFAULT_CSS = """
    DeviceBar { height: 1; background: $primary-background; color: $text; padding: 0 1; }
    """

    def __init__(self, **kw: object) -> None:
        super().__init__("droidforge - connecting...", **kw)  # type: ignore[arg-type]
        self.fields: Dict[str, str] = {}

    def show(self, **fields: str) -> None:
        self.fields.update({k: v for k, v in fields.items() if v is not None})
        order = ("device", "profile", "root", "shizuku", "verbosity", "dry_run", "expert")
        parts = [self.fields[k] for k in order if self.fields.get(k)]
        self.update("  |  ".join(parts) or "droidforge")


class ExpertBanner(Static):
    DEFAULT_CSS = """
    ExpertBanner { height: 1; background: red; color: white; text-style: bold; padding: 0 1; }
    ExpertBanner.hidden { display: none; }
    """

    def __init__(self, **kw: object) -> None:
        super().__init__("EXPERT MODE - locked packages can be selected: one per batch, type the full name, health "
                         "check after each, reboot check afterwards.", **kw)  # type: ignore[arg-type]

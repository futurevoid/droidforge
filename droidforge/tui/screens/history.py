"""Backup & History (R-11.2, R-11.3): undo an entry, roll back to a point, restore droidforge's own changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static

from droidforge.features import backup
from droidforge.tui.screens.base import Section
from droidforge.tui.widgets.tables import HistoryTable

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class HistorySection(Section):
    DEFAULT_CSS = "HistorySection HistoryTable { height: 20; }"

    def compose(self) -> ComposeResult:
        yield Label("[b]Backup & History[/b]  - undo is itself a previewed, health-checked plan")
        yield HistoryTable(id="history")
        with Horizontal(classes="buttons"):
            yield Button("Refresh", id="refresh")
            yield Button("Undo selected", id="undo")
            yield Button("Roll back to here", id="rollback")
            yield Button("Restore changes since session start", id="restore")
        yield Static("", id="backups", markup=False)

    def refresh_from(self, app: "DroidforgeApp") -> None:
        s = app.session
        if s is None:
            return
        self.query_one(HistoryTable).load(s.history.entries())
        files = backup.list_backups(s.device.serial or "device")
        self.query_one("#backups", Static).update(
            f"{len(files)} backup(s) of this phone" + (f"; newest: {files[-1].name}" if files else ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.dapp
        s = app.session
        if s is None:
            return
        bid = event.button.id
        entry = self.query_one(HistoryTable).current_id()
        if bid == "refresh":
            self.refresh_from(app)
        elif bid == "undo" and entry:
            app.run_plan(lambda: s.history.undo([entry]))
        elif bid == "rollback" and entry:
            app.run_plan(lambda: s.history.rollback_to(entry))
        elif bid == "restore":
            sessions = [f for f in backup.list_backups(s.device.serial or "device") if f.name.endswith("-session.json")]
            if not sessions:
                app.notify("No session backup yet", severity="warning")
                return
            app.run_plan(lambda: backup.restore_plan(s.device, s.history, sessions[-1]))

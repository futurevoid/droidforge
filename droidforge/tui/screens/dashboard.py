"""Dashboard: device info + doctor (R-2.8), reboot check (R-11.9), expert mode toggle."""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static

from droidforge import config
from droidforge.features import doctor
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.features.fix import Breakage
    from droidforge.tui.app import DroidforgeApp


class DashboardSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Dashboard[/b]")
        with Horizontal(classes="buttons"):
            yield Button("Run doctor", id="doctor")
            yield Button("Reboot & re-check", id="reboot-check")
            yield Button("Expert mode", id="expert")
            yield Button("HTML report", id="report")
        yield Static("", id="alerts")
        yield Static("Connecting...", id="doctor-report", markup=False)

    def refresh_from(self, app: "DroidforgeApp", explicit: bool = False) -> None:
        s = app.session
        if s is None:
            return
        app.background(lambda: doctor.run(s.device, s.profile, s.history, backup_dir=config.paths().sub("backups"),
                                          mark_time=explicit), self.show_report)

    def show_report(self, rep: doctor.DoctorReport) -> None:
        self.query_one("#doctor-report", Static).update("\n".join(rep.lines()))
        self.dapp.dashboard_alerts(rep)

    def show_alerts(self, alerts: List["Breakage"]) -> None:
        box = self.query_one("#alerts", Static)
        if not alerts:
            box.update("")
            return
        lines = ["[b red]Unresolved alerts (listed until the phone is healthy):[/]"]
        for b in alerts:
            lines += [f"[red]! {escape(b.title)}[/]"] + [f"    {escape(w)}" for w in b.what_broke()]
        box.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "doctor":
            self.refresh_from(self.dapp, explicit=True)
        elif event.button.id == "reboot-check":
            self.dapp.run_reboot_check()
        elif event.button.id == "expert":
            self.dapp.action_toggle_expert()
        elif event.button.id == "report" and self.dapp.session is not None:
            from droidforge.engine import report
            s = self.dapp.session
            self.dapp.background(lambda: report.write(s.device, s.history, "", True),
                                 lambda path: self.dapp.notify(f"Report written: {path}"))

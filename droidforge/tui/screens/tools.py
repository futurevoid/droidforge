"""Tools (R-2.3, R-9.x): Shizuku; scrcpy, logcat, activity launcher and shell pane join in P5.3 - P5.6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static

from droidforge.features import shizuku
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class ToolsSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Tools[/b]")
        yield Label("Shizuku", classes="subtitle")
        yield Static("", id="shizuku-status", markup=False)
        with Horizontal(classes="buttons"):
            yield Button("Install Shizuku (official GitHub release)", id="shizuku-install")
            yield Button("Start Shizuku", id="shizuku-start", variant="primary")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev = self.device
        if dev is not None:
            app.background(lambda: shizuku.status(dev),
                           lambda st: self.query_one("#shizuku-status", Static).update(f"Shizuku: {st}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        if event.button.id == "shizuku-install":
            app.run_plan(lambda: shizuku.install_plan(dev), on_done=lambda rep: self.refresh_from(app))
        elif event.button.id == "shizuku-start":
            app.run_plan(lambda: shizuku.start_plan(dev), on_done=lambda rep: self.refresh_from(app))

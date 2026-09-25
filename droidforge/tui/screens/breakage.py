"""Breakage alert modal (R-12.5) - cannot be missed: what broke, what droidforge changed just before, and
Fix it / Details / Ignore (plus Open Developer options when the permission-monitoring switch is on)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from droidforge.features.fix import Breakage


class BreakageAlert(ModalScreen[str]):
    DEFAULT_CSS = """
    BreakageAlert { align: center middle; background: $error 30%; }
    BreakageAlert > Vertical { width: 95%; height: 85%; border: heavy $error; background: $surface; padding: 0 1; }
    BreakageAlert #alert-title { color: $error; text-style: bold; }
    BreakageAlert #alert-body { height: 1fr; }
    BreakageAlert #alert-details.hidden { display: none; }
    BreakageAlert #alert-buttons { height: 3; }
    """

    def __init__(self, b: Breakage) -> None:
        super().__init__()
        self.b = b

    def compose(self) -> ComposeResult:
        b = self.b
        with Vertical():
            yield Label(f"!! {b.title or 'Something on the phone broke'} !!", id="alert-title")
            with VerticalScroll(id="alert-body"):
                yield Static("\n".join(b.lines()[2:]), id="alert-text", markup=False)
                details = []
                if b.repair is not None:
                    details += ["", "Repair plan:"] + [f"  {s.cmd}" for s in b.repair.steps] + \
                               [f"  ! {n}" for n in b.repair.notes]
                yield Static("\n".join(details) or "-", id="alert-details", classes="hidden", markup=False)
            with Horizontal(id="alert-buttons"):
                if b.explained:
                    yield Button("Fix it", id="fix", variant="error")
                if b.switch_on:
                    yield Button("Open Developer options", id="devopts", variant="warning")
                yield Button("Details", id="details")
                yield Button("Ignore", id="ignore")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "details":
            self.query_one("#alert-details").toggle_class("hidden")
            return
        self.dismiss(event.button.id or "ignore")

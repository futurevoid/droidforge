"""Small modal screens: device picker, first-run limits note (P16), message box."""

from __future__ import annotations

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static

LIMITS = (
    "droidforge's limits, said once:\n\n"
    "It cannot promise that a ROM never reacts badly to a supported, reversible change - the 2026-09-25 incident "
    "came from a change that 'worked'. What it guarantees: only allowlisted commands, only what you picked, every "
    "change reversible, damage checked right after each batch, the plan stopped and undo offered.\n\n"
    "It never turns on developer options such as 'Disable permission monitoring', never changes the device "
    "language, and never changes how the phone looks.\n\n"
    "Last resort if the phone ever misbehaves: Settings > search 'Reset' > Reset all settings (keeps apps and data)."
)


class MessageBox(ModalScreen[None]):
    DEFAULT_CSS = """
    MessageBox { align: center middle; }
    MessageBox > Vertical { width: 80%; max-width: 100; height: auto; border: thick $primary; padding: 1 2;
                            background: $surface; }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, id="title")
            yield Static(self.body, id="body")
            yield Button("OK", id="ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


EXPERT_WARNING = ("Expert mode lets you select locked packages: SystemUI, telephony, Play services, WebView, UI "
                  "infrastructure, the current keyboard and launcher, UAD Unsafe. Breaking these can mean no calls, "
                  "no keyboard, no home screen or a boot loop.\n\nEach locked package runs alone, you type its full "
                  "name, the health check runs after it, and a reboot check is offered afterwards.")


class ConfirmBox(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmBox { align: center middle; }
    ConfirmBox > Vertical { width: 80%; max-width: 100; height: auto; border: thick $error; padding: 1 2;
                            background: $surface; }
    ConfirmBox Horizontal { height: 3; }
    """

    def __init__(self, title: str, body: str, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self.title_text, self.body, self.yes, self.no = title, body, yes, no

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self.title_text}[/b]")
            yield Static(self.body)
            with Horizontal():
                yield Button(self.yes, id="yes", variant="error")
                yield Button(self.no, id="no", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class LimitsNote(MessageBox):
    def __init__(self) -> None:
        super().__init__("Before you start", LIMITS)


class DevicePicker(ModalScreen[Optional[str]]):
    DEFAULT_CSS = """
    DevicePicker { align: center middle; }
    DevicePicker > Vertical { width: 60; height: auto; border: thick $primary; padding: 1 2; background: $surface; }
    """

    def __init__(self, rows: List[Tuple[str, str]]) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Pick a phone")
            yield OptionList(*[f"{s}  ({st})" for s, st in self.rows], id="devices")
            yield Button("Cancel", id="cancel")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        serial, state = self.rows[event.option_index]
        self.dismiss(serial if state == "device" else None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

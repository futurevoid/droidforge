"""Keyboard (R-3.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static

from droidforge.features import keyboard
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class KeyboardSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Keyboard[/b]")
        yield Static("", id="kbd-status", classes="status", markup=False)
        with Horizontal(classes="buttons"):
            yield Button("Switch to Gboard", id="gboard")
            yield Button("Chinese keyboards off", id="chinese")
            yield Button("Remove secure keyboard", id="secure")
            yield Button("Gboard languages", id="gboard-lang")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev = self.device
        if dev is not None:
            app.background(lambda: (keyboard.current_ime(dev), keyboard.enabled_imes(dev)), self.show)

    def show(self, res: Tuple[str, List[str]]) -> None:
        cur, enabled = res
        lines = [f"Current keyboard: {cur or '-'}", "Enabled keyboards:"]
        lines += [f"  {i}{'  (Chinese)' if keyboard.is_chinese_ime(i) else ''}" for i in enabled]
        self.query_one("#kbd-status", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        dev = self.device
        if dev is None:
            return
        builders = {"gboard": keyboard.gboard_plan, "chinese": keyboard.chinese_imes_plan,
                    "secure": keyboard.secure_keyboard_plan, "gboard-lang": keyboard.gboard_languages_plan}
        fn = builders.get(event.button.id or "")
        if fn is not None:
            self.dapp.run_plan(lambda: fn(dev))

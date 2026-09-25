"""Base for main-area sections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class Section(VerticalScroll):
    DEFAULT_CSS = """
    Section { padding: 0 1; }
    Section .buttons { height: auto; }
    Section .buttons Button { margin: 0 1 0 0; }
    Section .status { padding: 0 0 1 0; }
    Section .subtitle { text-style: bold; padding: 1 0 0 0; }
    """

    def __init__(self, section_id: str, title: str) -> None:
        super().__init__(id=section_id)
        self.title_text = title

    @property
    def dapp(self) -> "DroidforgeApp":
        return self.app  # type: ignore[return-value]

    @property
    def device(self) -> Any:
        s = self.dapp.session
        return s.device if s is not None else None

    def compose(self) -> ComposeResult:
        yield Label(f"[b]{self.title_text}[/b]")
        yield Static("", classes="body")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        pass

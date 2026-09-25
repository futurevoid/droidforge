"""Shared bits for feature sections: a searchable picker of the phone's user apps."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, SelectionList
from textual.widgets.selection_list import Selection


class AppPicker(Vertical):
    """Multi-select of installed user apps with a search box and an optional status marker per app.
    The selection survives filtering."""

    DEFAULT_CSS = """
    AppPicker { height: 16; }
    AppPicker SelectionList { height: 1fr; }
    """

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self.pkgs: List[str] = []
        self.status: Dict[str, str] = {}
        self.names: Dict[str, str] = {}
        self.chosen: Set[str] = set()
        self.filter_text = ""
        self._redrawing = False

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search apps", classes="app-search")
        yield SelectionList[str]()

    def load(self, pkgs: List[str], status: Optional[Dict[str, str]] = None,
             names: Optional[Dict[str, str]] = None) -> None:
        self.pkgs = list(pkgs)
        self.status = dict(status or {})
        self.names = dict(names or {})
        self.chosen &= set(self.pkgs)
        self._redraw()

    def _redraw(self) -> None:
        sl = self.query_one(SelectionList)
        f = self.filter_text.lower()
        self._redrawing = True
        try:
            sl.clear_options()
            sl.add_options([Selection(self._prompt(p), p, p in self.chosen, id=p) for p in self.pkgs
                            if not f or f in p.lower() or f in self.names.get(p, "").lower()])
        finally:
            self.call_after_refresh(self._done_redrawing)

    def set_names(self, names: Dict[str, str]) -> None:
        """Names arriving in the background: change the row texts in place. Rebuilding the list here reset the
        cursor while the user was moving through it, so key presses seemed to be lost."""
        sl = self.query_one(SelectionList)
        for p, name in names.items():
            if self.names.get(p) == name:
                continue
            self.names[p] = name
            try:
                sl.replace_option_prompt(p, self._prompt(p))
            except Exception:  # noqa: BLE001 - not shown right now (filtered out)
                pass

    def _prompt(self, p: str) -> Text:
        t = Text()
        if self.names.get(p):
            t.append(self.names[p], style="bold")
            t.append("  ")
        t.append(p, style="dim" if self.names.get(p) else "")
        if self.status.get(p):
            t.append(f"   [{self.status[p]}]")
        return t

    def _done_redrawing(self) -> None:
        self._redrawing = False

    def on_input_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self._redraw()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        """Visible rows follow the list; picks hidden by the search stay picked."""
        if self._redrawing:
            return
        sl = event.selection_list
        visible = {sl.get_option_at_index(i).value for i in range(sl.option_count)}
        self.chosen = (self.chosen - visible) | set(sl.selected)

    def select(self, pkg: str) -> None:
        self.chosen.add(pkg)
        self._redraw()

    def picked(self) -> List[str]:
        return [p for p in self.pkgs if p in self.chosen]

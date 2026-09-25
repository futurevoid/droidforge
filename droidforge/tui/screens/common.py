"""Shared bits for feature sections: a searchable picker of the phone's user apps."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, SelectionList


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
        self.chosen: Set[str] = set()
        self.filter_text = ""
        self._redrawing = False

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search apps", classes="app-search")
        yield SelectionList[str]()

    def load(self, pkgs: List[str], status: Optional[Dict[str, str]] = None) -> None:
        self.pkgs = list(pkgs)
        self.status = dict(status or {})
        self.chosen &= set(self.pkgs)
        self._redraw()

    def _redraw(self) -> None:
        sl = self.query_one(SelectionList)
        f = self.filter_text.lower()
        self._redrawing = True
        try:
            sl.clear_options()
            sl.add_options([(p + (f"   [{self.status[p]}]" if self.status.get(p) else ""), p, p in self.chosen)
                            for p in self.pkgs if not f or f in p.lower()])
        finally:
            self.call_after_refresh(self._done_redrawing)

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

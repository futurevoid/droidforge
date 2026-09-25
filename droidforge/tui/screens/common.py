"""Shared bits for feature sections: a picker of the phone's user apps."""

from __future__ import annotations

from typing import List

from textual.widgets import SelectionList


class AppPicker(SelectionList[str]):
    """Multi-select of installed user apps (the only apps most Phase 4 actions should target)."""

    DEFAULT_CSS = "AppPicker { height: 12; }"

    def load(self, pkgs: List[str]) -> None:
        picked = set(self.selected)
        self.clear_options()
        self.add_options([(p, p, p in picked) for p in pkgs])

    def picked(self) -> List[str]:
        return list(self.selected)

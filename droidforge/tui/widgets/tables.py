"""PackageTable (UAD tier, status, description, multi-select, filter) and HistoryTable."""

from __future__ import annotations

from typing import Iterable, List, Optional, Set

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input

from droidforge.engine.history import Entry
from droidforge.features.debloat import Row

TIER_STYLE = {"Recommended": "green", "Advanced": "yellow", "Expert": "magenta", "Unsafe": "red"}
STATUS_STYLE = {"enabled": "green", "disabled": "yellow", "suspended": "yellow", "removed": "red"}
LOCK_TEXT = {"locked": ("locked", "white on red"), "guarded": ("guarded", "yellow"), "keep": ("keep", "cyan"),
             "expert": ("expert", "magenta")}


class PackageTable(Vertical):
    DEFAULT_CSS = """
    PackageTable { height: 1fr; }
    PackageTable DataTable { height: 1fr; }
    """

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.rows: List[Row] = []
        self.selected: Set[str] = set()
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter packages (name or description)", id="pkg-filter")
        t: DataTable = DataTable(id="pkg-table", cursor_type="row", zebra_stripes=True)
        t.add_columns(" ", "status", "rating", "package", "note", "description")
        yield t

    def load(self, rows: Iterable[Row]) -> None:
        self.rows = list(rows)
        self.selected &= {r.pkg for r in self.rows}
        self._redraw()

    def visible_rows(self) -> List[Row]:
        f = self.filter_text.lower()
        return [r for r in self.rows if not f or f in r.pkg.lower() or f in r.description.lower()]

    def _redraw(self) -> None:
        t = self.query_one(DataTable)
        t.clear()
        for r in self.visible_rows():
            lock = LOCK_TEXT.get(r.verdict.level)
            t.add_row(Text("[x]" if r.pkg in self.selected else "[ ]", style="bold" if r.pkg in self.selected else ""),
                      Text(r.status, style=STATUS_STYLE.get(r.status, "")),
                      Text(r.tier or "-", style=TIER_STYLE.get(r.tier, "dim")), r.pkg,
                      Text(lock[0], style=lock[1]) if lock else "", r.description, key=r.pkg)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pkg-filter":
            self.filter_text = event.value
            self._redraw()

    def toggle(self, pkg: str) -> None:
        if pkg in self.selected:
            self.selected.discard(pkg)
        else:
            self.selected.add(pkg)
        self._redraw()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.toggle(str(event.row_key.value))

    def select_all(self, pkgs: Iterable[str]) -> None:
        self.selected |= set(pkgs)
        self._redraw()

    def clear_selection(self) -> None:
        self.selected.clear()
        self._redraw()

    def selection(self) -> List[str]:
        return [r.pkg for r in self.rows if r.pkg in self.selected]


class HistoryTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns("time", "plan", "step", "command", "result")

    def load(self, entries: Iterable[Entry]) -> None:
        self.clear()
        for e in reversed(list(entries)):
            res = "dry-run" if e.dry_run else "undone" if e.undone else "ok" if e.ok else "failed"
            style = {"ok": "green", "failed": "red", "undone": "dim", "dry-run": "yellow"}[res]
            self.add_row(e.ts.replace("T", " ")[:19], e.plan_title[:28], e.label[:40], e.cmd, Text(res, style=style),
                         key=e.id)

    def current_id(self) -> Optional[str]:
        if self.row_count == 0:
            return None
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return str(key.value) if key.value else None

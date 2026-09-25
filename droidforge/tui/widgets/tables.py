"""PackageTable (UAD tier, status, description, multi-select, filter) and HistoryTable."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

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
        yield Input(placeholder="filter packages (app name, package or description)", id="pkg-filter")
        t: DataTable = DataTable(id="pkg-table", cursor_type="row", zebra_stripes=True)
        cols = t.add_columns(" ", "status", "rating", "app name", "package", "note", "description")
        self._check_col, self._name_col = cols[0], cols[3]
        yield t

    def load(self, rows: Iterable[Row]) -> None:
        self.rows = list(rows)
        self.selected &= {r.pkg for r in self.rows}
        self._redraw()

    def visible_rows(self) -> List[Row]:
        f = self.filter_text.lower()
        return [r for r in self.rows
                if not f or f in r.pkg.lower() or f in r.name.lower() or f in r.description.lower()]

    def _redraw(self) -> None:
        """Rebuild the rows (new data / filter). The cursor stays on the same package when it is still shown."""
        t = self.query_one(DataTable)
        current = self._cursor_pkg()
        t.clear()
        visible = self.visible_rows()
        for r in visible:
            lock = LOCK_TEXT.get(r.verdict.level)
            t.add_row(self._check_cell(r.pkg),
                      Text(r.status, style=STATUS_STYLE.get(r.status, "")),
                      Text(r.tier or "-", style=TIER_STYLE.get(r.tier, "dim")), self._name_cell(r), r.pkg,
                      Text(lock[0], style=lock[1]) if lock else "", r.description, key=r.pkg)

        keys = [r.pkg for r in visible]
        if current in keys:
            t.move_cursor(row=keys.index(current))

    def _cursor_pkg(self) -> Optional[str]:
        t = self.query_one(DataTable)
        if not t.row_count:
            return None
        try:
            return str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)
        except Exception:  # noqa: BLE001 - no valid cursor yet
            return None

    def _check_cell(self, pkg: str) -> Text:
        on = pkg in self.selected
        return Text("[x]" if on else "[ ]", style="bold" if on else "")

    def _update_checks(self, pkgs: Iterable[str]) -> None:
        """Change only the checkbox cells - the cursor never moves (Enter used to jump back to the top)."""
        t = self.query_one(DataTable)
        for p in pkgs:
            try:
                t.update_cell(p, self._check_col, self._check_cell(p))
            except Exception:  # noqa: BLE001 - filtered out right now
                pass

    def _name_cell(self, r: Row) -> Text:
        return Text(r.name, style="bold") if r.name else Text("...", style="dim")

    def set_names(self, names: Dict[str, str]) -> None:
        """Fill in app names as they arrive (background), without rebuilding the table."""
        t = self.query_one(DataTable)
        for r in self.rows:
            if r.pkg in names and names[r.pkg] != r.name:
                r.name = names[r.pkg]
                try:
                    t.update_cell(r.pkg, self._name_col, self._name_cell(r))
                except Exception:  # noqa: BLE001 - the row is filtered out right now
                    pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pkg-filter":
            self.filter_text = event.value
            self._redraw()

    def toggle(self, pkg: str) -> None:
        if pkg in self.selected:
            self.selected.discard(pkg)
        else:
            self.selected.add(pkg)
        self._update_checks([pkg])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.toggle(str(event.row_key.value))

    def select_all(self, pkgs: Iterable[str]) -> None:
        pkgs = set(pkgs)
        self.selected |= pkgs
        self._update_checks(pkgs)

    def clear_selection(self) -> None:
        was = set(self.selected)
        self.selected.clear()
        self._update_checks(was)

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

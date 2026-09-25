"""Collapsible bottom pane with the live adb traffic at the current verbosity (fed by a log.py sink)."""

from __future__ import annotations

from collections import deque
from typing import Deque

from textual.widgets import RichLog

from droidforge.log import LogLine

STYLE = {"cmd": "cyan", "exit": "dim", "out": "dim", "more": "dim", "err": "yellow", "trace": "dim",
         "info": "cyan", "ok": "green", "warn": "yellow", "error": "bold red"}


class LogPane(RichLog):
    """Thread-safe: the sink only appends to a deque; a timer drains it on the UI thread."""

    DEFAULT_CSS = """
    LogPane { height: 12; border-top: solid $primary; }
    LogPane.hidden { display: none; }
    """

    def __init__(self, **kw: object) -> None:
        super().__init__(highlight=False, markup=False, wrap=False, max_lines=5000, **kw)  # type: ignore[arg-type]
        self.pending: Deque[LogLine] = deque()

    def sink(self, line: LogLine) -> None:
        self.pending.append(line)

    def on_mount(self) -> None:
        self.set_interval(0.1, self.drain)

    def drain(self) -> None:
        from rich.text import Text
        while self.pending:
            line = self.pending.popleft()
            self.write(Text(line.text, style=STYLE.get(line.kind, "")))

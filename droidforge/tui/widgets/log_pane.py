"""Collapsible bottom pane with the live adb traffic at the current verbosity (fed by a log.py sink)."""

from __future__ import annotations

from collections import deque
from typing import Deque

from textual.widgets import RichLog

from droidforge.log import LogLine

STYLE = {"cmd": "cyan", "exit": "dim", "out": "dim", "more": "dim", "err": "yellow", "trace": "dim",
         "info": "cyan", "ok": "green", "warn": "yellow", "error": "bold red"}


LINES_PER_TICK = 60    # per 0.1 s tick - leaves the UI thread free for key presses
MAX_PENDING = 1000


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
        """UI thread, every 0.1 s: write a bounded number of lines so a flood of output can never freeze the
        screen; beyond MAX_PENDING the oldest waiting lines are dropped (the debug log keeps everything)."""
        from rich.text import Text
        dropped = 0
        while len(self.pending) > MAX_PENDING:
            self.pending.popleft()
            dropped += 1
        if dropped:
            self.write(Text(f"    ... {dropped} log line(s) skipped to keep the screen responsive - full text in "
                            "the debug log", style="dim"))
        n = min(len(self.pending), LINES_PER_TICK)
        if n:   # one write per tick: a write per line cost the screen thread more than the lines themselves
            batch = [self.pending.popleft() for _ in range(n)]
            self.write(Text("\n").join(Text(ln.text, style=STYLE.get(ln.kind, "")) for ln in batch))

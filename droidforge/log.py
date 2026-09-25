"""Verbosity-filtered logging with pluggable sinks and an always-complete debug log (P3, R-11.6).

On-screen format (ported from legacy/cnrom_fix.py):

    $ adb -s SERIAL shell 'pm list packages'
        -> exit 0 | 41 ms | 3 line(s) out
        | package:com.example
        ! some stderr line
      . a decision or internal step

Levels: 1 = results only; 2 = + commands, exit, timing, first 15 output lines, decisions;
3 = ULTRA (default) = + full output, internal (plumbing) calls, cache hits, timestamps.
The debug log file gets everything regardless of the level.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, TextIO

LEVEL_NAMES = {1: "results only", 2: "commands + exit codes + timing + first 15 lines + decisions",
               3: "ULTRA - everything, full output, internal calls, cache hits, timestamps"}
OUTPUT_LINES_AT_2 = 15
DEBUG_LOG_MAX = 20 * 1024 * 1024


@dataclass(frozen=True)
class LogLine:
    kind: str    # cmd | exit | out | err | more | trace | info | ok | warn | error
    text: str    # already formatted, without colour


Sink = Callable[[LogLine], None]


def ascii_safe(text: str) -> str:
    """CLI output stays ASCII: non-ASCII characters (device output) are escaped."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


class Logger:
    def __init__(self, verbosity: int = 3, debug_path: Optional[Path] = None) -> None:
        self._verbosity = 3
        self.verbosity = verbosity
        self.debug_path = debug_path
        self._sinks: List[Sink] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ config
    @property
    def verbosity(self) -> int:
        return self._verbosity

    @verbosity.setter
    def verbosity(self, v: int) -> None:
        self._verbosity = min(3, max(1, int(v)))

    def cycle(self) -> int:
        self.verbosity = self._verbosity % 3 + 1
        return self._verbosity

    def add_sink(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def remove_sink(self, sink: Sink) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    # ------------------------------------------------------------------ plumbing
    def _ts(self) -> str:
        return f"{datetime.now():%H:%M:%S} " if self._verbosity >= 3 else ""

    def _emit(self, kind: str, text: str, level: int) -> None:
        if self._verbosity < level:
            return
        line = LogLine(kind, text)
        for s in list(self._sinks):
            try:
                s(line)
            except Exception as ex:  # a broken sink must never stop a plan
                self.dbg(f"SINK ERROR {s!r}: {ex}")

    def dbg(self, text: str) -> None:
        """Full, untruncated debug record - always written, whatever the verbosity."""
        if self.debug_path is None:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        body = "".join(f"{stamp}  {ln}\n" for ln in (str(text).splitlines() or [""]))
        with self._lock:
            try:
                self.debug_path.parent.mkdir(parents=True, exist_ok=True)
                if self.debug_path.exists() and self.debug_path.stat().st_size > DEBUG_LOG_MAX:
                    self.debug_path.replace(self.debug_path.with_suffix(".log.1"))
                with self.debug_path.open("a", encoding="utf-8") as f:
                    f.write(body)
            except OSError:
                pass

    # ------------------------------------------------------------------ results (level 1)
    def info(self, msg: str) -> None:
        self.dbg(f"INFO  {msg}")
        self._emit("info", f"[*] {msg}", 1)

    def ok(self, msg: str) -> None:
        self.dbg(f"OK    {msg}")
        self._emit("ok", f"[+] {msg}", 1)

    def warn(self, msg: str) -> None:
        self.dbg(f"WARN  {msg}")
        self._emit("warn", f"[!] {msg}", 1)

    def error(self, msg: str) -> None:
        self.dbg(f"ERROR {msg}")
        self._emit("error", f"[x] {msg}", 1)

    # ------------------------------------------------------------------ narration
    def trace(self, msg: str, lvl: int = 2) -> None:
        """Narrate a decision or internal step (lvl 2) or a cache hit / plumbing detail (lvl 3)."""
        self.dbg(f"TRACE {msg}")
        self._emit("trace", f"  {self._ts()}. {msg}", lvl)

    def command(self, pretty: str, plumbing: bool = False) -> None:
        self.dbg(f"RUN   {pretty}")
        self._emit("cmd", f"  {self._ts()}$ {pretty}", 3 if plumbing else 2)

    def result(self, code: int, ms: int, out: str, err: str, plumbing: bool = False) -> None:
        olines, elines = out.splitlines(), err.splitlines()
        self.dbg(f"EXIT  {code}  ({ms} ms, {len(olines)} stdout / {len(elines)} stderr lines)")
        for ln in olines:
            self.dbg(f"  out | {ln}")
        for ln in elines:
            self.dbg(f"  err | {ln}")
        lvl = 3 if plumbing else 2
        if self._verbosity < lvl:
            return
        errs = f", {len(elines)} err" if elines else ""
        self._emit("exit", f"    -> exit {code} | {ms} ms | {len(olines)} line(s) out{errs}", lvl)
        limit = None if self._verbosity >= 3 else OUTPUT_LINES_AT_2
        for ln in olines[:limit]:
            self._emit("out", f"    | {ln}", lvl)
        if limit is not None and len(olines) > limit:
            self._emit("more", f"    | ... {len(olines) - limit} more line(s) - full text in the debug log "
                               f"(or verbosity 3)", lvl)
        for ln in elines[:limit]:
            self._emit("err", f"    ! {ln}", lvl)


# ---------------------------------------------------------------------- console sink
_ANSI = {"cmd": "\033[36m", "exit": "\033[2m", "out": "\033[2m", "more": "\033[2m", "err": "\033[33m",
         "trace": "\033[2m", "info": "\033[36m", "ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m"}


def console_sink(stream: Optional[TextIO] = None, color: Optional[bool] = None) -> Sink:
    """ASCII console sink for the CLI (colour only on a TTY)."""
    def sink(line: LogLine) -> None:
        s = stream or sys.stderr
        use = color if color is not None else s.isatty()
        text = ascii_safe(line.text)
        s.write(f"{_ANSI.get(line.kind, '')}{text}\033[0m\n" if use else f"{text}\n")
        s.flush()
    return sink


# ---------------------------------------------------------------------- process-wide logger
LOG = Logger()


def configure(verbosity: int, debug_path: Optional[Path]) -> Logger:
    LOG.verbosity = verbosity
    LOG.debug_path = debug_path
    return LOG

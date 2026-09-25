"""Tools (R-2.3, R-9.x): Shizuku; scrcpy, logcat, activity launcher and shell pane join in P5.3 - P5.6."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual import work
from textual.widgets import Button, Checkbox, Input, Label, RichLog, Select, Static

from droidforge import config
from droidforge.adb.hostcmd import Stream
from droidforge.features import shizuku
from droidforge.features.english_setup import focused_package
from droidforge.engine import executor
from droidforge.features.tools import activities, logcat, scrcpy
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class ToolsSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Tools[/b]")
        yield Label("Shizuku", classes="subtitle")
        yield Static("", id="shizuku-status", markup=False)
        with Horizontal(classes="buttons"):
            yield Button("Install Shizuku (official GitHub release)", id="shizuku-install")
            yield Button("Start Shizuku", id="shizuku-start", variant="primary")
        yield Label("Screen mirroring (scrcpy)", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Checkbox("phone screen off", id="scrcpy-off")
            yield Checkbox("stay awake", id="scrcpy-awake")
            yield Input(placeholder="record to file (optional)", id="scrcpy-record")
            yield Button("Launch scrcpy", id="scrcpy")
            yield Button("Install scrcpy", id="scrcpy-install")
        yield Label("Live logcat", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Select([(f"level >= {lv}", lv) for lv in logcat.LEVELS], value="V", id="lc-level",
                         allow_blank=False)
            yield Input(placeholder="tag", id="lc-tag")
            yield Input(placeholder="regex", id="lc-regex")
            yield Checkbox("focused app only", id="lc-focused")
        with Horizontal(classes="buttons"):
            yield Button("Start", id="lc-start", variant="primary")
            yield Button("Pause", id="lc-stop")
            yield Button("Clear", id="lc-clear")
            yield Button("Save", id="lc-save")
        yield RichLog(id="logcat", max_lines=5000, highlight=False, markup=False, wrap=False)
        yield Label("Activity launcher", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Select([(label, key) for key, (label, _) in activities.CURATED.items()], value="developer",
                         id="act-curated", allow_blank=False)
            yield Button("Open", id="act-open")
        with Horizontal(classes="buttons"):
            yield Input(placeholder="package to browse", id="act-pkg")
            yield Button("List activities", id="act-list")
            yield Select([], id="act-comp", prompt="activity")
            yield Button("Start", id="act-start")
        yield Label("adb shell (your own terminal: write-looking lines need a second Enter; no automatic undo)",
                    classes="subtitle")
        yield Input(placeholder="shell command, Enter to run", id="shell-in")
        yield RichLog(id="shell-out", max_lines=3000, highlight=False, markup=False, wrap=True)

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev = self.device
        if dev is not None:
            app.background(lambda: shizuku.status(dev),
                           lambda st: self.query_one("#shizuku-status", Static).update(f"Shizuku: {st}"))

    DEFAULT_CSS = """
    ToolsSection #logcat { height: 18; border: round $panel; }
    ToolsSection #shell-out { height: 14; border: round $panel; }
    ToolsSection Select { width: 40; }
    """

    def on_mount(self) -> None:
        self.stream: Optional[Stream] = None
        self.lines: List[str] = []
        self.pending_write = ""
        self.shell_history: List[str] = []

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "shell-in" or self.device is None:
            return
        cmd = event.value.strip()
        if not cmd:
            return
        confirmed = cmd == self.pending_write
        self.pending_write = ""
        self._shell(cmd, confirmed)

    @work(thread=True, group="shell", exclusive=True)
    def _shell(self, cmd: str, confirmed: bool) -> None:
        app = self.dapp
        s = app.session
        with app._dev_lock:
            res = executor.run_manual(cmd, self.device, s.history if s else None, confirmed)
        app.call_from_thread(self._shell_done, res)

    def _shell_done(self, res: "executor.ManualResult") -> None:
        out = self.query_one("#shell-out", RichLog)
        inp = self.query_one("#shell-in", Input)
        out.write(f"$ {res.cmd}")
        if res.refused:
            out.write(f"! refused: {res.refused}")
        elif res.needs_confirm:
            self.pending_write = res.cmd
            out.write("! this looks like a write (no automatic undo) - press Enter again to run it")
            return
        elif res.result is not None:
            for line in (res.result.out + ("\n" + res.result.err if res.result.err else "")).splitlines():
                out.write(line)
            out.write(f"-> exit {res.result.exit}")
            self.shell_history.append(res.cmd)
            for r in res.regressions:
                out.write(f"! health: {r}")
            if res.regressions:
                self.dapp.message("That shell line changed something important",
                                  "\n".join(str(r) for r in res.regressions)
                                  + "\n\nThere is no automatic undo for manual lines. If the phone misbehaves: "
                                    "Settings > Reset all settings.")
        inp.value = ""

    def lc_filter(self) -> logcat.Filter:
        return logcat.Filter(str(self.query_one("#lc-level", Select).value), self.query_one("#lc-tag", Input).value,
                             self.query_one("#lc-regex", Input).value)

    @work(thread=True, group="logcat", exclusive=True)
    def _read_logcat(self, focused: bool) -> None:
        dev = self.device
        pid = None
        if focused:
            pkg = focused_package(dev)
            pid = logcat.pid_of(dev, pkg) if pkg else None
        st = self.stream = logcat.open_stream(dev, pid)
        for line in st:
            self.lines.append(line)
            if self.lc_filter().matches(line):
                self.app.call_from_thread(self.query_one("#logcat", RichLog).write, line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        bid = event.button.id
        if bid == "scrcpy":
            rec = self.query_one("#scrcpy-record", Input).value.strip() or None
            try:
                cmd = scrcpy.launch(dev, self.query_one("#scrcpy-off", Checkbox).value,
                                    self.query_one("#scrcpy-awake", Checkbox).value, rec)
                app.notify(f"Started: {cmd}")
            except FileNotFoundError as e:
                app.notify(str(e), severity="error")
            return
        if bid == "scrcpy-install":
            app.run_plan(scrcpy.install_plan(dev))
            return
        if bid == "lc-start":
            self.query_one("#logcat", RichLog).clear()
            self._read_logcat(self.query_one("#lc-focused", Checkbox).value)
            return
        if bid == "lc-stop" and self.stream is not None:
            self.stream.stop()
            return
        if bid == "lc-clear":
            self.lines.clear()
            self.query_one("#logcat", RichLog).clear()
            return
        if bid == "lc-save":
            path = config.paths().sub("logs") / f"logcat-{datetime.now():%Y%m%d-%H%M%S}.txt"
            path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
            app.notify(f"Saved {len(self.lines)} lines to {path}")
            return
        if bid == "act-open":
            app.run_plan(activities.curated_plan(dev, str(self.query_one("#act-curated", Select).value)))
            return
        if bid == "act-list":
            pkg = self.query_one("#act-pkg", Input).value.strip()
            app.background(lambda: activities.activities(dev, pkg),
                           lambda comps: self.query_one("#act-comp", Select).set_options([(c, c) for c in comps]))
            return
        if bid == "act-start":
            comp = self.query_one("#act-comp", Select).value
            if isinstance(comp, str):
                app.run_plan(activities.launch_plan(dev, comp))
            return
        if bid == "shizuku-install":
            app.run_plan(lambda: shizuku.install_plan(dev), on_done=lambda rep: self.refresh_from(app))
        elif event.button.id == "shizuku-start":
            app.run_plan(lambda: shizuku.start_plan(dev), on_done=lambda rep: self.refresh_from(app))

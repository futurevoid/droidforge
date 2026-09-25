"""DroidforgeApp (R-12.1): header DeviceBar, sidebar of sections, main area, collapsible LogPane.

Engine calls run in thread workers; log lines reach the LogPane through a thread-safe sink; the confirm hook
(P3.2) blocks the worker on a threading.Event while the preview modal is open.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import ContentSwitcher, Footer, Label, ListItem, ListView, Static

from droidforge import config
from droidforge.adb.device import list_devices
from droidforge.adb.real import RealBackend
from droidforge.adb.sim import FakePhone
from droidforge.log import LOG
from droidforge.session import ConnectError, Session, open_session
from droidforge.tui.screens.modals import DevicePicker, LimitsNote
from droidforge.tui.widgets.device_bar import DeviceBar, ExpertBanner
from droidforge.tui.widgets.log_pane import LogPane

SECTIONS: List[Tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("language", "Language"),
    ("keyboard", "Keyboard"),
    ("debloat", "Debloat"),
    ("history", "Backup & History"),
]


class Section(VerticalScroll):
    """A main-area section. Screens for the features replace the placeholder body."""

    DEFAULT_CSS = "Section { padding: 1 2; }"

    def __init__(self, section_id: str, title: str) -> None:
        super().__init__(id=section_id)
        self.title_text = title

    def compose(self) -> ComposeResult:
        yield Label(f"[b]{self.title_text}[/b]")
        yield Static("", classes="body")

    def refresh_from(self, app: "DroidforgeApp") -> None:  # overridden by feature sections
        pass


class DroidforgeApp(App[None]):
    TITLE = "droidforge"
    CSS = """
    #main { height: 1fr; }
    #sidebar { width: 24; border-right: solid $primary; }
    #content { width: 1fr; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("l", "toggle_log", "Log pane"),
    ]

    def __init__(self, simulate: bool = False, serial: Optional[str] = None, expert: bool = False,
                 dry_run: bool = False, phone: Optional[FakePhone] = None, show_limits: Optional[bool] = None) -> None:
        super().__init__()
        self.simulate, self.serial, self.expert, self.dry_run = simulate, serial, expert, dry_run
        self.phone = phone
        self.cfg = config.Config()
        self.show_limits = (not self.cfg.get("limits_shown")) if show_limits is None else show_limits
        self.session: Optional[Session] = None
        self.sections: Dict[str, Section] = {}
        self.status_text = "connecting..."

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield DeviceBar(id="devicebar")
        banner = ExpertBanner(id="expert-banner")
        if not self.expert:
            banner.add_class("hidden")
        yield banner
        with Horizontal(id="main"):
            yield ListView(*[ListItem(Label(label), id=f"nav-{sid}") for sid, label in SECTIONS], id="sidebar")
            with ContentSwitcher(initial="dashboard", id="content"):
                for sid, label in SECTIONS:
                    sec = self.make_section(sid, label)
                    self.sections[sid] = sec
                    yield sec
        yield LogPane(id="log")
        yield Footer()

    def make_section(self, sid: str, label: str) -> Section:
        return Section(sid, label)

    def on_mount(self) -> None:
        pane = self.query_one(LogPane)
        LOG.add_sink(pane.sink)
        self._sink = pane.sink
        self.refresh_bar()
        if self.show_limits:
            self.push_screen(LimitsNote(), lambda _: self.cfg.set("limits_shown", True))
        self.connect(self.serial)

    def on_unmount(self) -> None:
        LOG.remove_sink(self._sink)

    # ------------------------------------------------------------------ navigation
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is not None and event.item.id and event.item.id.startswith("nav-"):
            self.show_section(event.item.id[4:])

    def show_section(self, sid: str) -> None:
        self.query_one(ContentSwitcher).current = sid
        if self.session is not None:
            self.sections[sid].refresh_from(self)

    def action_toggle_log(self) -> None:
        self.query_one(LogPane).toggle_class("hidden")

    # ------------------------------------------------------------------ connection
    @work(thread=True, exclusive=True, group="connect")
    def connect(self, serial: Optional[str] = None) -> None:
        try:
            s = open_session(simulate=self.simulate, serial=serial, expert=self.expert, dry_run=self.dry_run,
                             phone=self.phone)
        except ConnectError as e:
            rows = [] if self.simulate else list_devices(RealBackend())
            ready = [r for r in rows if r[1] == "device"]
            self.call_from_thread(self._connect_failed, str(e), rows if len(ready) > 1 else [])
            return
        s.start()  # session-start backup (R-11.3)
        label = s.device.label
        self.call_from_thread(self._connected, s, label)

    def _connect_failed(self, msg: str, rows: List[Tuple[str, str]]) -> None:
        self.status_text = msg
        self.refresh_bar(device=f"no device: {msg}")
        LOG.error(msg)
        if rows:
            self.push_screen(DevicePicker(rows), lambda serial: self.connect(serial) if serial else None)

    def _connected(self, s: Session, label: str) -> None:
        self.session = s
        self.status_text = "connected"
        self.refresh_bar(device=f"{label} ({s.device.serial}){' [SIMULATED]' if s.simulate else ''}")
        LOG.ok(f"Connected: {label} ({s.device.serial})")
        current = self.query_one(ContentSwitcher).current or "dashboard"
        self.sections[current].refresh_from(self)

    def refresh_bar(self, **fields: str) -> None:
        s = self.session
        prof = ""
        if s is not None:
            p = s.profile
            n = len(p.disabled) + len(p.removed) + len(p.suspended) + len(p.neutered)
            prof = f"profile: {n} package change(s)"
        self.query_one(DeviceBar).show(
            profile=prof, verbosity=f"verbosity {LOG.verbosity}",
            dry_run="DRY-RUN" if self.dry_run else "", expert="EXPERT" if self.expert else "", **fields)

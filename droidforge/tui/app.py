"""DroidforgeApp (R-12.1): header DeviceBar, sidebar of sections, main area, collapsible LogPane.

Engine calls run in thread workers; log lines reach the LogPane through a thread-safe sink; the confirm hook
(P3.2) blocks the worker on a threading.Event while the preview modal is open.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer, Label, ListItem, ListView

from droidforge import config
from droidforge.adb.device import list_devices
from droidforge.adb.real import RealBackend
from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.executor import RunReport
from droidforge.engine.plan import Confirmation, Plan
from droidforge.log import LEVEL_NAMES, LOG
from droidforge.session import ConnectError, Session, open_session
from droidforge.engine.health import HealthReport
from droidforge.features import fix
from droidforge.features.doctor import DoctorReport
from droidforge.tui.screens.breakage import BreakageAlert
from droidforge.tui.screens.base import Section
from droidforge.tui.screens.apps import AppsSection
from droidforge.tui.screens.dashboard import DashboardSection
from droidforge.tui.screens.firewall import FirewallSection
from droidforge.tui.screens.keepalive import KeepAliveSection
from droidforge.tui.screens.privacy import PrivacySection
from droidforge.tui.screens.debloat import DebloatSection
from droidforge.tui.screens.history import HistorySection
from droidforge.tui.screens.keyboard import KeyboardSection
from droidforge.tui.screens.language import LanguageSection
from droidforge.tui.screens.modals import EXPERT_WARNING, ConfirmBox, DevicePicker, LimitsNote, MessageBox
from droidforge.tui.themes import DEFAULT_THEME, HACKER
from droidforge.tui.widgets.device_bar import DeviceBar, ExpertBanner
from droidforge.tui.widgets.log_pane import LogPane
from droidforge.tui.widgets.plan_preview import PlanPreview

PlanDone = Callable[[RunReport], None]
LONG_JOB_S = 30.0


def notify(app: "DroidforgeApp", title: str, body: str) -> None:
    """Desktop notification (R-2.7) - never fatal."""
    from droidforge import notify as nt
    try:
        nt.notify(title, body, app.session.device if app.session else None)
    except Exception as e:  # a notification must never break the app
        LOG.dbg(f"notify failed: {e}")

SECTIONS: List[Tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("language", "Language"),
    ("keyboard", "Keyboard"),
    ("debloat", "Debloat"),
    ("privacy", "Privacy & ads"),
    ("firewall", "Firewall"),
    ("apps", "Apps & defaults"),
    ("keepalive", "Keep-alive & perms"),
    ("history", "Backup & History"),
]


SECTION_CLASSES = {"dashboard": DashboardSection, "language": LanguageSection, "keyboard": KeyboardSection,
                   "debloat": DebloatSection, "privacy": PrivacySection, "firewall": FirewallSection,
                   "apps": AppsSection, "keepalive": KeepAliveSection, "history": HistorySection}


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
        Binding("v", "cycle_verbosity", "Verbosity"),
        Binding("d", "toggle_dry_run", "Dry-run"),
        Binding("ctrl+t", "change_theme", "Theme"),
        Binding("ctrl+e", "toggle_expert", "Expert mode"),
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
        self.last_report: Optional[RunReport] = None
        self.sleep: Callable[[float], None] = time.sleep   # tests replace it (reboot check polling)
        self._pending: List[Tuple[threading.Event, Dict[str, Confirmation]]] = []
        self.ignored: List[fix.Breakage] = []
        self._plan_started = 0.0
        # one engine call at a time: plans, checks and reads share one Device (caches, snapshots, adb)
        self._dev_lock = threading.RLock()

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
        return SECTION_CLASSES.get(sid, Section)(sid, label)

    def on_mount(self) -> None:
        self.register_theme(HACKER)
        wanted = self.cfg.get("theme") or DEFAULT_THEME
        self.theme = wanted if wanted in self.available_themes else DEFAULT_THEME
        self.watch(self, "theme", self._theme_changed, init=False)
        pane = self.query_one(LogPane)
        LOG.add_sink(pane.sink)
        self._sink = pane.sink
        self.refresh_bar()
        if self.show_limits:
            self.push_screen(LimitsNote(), lambda _: self.cfg.set("limits_shown", True))
        self.connect(self.serial)

    def on_unmount(self) -> None:
        self._release_pending()
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

    def _theme_changed(self, theme: str) -> None:
        self.cfg.set("theme", theme)   # R-12.2: the choice is persisted

    def action_cycle_verbosity(self) -> None:
        v = LOG.cycle()
        self.cfg.set("verbosity", v)
        self.refresh_bar()
        self.notify(f"Verbosity {v}: {LEVEL_NAMES[v]}")

    def action_toggle_dry_run(self) -> None:
        self.dry_run = not self.dry_run
        if self.session is not None:
            self.session.dry_run = self.dry_run
        self.refresh_bar()
        self.notify("Dry-run ON - plans are shown and logged, nothing is sent" if self.dry_run else "Dry-run off")

    def action_toggle_expert(self) -> None:
        """R-4.3: expert mode toggle in the header; red banner while on. Turning it on asks first."""
        if self.expert:
            self.set_expert(False)
            return
        self.push_screen(ConfirmBox("Turn on expert mode?", EXPERT_WARNING),
                         lambda yes: self.set_expert(True) if yes else None)

    def set_expert(self, on: bool) -> None:
        self.expert = on
        if self.session is not None:
            self.session.expert = on
        self.query_one(ExpertBanner).set_class(not on, "hidden")
        self.refresh_bar()
        LOG.warn("Expert mode ON" if on else "Expert mode off")

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
        with self._dev_lock:
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
        self.check_startup()  # R-12.5: breakage between sessions is caught at every connect
        self.check_firewall()  # R-5.5 / P14: rules cleared by a reboot -> ask, never re-apply on our own
        self.check_ota()       # R-2.5 / P14: system update detected -> show what it undid, ask

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

    # ------------------------------------------------------------------ plans
    def run_plan(self, plan: Union[Plan, Callable[[], Plan]], on_done: Optional[PlanDone] = None) -> None:
        """Build (in the worker: builders read the phone) -> preview -> confirm -> execute.
        Plans without steps only show their notes."""
        if self.session is None:
            self.notify("No phone connected", severity="error")
            return
        self._plan_worker(plan, on_done)

    @work(thread=True, exclusive=True, group="plan")
    def _plan_worker(self, plan: Union[Plan, Callable[[], Plan]], on_done: Optional[PlanDone]) -> None:
        self._plan_started = time.monotonic()
        s = self.session
        assert s is not None
        with self._dev_lock:
            try:
                built = plan() if callable(plan) else plan
            except Exception as e:  # a builder that cannot read what it needs: show it, never crash the app
                LOG.error(f"could not build the plan: {e}")
                self.call_from_thread(self.message, "Could not build the plan", str(e))
                return
            if not built.steps:
                self.call_from_thread(self.message, built.title, "\n".join(built.notes) or "Nothing to do.")
                return
            try:
                rep = executor.run(built, s.device, self.confirm_blocking, dry_run=self.dry_run, history=s.history,
                                   profile=s.profile, expert_mode=self.expert)
            except Exception as e:
                self.call_from_thread(self._crashed, built, e)
                return
        self.call_from_thread(self._plan_finished, rep, on_done)

    def _crashed(self, plan: Plan, e: Exception) -> None:
        """Never let an unexpected error take the app down mid-plan: say what happened and where recovery is."""
        import traceback
        LOG.dbg("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        LOG.error(f"Unexpected error while running '{plan.title}': {e}")
        body = f"{type(e).__name__}: {e}\n\nFull traceback in the debug log."
        if plan.recovery:
            body += f"\n\nRecovery script (undo of this plan): {plan.recovery}\nRun it with: sh {plan.recovery}"
        self.push_screen(MessageBox("Unexpected error", body))

    def message(self, title: str, body: str) -> None:
        """Show a message box. UI thread only: widgets must be built there (workers use call_from_thread)."""
        self.push_screen(MessageBox(title, body))

    def background(self, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run a read-only engine call in a thread; `done(result)` on the UI thread."""
        self._bg_worker(fn, done)

    @work(thread=True, group="read")
    def _bg_worker(self, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        try:
            with self._dev_lock:
                res = fn()
        except Exception as e:
            LOG.error(f"read failed: {e}")
            return
        self.call_from_thread(done, res)

    def confirm_blocking(self, plan: Plan) -> Confirmation:
        """The executor's confirm hook (runs in the worker thread): block until the preview is dismissed."""
        done = threading.Event()
        box: Dict[str, Confirmation] = {}
        self._pending.append((done, box))

        def show() -> None:
            def result(r: Optional[Confirmation]) -> None:
                box.setdefault("r", r or Confirmation(False))
                done.set()
            self.push_screen(PlanPreview(plan, dry_run=self.dry_run), result)
        try:
            self.call_from_thread(show)
        except RuntimeError:  # the app is shutting down
            box.setdefault("r", Confirmation(False))
            done.set()
        done.wait()
        self._pending.remove((done, box))
        return box["r"]

    def _release_pending(self) -> None:
        """On exit, every open confirmation answers Cancel - nothing is sent, the worker ends."""
        for done, box in list(self._pending):
            box.setdefault("r", Confirmation(False))
            done.set()

    async def action_quit(self) -> None:
        self._release_pending()
        await super().action_quit()

    def _plan_finished(self, rep: RunReport, on_done: Optional[PlanDone]) -> None:
        self.last_report = rep
        if time.monotonic() - self._plan_started > LONG_JOB_S:
            notify(self, "droidforge: plan finished", f"{rep.plan.title}: {rep.status}")
        self.refresh_bar()
        if rep.status == "refused":
            self.push_screen(MessageBox("Refused", rep.error))
        elif rep.status == "stopped":
            self.on_breakage(rep)
        elif rep.status in ("done", "dry-run"):
            ok = sum(1 for r in rep.results if r.ok)
            self.notify(f"{rep.plan.title}: {ok}/{len(rep.results)} step(s) ok"
                        + (" (dry-run)" if rep.status == "dry-run" else ""))
        current = self.query_one(ContentSwitcher).current or "dashboard"
        self.sections[current].refresh_from(self)
        if on_done is not None:
            on_done(rep)

    # ------------------------------------------------------------------ breakage alert (R-12.5)
    def on_breakage(self, rep: RunReport) -> None:
        self.show_breakage(fix.from_report(rep), rep.baseline_health)

    def show_breakage(self, b: fix.Breakage, baseline: Optional[HealthReport] = None) -> None:
        LOG.error(b.title)
        for w in b.what_broke():
            LOG.error(f"  {w}")

        def chosen(action: Optional[str]) -> None:
            if action == "fix" and b.repair is not None:
                self.run_plan(b.repair, on_done=lambda rep: self._after_fix(b, baseline))
            elif action == "devopts":
                self.run_plan(fix.developer_options_plan())
                self._remember(b)
            else:
                self._remember(b)
        self.push_screen(BreakageAlert(b), chosen)

    def _remember(self, b: fix.Breakage) -> None:
        """Ignored alerts stay listed on the dashboard until the phone is healthy."""
        if b not in self.ignored:
            self.ignored.append(b)
        self.sections["dashboard"].show_alerts(self.ignored)  # type: ignore[attr-defined]

    def _after_fix(self, b: fix.Breakage, baseline: Optional[HealthReport]) -> None:
        s = self.session
        if s is None:
            return
        self.background(lambda: fix.recheck(s.device, s.profile, baseline), lambda regs: self._fixed(b, regs))

    def _fixed(self, b: fix.Breakage, regs: List[Any]) -> None:
        if not regs:
            self.ignored.clear()
            self.sections["dashboard"].show_alerts(self.ignored)  # type: ignore[attr-defined]
            self.message("Healthy again", "Fix it worked: the phone is healthy again.")
            return
        still = fix.Breakage(b.source, regs, [], b.recent, None, "Still not right after Fix it")
        self.show_breakage(still)

    def check_ota(self) -> None:
        s = self.session
        if s is None:
            return
        from droidforge.features import ota

        def ask(rep: "ota.OtaReport") -> None:
            if not rep.changed:
                if s.profile.fingerprint != rep.new:
                    s.profile.note_device(s.device)     # first connect: remember the build
                    if s.profile.path:
                        s.profile.save()
                return
            notify(self, "droidforge: system update detected", "Your saved changes can be re-applied.")
            if rep.plan is None or not rep.plan.steps:
                ota.acknowledge(s.profile, s.device)
                return
            body = ("The phone got a system update. It undid:\n" + "\n".join(f"  {r}" for r in rep.reverted)
                    + "\n\nRe-apply your changes? You will see the plan first.")
            self.push_screen(ConfirmBox("System update detected", body, "Re-apply", "Keep as it is"),
                             lambda yes: self.run_plan(rep.plan, on_done=lambda r: ota.acknowledge(
                                 s.profile, s.device) if r.status == "done" else None)
                             if yes else ota.acknowledge(s.profile, s.device))
        self.background(lambda: ota.check(s.device, s.profile, None, self.expert), ask)

    def check_firewall(self) -> None:
        s = self.session
        if s is None or not s.profile.firewall:
            return
        from droidforge.features import firewall

        def ask(missing: List[str]) -> None:
            if not missing:
                return
            body = ("These apps were blocked by droidforge, but their firewall rules are gone (the phone rebooted):\n"
                    + "\n".join(f"  {p}" for p in missing) + "\n\nRe-apply the rules? You will see the plan first.")
            self.push_screen(ConfirmBox("Firewall rules were cleared", body, "Re-apply", "Not now"),
                             lambda yes: self.run_plan(lambda: firewall.reapply_plan(s.device, s.profile,
                                                                                     expert_mode=self.expert))
                             if yes else None)
        self.background(lambda: firewall.missing_rules(s.device, s.profile), ask)

    def check_startup(self) -> None:
        s = self.session
        if s is not None:
            self.background(lambda: fix.check_startup(s.device, s.profile, s.history),
                            lambda b: self.show_breakage(b) if b is not None else None)

    def dashboard_alerts(self, rep: DoctorReport) -> None:
        if rep.healthy and self.ignored:
            self.ignored.clear()
            self.sections["dashboard"].show_alerts(self.ignored)  # type: ignore[attr-defined]

    def run_reboot_check(self) -> None:
        rep = self.last_report
        if self.session is None or rep is None or not rep.offer_reboot:
            self.notify("The reboot check is offered after a risky plan (system debloat, keyboard, expert).",
                        severity="warning")
            return
        self._reboot_worker(rep)

    @work(thread=True, exclusive=True, group="plan")
    def _reboot_worker(self, before: RunReport) -> None:
        from droidforge.engine.reboot import reboot_check
        s = self.session
        assert s is not None
        try:
            with self._dev_lock:
                rep = reboot_check(s.device, before, self.confirm_blocking, sleep=self.sleep, dry_run=self.dry_run,
                                   history=s.history, profile=s.profile, expert_mode=self.expert)
        except Exception as e:
            self.call_from_thread(self._crashed, before.plan, e)
            return
        self.call_from_thread(self._plan_finished, rep, None)

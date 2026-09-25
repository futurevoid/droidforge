"""Debloat (R-4.x): UAD-NG list / scan, package table, actions. Every action is a previewed plan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from droidforge.data import uad
from droidforge.engine import safety
from droidforge.engine.plan import Plan
from droidforge.features import debloat
from droidforge.tui.screens.base import Section
from droidforge.tui.screens.modals import ConfirmBox, MessageBox
from droidforge.tui.widgets.tables import PackageTable

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp

ACTIONS = [("disable", "Disable"), ("force", "Force-disable"), ("neuter", "Neuter"), ("remove", "Remove (user 0)"),
           ("enable", "Enable / un-neuter"), ("restore", "Restore")]


class DebloatSection(Section):
    DEFAULT_CSS = """
    DebloatSection PackageTable { height: 24; }
    DebloatSection Select { width: 22; }
    DebloatSection #keyword { width: 24; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Debloat[/b]  - no presets: you pick every package (R-4.1)")
        yield Static(uad.status_line(), id="uad-status")
        with Horizontal(classes="buttons"):
            yield Select([("UAD-NG list", "uad"), ("Scan (China-ROM)", "scan")], value="uad", id="mode",
                         allow_blank=False)
            for t in uad.TIERS:
                yield Checkbox(t, value=t == "Recommended", id=f"tier-{t}")
        with Horizontal(classes="buttons"):
            yield Input(placeholder="keyword (e.g. heytap, 'all' in scan)", id="keyword")
            yield Checkbox("show system UI infrastructure", id="infra")
            yield Button("Load", id="load", variant="primary")
            yield Button("Update UAD-NG list", id="update-uad")
        yield PackageTable(id="packages")
        with Horizontal(classes="buttons"):
            for aid, label in ACTIONS:
                yield Button(label, id=f"act-{aid}")
        with Horizontal(classes="buttons"):
            yield Button("Info", id="info")
            yield Button("Select all (bulk-safe)", id="select-all")
            yield Button("Clear selection", id="clear")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        self.query_one("#uad-status", Static).update(uad.status_line())
        if not self.query_one(PackageTable).rows:
            self.load()

    def load(self) -> None:
        dev, app = self.device, self.dapp
        if dev is None:
            return
        data = uad.load_cached()
        mode = self.query_one("#mode", Select).value
        tiers = [t for t in uad.TIERS if self.query_one(f"#tier-{t}", Checkbox).value]
        kw = self.query_one("#keyword", Input).value.strip()
        infra = self.query_one("#infra", Checkbox).value
        suspended = app.session.profile.suspended if app.session else []
        if mode == "uad":
            if not data:
                self.query_one("#uad-status", Static).update("UAD-NG: not downloaded - press 'Update UAD-NG list'"
                                                             " (or use Scan)")
            app.background(lambda: debloat.listing(dev, data, tiers, None, kw, infra, suspended), self._loaded)
        else:
            app.background(lambda: debloat.scan(dev, data, kw, infra, suspended), self._loaded)

    def _loaded(self, rows: List[debloat.Row]) -> None:
        self.query_one(PackageTable).load(rows)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        app, dev = self.dapp, self.device
        table = self.query_one(PackageTable)
        if bid == "load":
            self.load()
        elif bid == "update-uad":
            app.push_screen(ConfirmBox("Download the UAD-NG list?", f"About 1.6 MB from GitHub:\n{uad.UAD_URL}\n"
                                       "(GPL-3.0, Universal Android Debloater Next Generation)", "Download", "Cancel"),
                            lambda yes: app.background(uad.update, self._updated) if yes else None)
        elif bid == "clear":
            table.clear_selection()
        elif bid == "select-all" and dev is not None:
            data = uad.load_cached()
            app.background(lambda: debloat.bulk(table.visible_rows(), safety.SafetyContext.from_device(dev, data)),
                           table.select_all)
        elif bid == "info" and dev is not None:
            pkgs = table.selection()
            app.background(lambda: debloat.info(dev, pkgs, uad.load_cached()),
                           lambda lines: app.push_screen(MessageBox("Package info", "\n".join(lines) or "-")))
        elif bid.startswith("act-") and dev is not None:
            pkgs = table.selection()
            if not pkgs:
                app.notify("Select packages first (Enter / click toggles a row)", severity="warning")
                return
            app.run_plan(self._builder(bid[4:], pkgs), on_done=lambda rep: self.load())

    def _builder(self, action: str, pkgs: List[str]) -> Callable[[], Plan]:
        app, dev = self.dapp, self.device
        data = uad.load_cached()
        profile = app.session.profile if app.session else None
        fns: Dict[str, Callable[[], Plan]] = {
            "disable": lambda: debloat.disable_plan(dev, pkgs, data, app.expert),
            "force": lambda: debloat.force_plan(dev, pkgs, data, app.expert),
            "neuter": lambda: debloat.neuter_plan(dev, pkgs, data, app.expert),
            "remove": lambda: debloat.remove_plan(dev, pkgs, data, app.expert),
            "enable": lambda: debloat.enable_plan(dev, pkgs, profile, data, app.expert),
            "restore": lambda: debloat.restore_plan(dev, pkgs, data, app.expert),
        }
        return fns[action]

    def _updated(self, res: tuple) -> None:
        ok, msg = res
        self.dapp.notify(msg, severity="information" if ok else "error")
        self.query_one("#uad-status", Static).update(uad.status_line())

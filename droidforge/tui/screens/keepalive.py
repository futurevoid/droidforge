"""Keep-alive (R-6.3), power permissions (R-6.4), region & time screens (R-3.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Label, Static

from droidforge.data.presets import CATALOG
from droidforge.features import keepalive, powerperms, region
from droidforge.tui.screens.base import Section
from droidforge.tui.screens.common import AppPicker

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class KeepAliveSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Keep-alive & power permissions[/b]")
        yield Static(keepalive.MANUAL, markup=False, classes="status")
        yield AppPicker(id="ka-apps")
        with Horizontal(classes="buttons"):
            yield Button("Keep picked apps alive", id="ka-on", variant="primary")
            yield Button("Stop keeping alive", id="ka-off")
        yield Label("Phone-wide, off by default - its own plan, undo it alone in History", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Button("Allow child processes (Disable child process restrictions)", id="ka-child")
        yield Label("Power permissions for the picked app", classes="subtitle")
        with Horizontal(classes="buttons"):
            for name in powerperms.PERMS:
                yield Checkbox(name, id=f"pp-{name}")
            yield Button("Grant", id="pp-grant")
        with Horizontal(classes="buttons", id="pp-presets"):
            yield Button("Grant presets (installed automation apps)", id="pp-presets-btn")
        yield Label("Region & time (droidforge only opens the screens)", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Button("Regional preferences", id="regional")
            yield Button("Date & time", id="datetime")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev = self.device
        if dev is not None:
            def read() -> Tuple[List[str], Dict[str, str], List[str], Dict[str, str]]:
                pkgs = keepalive.candidates(dev)
                return pkgs, keepalive.statuses(dev, pkgs), powerperms.installed_presets(dev), {}
            app.background(read, self.show)

    def show(self, res: Tuple[List[str], Dict[str, str], List[str], Dict[str, str]]) -> None:
        pkgs, status, presets, names = res
        self.query_one(AppPicker).load(pkgs, status, names)
        self.presets = presets
        self.query_one("#pp-presets-btn", Button).label = (
            "Grant presets: " + ", ".join(CATALOG[k].name for k in presets)) if presets else "No preset apps installed"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        picked = self.query_one(AppPicker).picked()
        bid = event.button.id
        if bid == "ka-on":
            app.run_plan(lambda: keepalive.keepalive_plan(dev, picked, None, app.expert),
                         on_done=lambda rep: self.refresh_from(app))
        elif bid == "ka-child":
            app.run_plan(lambda: keepalive.child_process_plan(dev))
        elif bid == "ka-off":
            app.run_plan(lambda: keepalive.remove_plan(dev, picked), on_done=lambda rep: self.refresh_from(app))
        elif bid == "pp-grant":
            perms = [n for n in powerperms.PERMS if self.query_one(f"#pp-{n}", Checkbox).value]
            app.run_plan(lambda: powerperms.grant_plan(dev, {p: perms for p in picked}, None, app.expert))
        elif bid == "pp-presets-btn":
            keys = list(getattr(self, "presets", []))
            app.run_plan(lambda: powerperms.preset_plan(dev, keys))
        elif bid == "regional":
            app.run_plan(lambda: region.regional_plan(dev))
        elif bid == "datetime":
            app.run_plan(lambda: region.datetime_plan(dev))

"""Firewall (R-5.5): block / allow internet per app, re-apply rules cleared by a reboot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, Static

from droidforge.data import uad
from droidforge.features import firewall
from droidforge.tui.screens.base import Section
from droidforge.tui.screens.common import AppPicker

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class FirewallSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Firewall[/b]  - per-app internet block without root (cleared by a reboot)")
        yield Static("", id="fw-status", classes="status", markup=False)
        yield AppPicker(id="fw-apps")
        with Horizontal(classes="buttons"):
            yield Input(placeholder="or any package name", id="fw-pkg")
            yield Button("Block internet", id="fw-block", variant="error")
            yield Button("Allow internet", id="fw-unblock")
            yield Button("Re-apply saved rules", id="fw-reapply")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev, s = self.device, app.session
        if dev is None or s is None:
            return

        def read() -> Tuple[bool, List[str], List[str], Dict[str, str]]:
            ok = firewall.supported(dev)
            apps = sorted(dev.packages("-3"))
            return ok, apps, firewall.missing_rules(dev, s.profile) if ok else [], {}
        app.background(read, self.show)

    def show(self, res: Tuple[bool, List[str], List[str], Dict[str, str]]) -> None:
        ok, apps, missing, names = res
        s = self.dapp.session
        blocked = s.profile.firewall if s else []
        msg = firewall.UNSUPPORTED if not ok else f"Blocked by droidforge: {', '.join(blocked) or 'none'}"
        if missing:
            msg += f"\nRules missing (reboot): {', '.join(missing)}"
        self.query_one("#fw-status", Static).update(msg)
        self.query_one(AppPicker).load(apps, None, names)

    def _picked(self) -> List[str]:
        extra = self.query_one("#fw-pkg", Input).value.strip()
        return self.query_one(AppPicker).picked() + ([extra] if extra else [])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev, s = self.dapp, self.device, self.dapp.session
        if dev is None or s is None:
            return
        data, pkgs = uad.load_cached(), self._picked()
        if event.button.id == "fw-block":
            app.run_plan(lambda: firewall.block_plan(dev, pkgs, data, app.expert, s.profile))
        elif event.button.id == "fw-unblock":
            app.run_plan(lambda: firewall.unblock_plan(dev, pkgs, data, app.expert))
        elif event.button.id == "fw-reapply":
            app.run_plan(lambda: firewall.reapply_plan(dev, s.profile, data, app.expert))

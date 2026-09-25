"""Privacy & ads (R-5.1 - R-5.4): telemetry, ads/promos, install hijack, Private DNS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select

from droidforge.data import uad
from droidforge.data.packages import ADS_CATEGORIES
from droidforge.features import ads, dns, privacy
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class PrivacySection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Privacy & ads[/b]")
        yield Label("Telemetry", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Checkbox("include App enhancement (cosa)", id="tel-optin")
            yield Checkbox("force-disable escalation", id="tel-force")
            yield Button("Kill telemetry", id="telemetry", variant="primary")
        yield Label("Ads and promos", classes="subtitle")
        with Horizontal(classes="buttons"):
            for key, label in ADS_CATEGORIES.items():
                yield Checkbox(label.split(" (")[0], value=True, id=f"ads-{key}")
            yield Button("Remove ads", id="ads", variant="primary")
        yield Label("Install hijack", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Checkbox("also lower adb install verification (LOWERS PROTECTION)", id="hijack-lower")
            yield Button("Stop install hijack", id="hijack", variant="primary")
        yield Label("Private DNS", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Select([(label, key) for key, label in dns.menu()], value=dns.DEFAULT, id="dns-provider",
                         allow_blank=False)
            yield Input(placeholder="NextDNS ID or custom hostname", id="dns-extra")
            yield Button("Set Private DNS", id="dns", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        data = uad.load_cached()
        bid = event.button.id
        if bid == "telemetry":
            opt, force = self.query_one("#tel-optin", Checkbox).value, self.query_one("#tel-force", Checkbox).value
            app.run_plan(lambda: privacy.telemetry_plan(dev, data, opt, force, app.expert))
        elif bid == "ads":
            cats = [k for k in ADS_CATEGORIES if self.query_one(f"#ads-{k}", Checkbox).value]
            app.run_plan(lambda: ads.ads_plan(dev, cats, data, app.expert))
        elif bid == "hijack":
            lower = self.query_one("#hijack-lower", Checkbox).value
            app.run_plan(lambda: privacy.install_hijack_plan(dev, data, lower, True, app.expert))
        elif bid == "dns":
            prov = str(self.query_one("#dns-provider", Select).value)
            extra = self.query_one("#dns-extra", Input).value.strip() or None
            app.run_plan(lambda: dns.dns_plan(dev, prov, extra if prov == "nextdns" else None,
                                              extra if prov == "custom" else None))

    def refresh_from(self, app: "DroidforgeApp") -> None:
        pass

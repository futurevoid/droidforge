"""Apps & defaults (R-6.1, R-6.2): Play pages, official downloads, local APKs, default-app swaps."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select

from droidforge import config
from droidforge.data import uad
from droidforge.data.presets import CATALOG
from droidforge.features import apps, defaults
from droidforge.tui.screens.base import Section


class AppsSection(Section):
    def compose(self) -> ComposeResult:
        yield Label("[b]Apps & defaults[/b]")
        yield Label("Install", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Select([(a.name, k) for k, a in CATALOG.items()], value="firefox-nightly", id="app-key",
                         allow_blank=False)
            yield Button("Open Play page", id="play")
            yield Button("Download official APK + install", id="official")
        with Horizontal(classes="buttons"):
            yield Input(placeholder="APK file or folder on this PC", id="apk-path")
            yield Button("Install APK / folder", id="local")
        yield Label("Default apps", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Select([(sw.label, k) for k, sw in defaults.SWAPS.items()], value="browser", id="swap-fn",
                         allow_blank=False)
            yield Checkbox("also disable the ColorOS app (browser / gallery / files)", id="swap-disable")
            yield Button("Swap", id="swap", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        key = str(self.query_one("#app-key", Select).value)
        bid = event.button.id
        if bid == "play":
            app.run_plan(lambda: apps.play_plan(dev, CATALOG[key].package))
        elif bid == "official":
            app.run_plan(lambda: apps.install_plan(dev, [apps.download(key, config.paths().sub("cache"))]))
        elif bid == "local":
            path = Path(self.query_one("#apk-path", Input).value.strip()).expanduser()
            app.run_plan(lambda: apps.folder_plan(dev, path) if path.is_dir() else apps.install_plan(dev, [path]))
        elif bid == "swap":
            fn = str(self.query_one("#swap-fn", Select).value)
            dis = self.query_one("#swap-disable", Checkbox).value
            app.run_plan(lambda: defaults.swap_plan(dev, fn, dis, uad.load_cached(), app.expert))

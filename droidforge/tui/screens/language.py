"""Language (R-3.1, R-3.2) and the guided English setup (P2.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Button, Input, Label, SelectionList, Static

from droidforge.features import language
from droidforge.features.english_setup import EnglishSetup
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class LanguageSection(Section):
    def __init__(self, section_id: str, title: str) -> None:
        super().__init__(section_id, title)
        self.setup: Optional[EnglishSetup] = None
        self.timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        yield Label("[b]Language[/b]  (droidforge reads the device language; you change it in Settings)")
        yield Static("", id="lang-status", classes="status")
        with Horizontal(classes="buttons"):
            yield Button("Open Settings > Language", id="open-lang")
            yield Button("Re-check", id="recheck")
            yield Button("Open App languages", id="open-app-lang")
        yield Label("English setup guide", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Button("1. Language", id="guide-1")
            yield Button("2. Gboard", id="guide-2")
            yield Button("2b. Chinese keyboards off", id="guide-2b")
            yield Button("3. Watch apps", id="guide-3")
            yield Button("Stop + offer", id="guide-3-stop")
        yield Static("", id="caught")
        yield Label("Per-app language - your own apps only (system apps follow the device language)",
                    classes="subtitle")
        yield SelectionList[str](id="apps")
        with Horizontal(classes="buttons"):
            yield Input(value=language.DEFAULT_APP_LOCALES, id="locales", placeholder="en-US,ar-EG")
            yield Button("Set language for picked apps", id="set-apps")

    def refresh_from(self, app: "DroidforgeApp") -> None:
        dev = self.device
        if dev is None:
            return
        app.background(lambda: (language.status(dev), language.candidates(dev)), self.show)

    def show(self, res: Tuple[language.LanguageStatus, List[str]]) -> None:
        st, cands = res
        msg = f"Device language: {st.describe()}"
        if st.chinese_first:
            msg += "\nChinese is first: open Settings > Language, add English and drag it to the top."
        self.query_one("#lang-status", Static).update(msg)
        sl = self.query_one("#apps", SelectionList)
        picked = set(sl.selected)
        sl.clear_options()
        sl.add_options([(p, p, p in picked) for p in cands])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        bid = event.button.id
        if bid == "open-lang":
            app.run_plan(lambda: language.open_language_settings(dev))
        elif bid == "recheck":
            self.refresh_from(app)
        elif bid == "open-app-lang":
            app.run_plan(lambda: language.open_app_languages(dev))
        elif bid == "set-apps":
            picked = list(self.query_one("#apps", SelectionList).selected)
            locs = self.query_one("#locales", Input).value.strip()
            app.run_plan(lambda: language.app_language_plan(dev, picked, locs))
        elif bid == "guide-1":
            self.setup = EnglishSetup(dev)
            setup = self.setup
            app.run_plan(setup.language_plan, on_done=lambda rep: app.notify(
                "When you have set English in Settings, press Re-check."))
        elif bid == "guide-2":
            app.run_plan(self._setup().keyboard_plan)
        elif bid == "guide-2b":
            app.run_plan(self._setup().chinese_keyboards_plan)
        elif bid == "guide-3":
            w = self._setup().start_watch()
            self.query_one("#caught", Static).update("Watching: open every screen that still shows Chinese...")
            if self.timer is not None:
                self.timer.stop()
            self.timer = self.set_interval(0.7, lambda: app.background(w.poll, self._polled))
        elif bid == "guide-3-stop":
            if self.timer is not None:
                self.timer.stop()
                self.timer = None
            setup = self._setup()
            app.run_plan(setup.apps_plan)

    def _setup(self) -> EnglishSetup:
        if self.setup is None:
            self.setup = EnglishSetup(self.device)
        return self.setup

    def _polled(self, pkg: Optional[str]) -> None:
        if self.setup is None or self.setup.watcher is None:
            return
        caught = self.setup.watcher.caught
        self.query_one("#caught", Static).update("Caught: " + (", ".join(caught) or "-"))

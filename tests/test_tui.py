"""Textual pilot tests: the TUI boots on the simulated phone and every screen works (P3.x)."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import ContentSwitcher

from droidforge import config
from droidforge.tui.app import SECTIONS, DroidforgeApp
from droidforge.tui.screens.modals import LimitsNote
from droidforge.tui.widgets.device_bar import DeviceBar, ExpertBanner
from droidforge.tui.widgets.log_pane import LogPane

SIZE = (140, 44)


async def boot(app: DroidforgeApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_boots_on_sim(df_home: Path) -> None:
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        assert app.session is not None and app.session.simulate
        bar = app.query_one(DeviceBar)
        assert "RMX8899" in bar.fields["device"] and "SIMULATED" in bar.fields["device"]
        assert app.query_one(ExpertBanner).has_class("hidden")
        await pilot.pause(0.3)
        log = app.query_one(LogPane)
        assert any("Connected" in str(line) for line in log.lines)
        backups = list((df_home / "data" / "backups").rglob("*-session.json"))
        assert backups, "session-start backup (R-11.3)"


async def test_navigation_and_log_toggle(df_home: Path) -> None:
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        for sid, _ in SECTIONS:
            app.show_section(sid)
            await pilot.pause()
            assert app.query_one(ContentSwitcher).current == sid
        log = app.query_one(LogPane)
        await pilot.press("l")
        assert log.has_class("hidden")
        await pilot.press("l")
        assert not log.has_class("hidden")


async def test_first_run_limits_note_shown_once(df_home: Path) -> None:
    app = DroidforgeApp(simulate=True)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        assert isinstance(app.screen, LimitsNote)
        await pilot.click("#ok")
        await pilot.pause()
        assert not isinstance(app.screen, LimitsNote)
    assert config.Config().get("limits_shown") is True
    app2 = DroidforgeApp(simulate=True)
    assert app2.show_limits is False


async def test_expert_banner(df_home: Path) -> None:
    app = DroidforgeApp(simulate=True, expert=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        assert not app.query_one(ExpertBanner).has_class("hidden")
        assert app.query_one(DeviceBar).fields["expert"] == "EXPERT"


async def test_no_device(df_home: Path, monkeypatch) -> None:
    monkeypatch.setattr("droidforge.adb.real.find_adb", lambda: None)
    app = DroidforgeApp(simulate=False, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        assert app.session is None and "pacman" in app.query_one(DeviceBar).fields["device"]

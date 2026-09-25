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


# ---------------------------------------------------------------- P3.2 widgets
from droidforge.engine.plan import Plan  # noqa: E402
from droidforge.features import debloat  # noqa: E402
from droidforge.tui.widgets.plan_preview import PlanPreview, commands_text  # noqa: E402
from droidforge.tui.widgets.tables import HistoryTable, PackageTable  # noqa: E402
from tests.helpers import UAD_SAMPLE  # noqa: E402


async def test_preview_from_debloat_action_cancel_leaves_sim_unchanged(df_home: Path) -> None:
    from droidforge.adb.sim import neo8_cn
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        before = phone.state()
        app.run_plan(debloat.force_plan(app.session.device, ["com.heytap.market", "com.oplus.sauhelper"], UAD_SAMPLE))
        await pilot.pause(0.3)
        assert isinstance(app.screen, PlanPreview)
        text = "\n".join(str(w.render()) for w in app.screen.query(".step"))
        assert "pm disable-user --user 0 com.heytap.market" in text and "undo: pm enable --user 0" in text
        assert "stage 2 if refused: pm suspend --user 0 com.heytap.market" in text
        await pilot.click("#cancel")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, PlanPreview)
        assert app.last_report.status == "cancelled" and phone.state() == before


async def test_preview_run_executes(df_home: Path) -> None:
    from droidforge.adb.sim import neo8_cn
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        app.run_plan(debloat.disable_plan(app.session.device, ["com.heytap.market"], UAD_SAMPLE))
        await pilot.pause(0.3)
        await pilot.click("#run")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.last_report.status == "done" and not phone.packages["com.heytap.market"].enabled
        assert app.session.history.entries()[-1].cmd == "pm disable-user --user 0 com.heytap.market"


async def test_typed_confirmation_gates_run(df_home: Path) -> None:
    from droidforge.adb.sim import neo8_cn
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        plan = debloat.disable_plan(app.session.device, ["com.oplus.camera"], UAD_SAMPLE)  # guarded
        assert plan.typed == ["I UNDERSTAND"]
        app.run_plan(plan)
        await pilot.pause(0.3)
        run = app.screen.query_one("#run")
        assert run.disabled
        app.screen.query_one("#typed-0").value = "i understand"
        await pilot.pause()
        assert run.disabled
        app.screen.query_one("#typed-0").value = "I UNDERSTAND"
        await pilot.pause()
        assert not run.disabled
        await pilot.click("#run")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.last_report.status == "done" and not phone.packages["com.oplus.camera"].enabled


async def test_empty_plan_shows_notes(df_home: Path) -> None:
    from droidforge.tui.screens.modals import MessageBox
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await boot(app, pilot)
        app.run_plan(Plan("Nothing", notes=["Already disabled: x"]))
        await pilot.pause()
        assert isinstance(app.screen, MessageBox)


def test_commands_text() -> None:
    from droidforge.engine import steps
    p = Plan("t", [steps.disable("com.x")])
    assert commands_text(p) == "# t\npm disable-user --user 0 com.x\n#   undo: pm enable --user 0 com.x"


async def test_package_table_filter_and_select(df_home: Path) -> None:
    from textual.app import App

    class T(App[None]):
        def compose(self):
            yield PackageTable(id="pt")
    app = T()
    async with app.run_test(size=SIZE) as pilot:
        from droidforge.adb.sim import sim_device
        from droidforge.log import Logger
        rows = debloat.scan(sim_device(log=Logger(1)), UAD_SAMPLE, "heytap")
        pt = app.query_one(PackageTable)
        pt.load(rows)
        await pilot.pause()
        pt.toggle("com.heytap.market")
        pt.toggle("com.heytap.mcs")
        pt.toggle("com.heytap.mcs")
        assert pt.selection() == ["com.heytap.market"]
        pt.query_one("#pkg-filter").value = "pictorial"
        await pilot.pause()
        assert [r.pkg for r in pt.visible_rows()] == ["com.heytap.pictorial"]
        assert pt.query_one("#pkg-table").row_count == 1


async def test_history_table(df_home: Path) -> None:
    from textual.app import App

    from droidforge.adb.sim import sim_device
    from droidforge.engine import executor
    from droidforge.engine.history import History
    from droidforge.log import Logger
    from tests.helpers import TELEMETRY, disable_plan, yes
    dev = sim_device(log=Logger(1))
    h = History(dev.serial)
    executor.run(disable_plan(TELEMETRY[:2]), dev, yes, history=h)

    class T(App[None]):
        def compose(self):
            yield HistoryTable(id="ht")
    app = T()
    async with app.run_test(size=SIZE) as pilot:
        ht = app.query_one(HistoryTable)
        ht.load(h.entries())
        await pilot.pause()
        assert ht.row_count == 2 and ht.current_id() == h.entries()[-1].id

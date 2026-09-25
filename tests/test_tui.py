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
from tests.helpers import UAD_SAMPLE, WRITE_PREFIXES  # noqa: E402


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


# ---------------------------------------------------------------- P3.3 sections
import json  # noqa: E402

from droidforge.adb.sim import IME_GBOARD, neo8_cn  # noqa: E402


async def settle(app: DroidforgeApp, pilot, t: float = 0.2) -> None:
    await pilot.pause(t)
    await app.workers.wait_for_complete()
    await pilot.pause()


async def run_previewed(app: DroidforgeApp, pilot) -> None:
    for _ in range(50):
        await pilot.pause(0.05)
        if isinstance(app.screen, PlanPreview) and app.screen.query("#run"):
            break
    assert isinstance(app.screen, PlanPreview), f"no preview, screen is {app.screen!r}"
    app.screen.query_one("#run").press()
    await settle(app, pilot)


def press(app: DroidforgeApp, selector: str) -> None:
    app.query_one(selector).press()


def write_uad_cache(df_home: Path) -> None:
    from droidforge.data import uad
    uad.cache_file().write_text(json.dumps(UAD_SAMPLE))


async def test_every_section_runs_one_action(df_home: Path) -> None:
    write_uad_cache(df_home)
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        # dashboard: doctor
        report = str(app.query_one("#doctor-report").render())
        assert "Everything droidforge checks looks healthy." in report

        # language: open Settings > Language, then per-app language for a picked user app
        app.show_section("language")
        await settle(app, pilot)
        assert "Chinese is first" in str(app.query_one("#lang-status").render())
        press(app, "#open-lang")
        await run_previewed(app, pilot)
        assert "android.settings.LOCALE_SETTINGS" in phone.started
        app.query_one("#lang-apps").select("com.whatsapp")
        app.query_one("#locales").value = "en-US,ar-EG"
        press(app, "#set-apps")
        await run_previewed(app, pilot)
        assert phone.packages["com.whatsapp"].locales == "en-US,ar-EG"

        # keyboard: Gboard
        app.show_section("keyboard")
        await settle(app, pilot)
        press(app, "#gboard")
        await run_previewed(app, pilot)
        assert phone.settings["secure"]["default_input_method"] == IME_GBOARD
        assert app.last_report.offer_reboot

        # dashboard: reboot check after the risky keyboard plan
        app.show_section("dashboard")
        await settle(app, pilot)
        app.sleep = lambda _: None
        press(app, "#reboot-check")
        await run_previewed(app, pilot)
        assert phone.boots == 1 and app.last_report.status == "done"

        # debloat: load, pick, disable
        app.show_section("debloat")
        await settle(app, pilot)
        table = app.query_one(PackageTable)
        assert "com.heytap.market" in [r.pkg for r in table.rows]
        table.toggle("com.heytap.market")
        press(app, "#act-disable")
        await run_previewed(app, pilot)
        assert not phone.packages["com.heytap.market"].enabled

        # history: undo the newest entry (the disable)
        app.show_section("history")
        await settle(app, pilot)
        ht = app.query_one(HistoryTable)
        assert ht.current_id() == app.session.history.entries()[-1].id
        press(app, "#undo")
        await run_previewed(app, pilot)
        assert phone.packages["com.heytap.market"].enabled


async def test_guide_watcher_offers_caught_apps(df_home: Path) -> None:
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.show_section("language")
        await settle(app, pilot)
        press(app, "#guide-3")
        phone.focused = "com.tencent.mm"
        await pilot.pause(1.0)
        await settle(app, pilot)
        phone.focused = "com.android.settings"
        await pilot.pause(1.0)
        await settle(app, pilot)
        assert "com.tencent.mm" in str(app.query_one("#caught").render())
        press(app, "#guide-3-stop")
        await run_previewed(app, pilot)
        assert phone.packages["com.tencent.mm"].locales == "en-US"


async def test_expert_toggle_asks_first(df_home: Path) -> None:
    from droidforge.tui.screens.modals import ConfirmBox
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmBox)
        app.screen.query_one("#yes").press()
        await pilot.pause()
        assert app.expert and app.session.expert
        assert not app.query_one(ExpertBanner).has_class("hidden")
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert not app.expert and app.query_one(ExpertBanner).has_class("hidden")


async def test_unexpected_error_is_shown_not_fatal(df_home: Path, monkeypatch) -> None:
    from droidforge.tui.screens.modals import MessageBox

    def boom(*a, **kw):
        raise RuntimeError("device vanished")
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        monkeypatch.setattr("droidforge.tui.app.executor.run", boom)
        app.run_plan(Plan("x", debloat.disable_plan(app.session.device, ["com.heytap.market"], UAD_SAMPLE).steps))
        await settle(app, pilot)
        assert isinstance(app.screen, MessageBox) and "device vanished" in str(app.screen.query_one("#body").render())
        assert app.is_running


async def test_quit_with_open_preview_cancels_and_exits(df_home: Path) -> None:
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    before = None
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        before = phone.state()
        app.run_plan(debloat.disable_plan(app.session.device, ["com.heytap.market"], UAD_SAMPLE))
        await pilot.pause(0.3)
        assert isinstance(app.screen, PlanPreview)
    # leaving the context exits the app while the preview is open: no hang, nothing sent
    assert phone.state() == before


async def test_selected_marker_is_visible(df_home: Path) -> None:
    from textual.app import App

    from droidforge.adb.sim import sim_device
    from droidforge.log import Logger

    class T(App[None]):
        def compose(self):
            yield PackageTable(id="pt")
    app = T()
    async with app.run_test(size=SIZE) as pilot:
        pt = app.query_one(PackageTable)
        pt.load(debloat.scan(sim_device(log=Logger(1)), UAD_SAMPLE, "market"))
        pt.toggle("com.heytap.market")
        await pilot.pause()
        cell = pt.query_one("#pkg-table").get_cell_at((0, 0))
        assert str(cell) == "[x]"


# ---------------------------------------------------------------- P3.4 themes, verbosity, dry-run
async def test_hacker_theme_registered_and_persisted(df_home: Path) -> None:
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert "hacker" in app.available_themes and "textual-light" in app.available_themes
        app.theme = "hacker"
        await pilot.pause()
    assert config.Config().get("theme") == "hacker"
    app2 = DroidforgeApp(simulate=True, show_limits=False)
    async with app2.run_test(size=SIZE) as pilot:
        await settle(app2, pilot)
        assert app2.theme == "hacker"


async def test_theme_switcher_key_opens_palette(df_home: Path) -> None:
    from textual.command import CommandPalette
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)


async def test_unknown_saved_theme_falls_back(df_home: Path) -> None:
    config.Config().set("theme", "no-such-theme")
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert app.theme == "textual-dark"


async def test_verbosity_key_cycles_and_persists(df_home: Path) -> None:
    from droidforge.log import LOG
    LOG.verbosity = 3
    app = DroidforgeApp(simulate=True, show_limits=False)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("v")
        assert LOG.verbosity == 1 and config.Config().get("verbosity") == 1
        assert app.query_one(DeviceBar).fields["verbosity"] == "verbosity 1"
        await pilot.press("v")
        await pilot.press("v")
        assert LOG.verbosity == 3


async def test_dry_run_toggle_sends_nothing(df_home: Path) -> None:
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("d")
        assert app.dry_run and app.query_one(DeviceBar).fields["dry_run"] == "DRY-RUN"
        before = phone.state()
        app.run_plan(debloat.disable_plan(app.session.device, ["com.heytap.market"], UAD_SAMPLE))
        await run_previewed(app, pilot)
        assert app.last_report.status == "dry-run" and phone.state() == before
        assert app.session.history.entries()[-1].dry_run
        await pilot.press("d")
        assert not app.dry_run


# ---------------------------------------------------------------- P3.5 breakage alert
from droidforge.tui.screens.breakage import BreakageAlert  # noqa: E402
from droidforge.tui.screens.modals import MessageBox  # noqa: E402


async def wait_for(app: DroidforgeApp, pilot, cls, n: int = 60):
    for _ in range(n):
        await pilot.pause(0.05)
        if isinstance(app.screen, cls):
            return app.screen
    raise AssertionError(f"{cls.__name__} never appeared (screen: {app.screen!r})")


async def test_break_ui_during_plan_shows_alert_and_fix_it_heals(df_home: Path) -> None:
    phone = neo8_cn()
    phone.side_effects[r"disable-user --user 0 com\.heytap\.market$"] = lambda ph: ph.break_ui()
    phone.side_effects[r"enable --user 0 com\.heytap\.market$"] = lambda ph: ph.unbreak_ui()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.run_plan(debloat.disable_plan(app.session.device, ["com.heytap.market", "com.opos.cs"], UAD_SAMPLE))
        await run_previewed(app, pilot)
        alert = await wait_for(app, pilot, BreakageAlert)
        text = str(alert.query_one("#alert-text").render())
        assert "Settings home screen" in text and "Disable permission monitoring" in text
        assert alert.query("#devopts")  # the user turns the switch off; droidforge only opens the screen
        alert.query_one("#fix").press()
        await run_previewed(app, pilot)
        healed = await wait_for(app, pilot, MessageBox)
        assert "healthy again" in str(healed.query_one("#body").render())
        assert phone.packages["com.heytap.market"].enabled and not phone.permission_monitoring_disabled


async def test_break_between_sessions_reported_at_start(df_home: Path) -> None:
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)            # dashboard doctor saves the healthy baseline
        app.run_plan(debloat.disable_plan(app.session.device, ["com.heytap.market"], UAD_SAMPLE))
        await run_previewed(app, pilot)
    phone.break_ui()                        # between sessions
    app2 = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app2.run_test(size=SIZE) as pilot:
        await settle(app2, pilot)
        alert = await wait_for(app2, pilot, BreakageAlert)
        text = str(alert.query_one("#alert-text").render())
        assert "Disable com.heytap.market" in text           # what droidforge changed since the healthy check
        assert alert.b.explained and alert.b.source == "startup"


async def test_unexplained_break_offers_only_manual_path(df_home: Path) -> None:
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
    phone.settings["system"]["font_scale"] = "1.3"
    n = len(phone.log)
    app2 = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app2.run_test(size=SIZE) as pilot:
        await settle(app2, pilot)
        alert = await wait_for(app2, pilot, BreakageAlert)
        assert not alert.query("#fix")
        assert "Reset all settings" in str(alert.query_one("#alert-text").render())
        alert.query_one("#ignore").press()
        await settle(app2, pilot)
        assert "Unresolved alerts" in str(app2.query_one("#alerts").render())
    writes = [c for c in phone.log[n:] if c.startswith(WRITE_PREFIXES)]
    assert writes == []


# ---------------------------------------------------------------- P4.10 Phase 4 sections
async def test_phase4_sections_run_one_action_each(df_home: Path) -> None:
    write_uad_cache(df_home)
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.show_section("privacy")
        await settle(app, pilot)
        press(app, "#dns")
        await run_previewed(app, pilot)
        assert phone.settings["global"]["private_dns_specifier"] == "dns.adguard-dns.com"

        app.show_section("firewall")
        await settle(app, pilot)
        app.query_one("#fw-apps").select("com.whatsapp")
        press(app, "#fw-block")
        await run_previewed(app, pilot)
        assert "com.whatsapp" in phone.firewall_blocked

        app.show_section("apps")
        await settle(app, pilot)
        press(app, "#swap")
        await run_previewed(app, pilot)
        assert phone.roles["android.app.role.BROWSER"] == ["org.mozilla.fenix"]

        app.show_section("keepalive")
        await settle(app, pilot)
        app.query_one("#ka-apps").select("org.telegram.messenger")
        press(app, "#ka-on")
        await run_previewed(app, pilot)
        assert "org.telegram.messenger" in phone.deviceidle
        press(app, "#datetime")
        await run_previewed(app, pilot)
        assert phone.started[-1] == "android.settings.DATE_SETTINGS"


async def test_ota_prompt_on_connect(df_home: Path) -> None:
    from droidforge.engine.profile import Profile
    from droidforge.tui.screens.modals import ConfirmBox
    phone = neo8_cn()
    prof = Profile.for_device(phone.serial)
    prof.fingerprint = "realme/RMX8899/old:16/OLD/1:user/release-keys"
    prof.disabled = ["com.heytap.mcs"]
    prof.save()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=SIZE) as pilot:
        for _ in range(80):
            await pilot.pause(0.05)
            if isinstance(app.screen, ConfirmBox) and app.screen.query("#yes"):
                break
        assert "System update" in str(app.screen.query_one("Label").render())
        app.screen.query_one("#yes").press()
        await run_previewed(app, pilot)
        assert not phone.packages["com.heytap.mcs"].enabled
        assert any("notify-send" in c for c in phone.host_log)

"""P4.7: keep-alive (R-6.3) and power permissions (R-6.4)."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.features import keepalive, powerperms
from tests.helpers import yes


def test_keepalive_steps_and_undo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    prof, h = Profile.for_device(phone.serial), History(phone.serial)
    plan = keepalive.keepalive_plan(sim, ["com.whatsapp"])
    cmds = [s.cmd for s in plan.steps]
    assert cmds == ["dumpsys deviceidle whitelist +com.whatsapp",
                    "cmd appops set com.whatsapp RUN_ANY_IN_BACKGROUND allow",
                    "am set-standby-bucket com.whatsapp active",
                    "am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:com.whatsapp"]
    assert plan.steps[2].undo == ["am set-standby-bucket com.whatsapp frequent"]
    assert any("Developer-options" in n for n in plan.notes)
    rep = executor.run(plan, sim, yes, profile=prof, history=h)
    assert rep.status == "done"
    assert "com.whatsapp" in phone.deviceidle and phone.standby["com.whatsapp"] == 10
    assert prof.keepalive == ["com.whatsapp"] and phone.started[-1] == "app-info package:com.whatsapp"
    assert keepalive.status(sim, "com.whatsapp") == {"whitelist": "user", "background": "allow", "bucket": "active"}
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, profile=prof, history=h)
    assert phone.state() == initial and prof.keepalive == []


def test_keepalive_skips_what_is_already_set(sim, phone: FakePhone) -> None:
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes)
    again = keepalive.keepalive_plan(sim, ["com.whatsapp"])
    assert [s.risk for s in again.steps] == ["read"]


def test_keepalive_locked_needs_expert(sim) -> None:
    plan = keepalive.keepalive_plan(sim, ["com.android.systemui", "com.whatsapp"])
    assert any("Locked, skipped: com.android.systemui" in n for n in plan.notes)
    assert all(s.pkg == "com.whatsapp" for s in plan.steps)


def test_power_perms(sim, phone: FakePhone) -> None:
    pkg = "net.dinglisch.android.taskerm"
    assert powerperms.installed_presets(sim) == []
    phone.add(pkg, system=False, perms={"android.permission.WRITE_SECURE_SETTINGS": False})
    sim.invalidate()
    assert powerperms.installed_presets(sim) == ["tasker"]
    plan = powerperms.grant_plan(sim, {pkg: ["WRITE_SECURE_SETTINGS", "DUMP", "PACKAGE_USAGE_STATS"]})
    cmds = [s.cmd for s in plan.steps]
    assert cmds == [f"pm grant {pkg} android.permission.WRITE_SECURE_SETTINGS",
                    f"cmd appops set {pkg} GET_USAGE_STATS allow"]
    assert any("does not request DUMP" in n for n in plan.notes) and powerperms.REFUSAL_NOTE in plan.notes
    prof = Profile.for_device(phone.serial)
    assert executor.run(plan, sim, yes, profile=prof).status == "done"
    assert prof.powerperms == {pkg: ["android.permission.WRITE_SECURE_SETTINGS"]}
    assert powerperms.preset_plan(sim, ["tasker"]).steps == []          # already granted


def test_refused_grant_is_reported(sim, phone: FakePhone) -> None:
    pkg = "net.dinglisch.android.taskerm"
    phone.add(pkg, system=False, perms={"android.permission.WRITE_SECURE_SETTINGS": False})
    phone.side_effects = {}
    orig = sim.backend._pm_perm

    def refuse(verb, name, perm):
        from droidforge.adb.backend import RunResult
        return RunResult(255, "", "java.lang.SecurityException: grant refused by ROM")
    sim.backend._pm_perm = refuse
    rep = executor.run(powerperms.preset_plan(sim, ["tasker"]), sim, yes)
    sim.backend._pm_perm = orig
    assert rep.status == "done" and not rep.results[0].ok and "refused" in rep.results[0].err


# ---------------------------------------------------------------- picking apps
def test_parse_selection() -> None:
    items = ["a.one", "b.two", "c.three", "d.four", "e.five"]
    assert keepalive.parse_selection("1,3", items) == ["a.one", "c.three"]
    assert keepalive.parse_selection("2-4 1", items) == ["b.two", "c.three", "d.four", "a.one"]
    assert keepalive.parse_selection("9, x, com.whatsapp", items) == ["com.whatsapp"]
    assert keepalive.parse_selection("all", items) == items and keepalive.parse_selection("", items) == []


def test_statuses_are_batched(sim, phone: FakePhone) -> None:
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes)
    phone.deviceidle.add("com.tencent.mm")
    pkgs = keepalive.candidates(sim)
    n = len(phone.log)
    st = keepalive.statuses(sim, pkgs)
    assert st["com.whatsapp"] == "kept alive" and st["com.tencent.mm"] == "partly" and st["org.telegram.messenger"] == ""
    assert len(phone.log) - n <= 3


def test_cli_picker(monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    phone = neo8_cn()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=phone, **kw))
    items = sorted(p for p, pk in phone.packages.items() if not pk.system)
    picks = iter([f"{items.index('com.whatsapp') + 1},{items.index('org.telegram.messenger') + 1}"])
    monkeypatch.setattr("builtins.input", lambda q: next(picks))
    assert cli.main(["-q", "--simulate", "--yes", "keepalive"]) == 0
    out = capsys.readouterr().out
    assert " 1) " in out and "Pick apps" not in out   # prompt went to input(), the list to stdout
    assert {"com.whatsapp", "org.telegram.messenger"} <= phone.deviceidle
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert cli.main(["-q", "--simulate", "--yes", "keepalive"]) == 1   # Enter = cancel, nothing sent
    out = capsys.readouterr().out
    assert "[kept alive]" in out


async def test_tui_search_keeps_selection_and_shows_status(df_home) -> None:
    from droidforge.adb.sim import neo8_cn
    from droidforge.tui.app import DroidforgeApp
    from droidforge.tui.screens.common import AppPicker
    phone = neo8_cn()
    phone.deviceidle.add("com.tencent.mm")
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        app.show_section("keepalive")
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        picker = app.query_one("#ka-apps", AppPicker)
        assert picker.status["com.tencent.mm"] == "partly"
        picker.select("com.whatsapp")
        picker.query_one("Input").value = "telegram"
        await pilot.pause()
        from textual.widgets import SelectionList
        sl = picker.query_one(SelectionList)
        assert sl.option_count == 1
        sl.select_all()
        await pilot.pause()
        picker.query_one("Input").value = ""
        await pilot.pause()
        assert picker.picked() == ["com.whatsapp", "org.telegram.messenger"]

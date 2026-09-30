"""P4.7: keep-alive (R-6.3) and power permissions (R-6.4)."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.features import keepalive, powerperms
from tests.helpers import yes


def test_keepalive_steps_and_undo(sim, phone: FakePhone) -> None:
    wa = phone.packages["com.whatsapp"]
    wa.perms[keepalive.EXACT_ALARM] = True     # asks for exact alarms
    wa.hibernating = True
    initial = phone.clone().state()
    prof, h = Profile.for_device(phone.serial), History(phone.serial)
    plan = keepalive.keepalive_plan(sim, ["com.whatsapp"])
    cmds = [s.cmd for s in plan.steps]
    assert cmds == ["dumpsys deviceidle whitelist +com.whatsapp",
                    "cmd appops set com.whatsapp RUN_ANY_IN_BACKGROUND allow",
                    "cmd appops set com.whatsapp RUN_IN_BACKGROUND allow",
                    "cmd appops set com.whatsapp START_FOREGROUND allow",
                    "cmd appops set com.whatsapp SYSTEM_EXEMPT_FROM_POWER_RESTRICTIONS allow",
                    "cmd appops set com.whatsapp SYSTEM_ALERT_WINDOW allow",
                    "cmd appops set com.whatsapp AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore",
                    "cmd appops set com.whatsapp SCHEDULE_EXACT_ALARM allow",
                    "cmd app_hibernation set-state com.whatsapp false",
                    "am set-standby-bucket com.whatsapp active",
                    "am set-bg-restriction-level --user 0 com.whatsapp exempted",
                    "am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:com.whatsapp"]
    assert plan.steps[3].undo == ["cmd appops set com.whatsapp START_FOREGROUND default"]
    assert plan.steps[6].undo == ["cmd appops set com.whatsapp AUTO_REVOKE_PERMISSIONS_IF_UNUSED default"]
    assert plan.steps[8].undo == ["cmd app_hibernation set-state com.whatsapp true"]
    assert plan.steps[9].undo == ["am set-standby-bucket com.whatsapp frequent"]
    assert plan.steps[10].undo == ["am set-bg-restriction-level --user 0 com.whatsapp adaptive_bucket"]
    assert any("Developer-options" in n for n in plan.notes)
    rep = executor.run(plan, sim, yes, profile=prof, history=h)
    assert rep.status == "done"
    assert "com.whatsapp" in phone.deviceidle and phone.standby["com.whatsapp"] == 10
    assert prof.keepalive == ["com.whatsapp"] and phone.started[-1] == "app-info package:com.whatsapp"
    assert keepalive.status(sim, "com.whatsapp") == {"whitelist": "user", "background": "allow", "bucket": "active"}
    assert phone.bg_level["com.whatsapp"] == "exempted"
    assert wa.appops["SYSTEM_ALERT_WINDOW"] == "allow" and wa.appops["AUTO_REVOKE_PERMISSIONS_IF_UNUSED"] == "ignore"
    assert wa.appops["SCHEDULE_EXACT_ALARM"] == "allow" and not wa.hibernating
    assert "pop-ups" in plan.steps[-1].label and any("pop-ups" in n for n in plan.notes)
    assert all(r.effect == "changed" for r in rep.results if r.requested.risk != "read")
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, profile=prof, history=h)
    assert phone.state() == initial and prof.keepalive == []


def test_keepalive_skips_what_is_already_set(sim, phone: FakePhone) -> None:
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes)
    again = keepalive.keepalive_plan(sim, ["com.whatsapp"])
    assert [s.risk for s in again.steps] == ["read"]


def test_keepalive_extras_only_where_needed(sim, phone: FakePhone) -> None:
    cmds = [s.cmd for s in keepalive.keepalive_plan(sim, ["com.whatsapp"]).steps]
    assert not any("SCHEDULE_EXACT_ALARM" in c or "app_hibernation" in c for c in cmds)   # no exact alarms asked
    phone.props["ro.build.version.sdk"] = "29"
    sim.forget_props()
    phone.packages["com.whatsapp"].perms[keepalive.EXACT_ALARM] = True
    phone.packages["com.whatsapp"].hibernating = True
    cmds = [s.cmd for s in keepalive.keepalive_plan(sim, ["com.whatsapp"]).steps]
    assert not any(x in c for c in cmds for x in ("AUTO_REVOKE", "SCHEDULE_EXACT_ALARM", "app_hibernation"))
    assert keepalive.why_lines(sim, ["com.whatsapp"])[0] == (
        "com.whatsapp: no exits recorded (not killed since boot, or Android < 11)")


def test_why_lines_name_the_killer_and_the_fix(sim) -> None:
    lines = keepalive.why_lines(sim, ["com.whatsapp", "org.telegram.messenger"])
    assert lines[0] == "com.whatsapp:"
    assert "OTHER: killed by ColorOS's app killer (Athena)" in lines[1] and "Allow auto launch" in lines[2]
    assert "USER_REQUESTED" in lines[3] and "lock the app's card in Recents" in lines[4]
    assert lines[5] == "  kill log (am_kill):"
    assert "ColorOS's app killer (Athena) [OplusAthenaAmManager]" in lines[6] and "Allow auto launch" in lines[7]
    assert "force-stopped" in lines[8] and "[remove task]" in lines[8] and "Recents" in lines[9]
    assert lines[10].startswith("org.telegram.messenger: no exits recorded")
    assert "cached-app limit" in lines[12] and "[cached #33]" in lines[12] and "keepalive --phone-wide" in lines[13]
    assert len(lines) == 14 and all(x.isascii() for x in lines)


def test_why_lines_warn_without_google_play_services(sim, phone: FakePhone) -> None:
    phone.packages["com.google.android.gms"].present = False
    assert keepalive.why_lines(sim, ["com.whatsapp"])[-1] == keepalive.NO_GMS
    assert keepalive.NO_GMS in keepalive.keepalive_plan(sim, ["com.whatsapp"]).notes
    assert keepalive.why_lines(sim, []) == []


def test_phone_wide_plan_and_one_click_undo(sim, phone: FakePhone) -> None:
    phone.settings["global"]["cached_apps_freezer"] = "enabled"
    phone.device_config["activity_manager"]["max_cached_processes"] = "32"
    initial = phone.clone().state()
    prof, h = Profile.for_device(phone.serial), History(phone.serial)
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes, profile=prof, history=h)
    after_apps = phone.clone().state()
    plan = keepalive.phone_wide_plan(sim)
    assert [s.cmd for s in plan.steps] == [
        "device_config set_sync_disabled_for_tests persistent",
        "settings put global settings_enable_monitor_phantom_procs false",
        "device_config put activity_manager max_phantom_processes 2147483647",
        "device_config put activity_manager max_cached_processes 128",
        "settings put global cached_apps_freezer disabled"]
    assert [s.undo for s in plan.steps] == [
        ["device_config set_sync_disabled_for_tests none"],
        ["settings delete global settings_enable_monitor_phantom_procs"],
        ["device_config delete activity_manager max_phantom_processes"],
        ["device_config put activity_manager max_cached_processes 32"],
        ["settings put global cached_apps_freezer enabled"]]
    assert all(s.risk == "risky" and s.pkg is None for s in plan.steps)
    assert any("--phone-wide-undo" in n for n in plan.notes) and any("Reboot" in n for n in plan.notes)
    rep = executor.run(plan, sim, yes, profile=prof, history=h)
    assert rep.status == "done" and all(r.effect == "changed" for r in rep.results)
    assert phone.devcfg_sync == "persistent" and phone.settings["global"]["cached_apps_freezer"] == "disabled"
    assert set(prof.keepalive_prev) == {s.touches[0] for s in plan.steps}
    assert not keepalive.phone_wide_plan(sim).steps                     # nothing left to do
    # the one-click undo: back to exactly what was there before, the per-app keep-alive stays
    undo = keepalive.phone_wide_undo_plan(sim, prof.keepalive_prev)
    assert [s.cmd for s in undo.steps] == [
        "settings put global cached_apps_freezer enabled",
        "device_config put activity_manager max_cached_processes 32",
        "device_config delete activity_manager max_phantom_processes",
        "settings delete global settings_enable_monitor_phantom_procs",
        "device_config set_sync_disabled_for_tests none"]
    assert executor.run(undo, sim, yes, profile=prof, history=h).status == "done"
    assert phone.state() == after_apps and phone.state() != initial and prof.keepalive_prev == {}
    assert not keepalive.phone_wide_undo_plan(sim, prof.keepalive_prev).steps


def test_phone_wide_undo_without_a_record_goes_to_defaults(sim, phone: FakePhone) -> None:
    executor.run(keepalive.phone_wide_plan(sim), sim, yes)             # profile lost / applied elsewhere
    phone.device_config["activity_manager"]["max_cached_processes"] = "64"   # the user changed it since
    undo = keepalive.phone_wide_undo_plan(sim)
    assert [s.cmd for s in undo.steps] == [
        "settings delete global cached_apps_freezer",
        "device_config delete activity_manager max_phantom_processes",
        "settings delete global settings_enable_monitor_phantom_procs",
        "device_config set_sync_disabled_for_tests none"]
    executor.run(undo, sim, yes)
    assert phone.device_config["activity_manager"] == {"max_cached_processes": "64"}
    assert phone.devcfg_sync == "none" and "cached_apps_freezer" not in phone.settings["global"]


def test_phone_wide_skips_what_the_android_version_lacks(sim, phone: FakePhone) -> None:
    phone.props["ro.build.version.sdk"] = "29"
    sim.forget_props()
    cmds = [s.cmd for s in keepalive.phone_wide_plan(sim).steps]
    assert not any("sync" in c or "freezer" in c for c in cmds) and len(cmds) == 3


def test_reapply_brings_keepalive_back_after_an_ota(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes, profile=prof)
    executor.run(keepalive.child_process_plan(sim), sim, yes, profile=prof)
    assert not [s for s in prof.reapply(sim).steps]                     # nothing to do yet
    phone.standby["com.whatsapp"] = 40                                  # the bucket decays
    phone.device_config["activity_manager"].clear()                     # an OTA wipes device_config
    cmds = [s.cmd for s in prof.reapply(sim).steps]
    assert cmds == ["am set-standby-bucket com.whatsapp active",
                    "device_config put activity_manager max_phantom_processes 2147483647"]  # only what was chosen
    assert "max_cached" not in " ".join(cmds) and "keepalive_prev" not in prof.export()


def test_cli_phone_wide_and_undo(monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    ph = neo8_cn()
    before = ph.clone().state()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=ph, **kw))
    assert cli.main(["-q", "--simulate", "--yes", "keepalive", "--phone-wide"]) == 0
    assert ph.settings["global"]["cached_apps_freezer"] == "disabled" and ph.devcfg_sync == "persistent"
    assert cli.main(["-q", "--simulate", "--yes", "keepalive", "--phone-wide-undo"]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "Undo just this plan" in out
    assert ph.state() == before


def test_parse_exit_info_real_format() -> None:
    from droidforge.adb import parse
    out = """ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)
Last Timestamp of Persistence Into Persistent Storage: 2026-09-27 10:00:00.000
  package: salah.rasoulallah.com
    Historical Process Exit for uid=10231
        ApplicationExitInfo #0:
          timestamp=2026-09-27 09:41:12.345 pid=8812 realUid=10231 packageUid=10231 definingUid=10231 user=0
          process=salah.rasoulallah.com reason=4 (APP CRASH(EXCEPTION)) subreason=0 (UNKNOWN) status=0
          importance=125 pss=0.00 rss=0.00 description=crash state=empty trace=null
        ApplicationExitInfo #1:
          timestamp=2026-09-27 03:02:01.000 pid=7001 realUid=10231 packageUid=10231 definingUid=10231 user=0
          process=salah.rasoulallah.com:service reason=3 (LOW_MEMORY) subreason=5 (TOO MANY CACHED) status=0
          importance=400 pss=0.00 rss=0.00 description=null state=empty trace=null
"""
    assert parse.exit_info(out) == [
        {"ts": "2026-09-27 09:41:12", "process": "salah.rasoulallah.com", "reason": "CRASH", "subreason": "",
         "description": "crash"},
        {"ts": "2026-09-27 03:02:01", "process": "salah.rasoulallah.com:service", "reason": "LOW_MEMORY",
         "subreason": "TOO MANY CACHED", "description": ""}]
    assert parse.exit_info("ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)\n") == []


def test_cli_keepalive_why(monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    ph = neo8_cn()
    before = ph.clone().state()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=ph, **kw))
    assert cli.main(["-q", "--simulate", "keepalive", "--why"]) == 1          # nothing kept alive yet
    assert "No app is kept alive" in capsys.readouterr().out
    assert cli.main(["-q", "--simulate", "keepalive", "--why", "com.whatsapp"]) == 0
    out = capsys.readouterr().out
    assert "Athena" in out and "USER_REQUESTED" in out and out.isascii()
    assert ph.state() == before                                                 # read-only


def test_child_processes_is_its_own_plan_and_undoes_alone(sim, phone: FakePhone, capsys) -> None:
    initial = phone.clone().state()
    h = History(phone.serial)
    executor.run(keepalive.keepalive_plan(sim, ["com.whatsapp"]), sim, yes, history=h)
    after_apps = phone.clone().state()
    plan = keepalive.child_process_plan(sim)
    assert [s.cmd for s in plan.steps] == [
        "settings put global settings_enable_monitor_phantom_procs false",
        "device_config put activity_manager max_phantom_processes 2147483647"]
    assert [s.undo for s in plan.steps] == [["settings delete global settings_enable_monitor_phantom_procs"],
                                            ["device_config delete activity_manager max_phantom_processes"]]
    assert all(s.risk == "risky" and s.pkg is None for s in plan.steps)
    rep = executor.run(plan, sim, yes, history=h)
    assert rep.status == "done" and all(r.effect == "changed" for r in rep.results)
    assert phone.settings["global"]["settings_enable_monitor_phantom_procs"] == "false"
    ids = [r.history_id for r in rep.results]
    executor.run(h.undo(ids), sim, yes, history=h)          # only this plan: the per-app keep-alive stays
    assert phone.state() == after_apps and phone.state() != initial
    assert keepalive.child_process_plan(sim).steps       # offered again after the undo


def test_child_processes_keeps_existing_values_for_undo(sim, phone: FakePhone) -> None:
    phone.settings["global"]["settings_enable_monitor_phantom_procs"] = "true"
    phone.device_config["activity_manager"]["max_phantom_processes"] = "32"
    plan = keepalive.child_process_plan(sim)
    assert [s.undo for s in plan.steps] == [["settings put global settings_enable_monitor_phantom_procs true"],
                                            ["device_config put activity_manager max_phantom_processes 32"]]


def test_cli_child_processes_prints_its_own_undo(monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    ph = neo8_cn()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=ph, **kw))
    assert cli.main(["-q", "--simulate", "--yes", "keepalive", "--child-processes"]) == 0
    out = capsys.readouterr().out
    assert "Undo just this plan: droidforge undo " in out and "Recovery script" in out and out.isascii()
    assert ph.device_config["activity_manager"]["max_phantom_processes"] == "2147483647"


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

"""P1.6: per-device profile - desired state, re-apply, export/import (previewed), legacy import."""

from __future__ import annotations

import json
from pathlib import Path

from droidforge.adb.sim import FakePhone, neo8_cn, sim_device
from droidforge.engine import executor, guard
from droidforge.engine.plan import Plan
from droidforge.engine.profile import Profile, import_plan, legacy_import_plan, legacy_profile
from droidforge.log import Logger
from tests.helpers import TELEMETRY, disable_plan, force_step, yes


def test_roundtrip(df_home: Path) -> None:
    p = Profile.for_device("SER1")
    p.disabled = ["com.b", "com.a"]
    p.neutered = {"com.c": ["android.permission.CAMERA"]}
    p.save()
    q = Profile.for_device("SER1")
    assert q.disabled == ["com.b", "com.a"] and q.neutered == p.neutered and q.serial == "SER1"
    assert q == p


def test_executor_updates_profile(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    plan = disable_plan(TELEMETRY[:2])
    plan.steps.append(force_step("com.oplus.sauhelper"))
    rep = executor.run(plan, sim, yes, profile=prof)
    assert rep.status == "done"
    saved = Profile.for_device(phone.serial)
    assert saved.disabled == sorted(TELEMETRY[:2]) and saved.suspended == ["com.oplus.sauhelper"]
    assert saved.fingerprint == phone.props["ro.build.fingerprint"] and saved.model == "realme RMX8899"
    assert saved.healthy_baseline["settings_home"]["ok"] is True


def test_undo_updates_profile(sim, phone: FakePhone) -> None:
    from droidforge.engine.history import History
    prof, h = Profile.for_device(phone.serial), History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:2]), sim, yes, profile=prof, history=h)
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, profile=prof, history=h)
    assert Profile.for_device(phone.serial).disabled == []


def test_reapply_after_ota(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(disable_plan(TELEMETRY[:3]), sim, yes, profile=prof)
    # "OTA": the update re-enabled two packages and changed the fingerprint
    phone.packages[TELEMETRY[0]].enabled = True
    phone.packages[TELEMETRY[2]].enabled = True
    phone.props["ro.build.fingerprint"] = "realme/RMX8899/new:16/NEW/1:user/release-keys"
    sim.forget_props()
    assert prof.ota_changed(sim)
    plan = prof.reapply(sim)
    assert sorted(s.cmd for s in plan.steps) == sorted([f"pm disable-user --user 0 {TELEMETRY[0]}",
                                                        f"pm disable-user --user 0 {TELEMETRY[2]}"])
    assert executor.run(plan, sim, yes, profile=prof).status == "done"
    assert all(not phone.packages[p].enabled for p in TELEMETRY[:3])


def test_reapply_neuter_and_ime(sim, phone: FakePhone) -> None:
    prof = Profile(neutered={"com.heytap.market": ["android.permission.POST_NOTIFICATIONS"]},
                   ime_disabled=["com.baidu.input_oppo/.ImeService", "com.sohu.inputmethod.sogouoem/.SogouIME"])
    plan = prof.reapply(sim)
    cmds = [s.cmd for s in plan.steps]
    assert "pm revoke com.heytap.market android.permission.POST_NOTIFICATIONS" in cmds
    assert "cmd appops set com.heytap.market RUN_ANY_IN_BACKGROUND ignore" in cmds
    assert "ime disable com.baidu.input_oppo/.ImeService" in cmds
    assert not any("sogou" in c for c in cmds)  # current keyboard is never switched off
    assert any("current keyboard" in n for n in plan.notes)
    for s in plan.steps:
        guard.check(s, sim)


def test_export_import_is_a_previewed_plan(sim, phone: FakePhone, df_home: Path) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(disable_plan(TELEMETRY[:2]), sim, yes, profile=prof)
    data = prof.export()
    assert "serial" not in data and "fingerprint" not in data and "healthy_baseline" not in data

    other_phone = neo8_cn()
    other_phone.serial = "OTHER"
    other = sim_device(other_phone, log=Logger(1))
    before = other_phone.state()
    plan = import_plan(json.loads(json.dumps(data)), other)
    assert [s.cmd for s in plan.steps] == [f"pm disable-user --user 0 {p}" for p in sorted(TELEMETRY[:2])]
    assert other_phone.state() == before                          # nothing applied by building the plan
    assert not Profile.for_device("OTHER").disabled                # stored profile untouched until it runs


def test_legacy_import_ignores_language_keys(sim, tmp_path: Path) -> None:
    legacy = {"disabled": ["com.heytap.market"], "removed": ["com.opos.cs"], "suspended": [],
              "neutered": {"com.heytap.mcs": ["android.permission.POST_NOTIFICATIONS"]},
              "english": ["com.tencent.mm", "com.android.settings"], "english_prev": {"com.tencent.mm": "zh-CN"},
              "device_locale_prev": "zh-Hans-CN", "system_locales_prev": "zh-Hans-CN,en-US", "fallback": "ar-EG",
              "ime_disabled": [], "verbosity": 3}
    f = tmp_path / "cnrom_state.json"
    f.write_text(json.dumps(legacy))
    prof = legacy_profile(f)
    assert prof.english == [] and prof.app_locales == {} and prof.disabled == ["com.heytap.market"]
    plan = legacy_import_plan(f, sim)
    cmds = [s.cmd for s in plan.steps]
    assert "pm uninstall -k --user 0 com.opos.cs" in cmds and "pm disable-user --user 0 com.heytap.market" in cmds
    assert not any("locale" in c for c in cmds)
    assert any("english" in n and "device_locale_prev" in n for n in plan.notes)


def test_vetter_skips_packages(sim) -> None:
    prof = Profile(disabled=["com.android.systemui", TELEMETRY[0]])
    plan = prof.reapply(sim, vet=lambda p: "locked" if "systemui" in p else "")
    assert [s.pkg for s in plan.steps] == [TELEMETRY[0]]
    assert any("Skipped com.android.systemui: locked" in n for n in plan.notes)


def test_dry_run_does_not_change_profile(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(Plan("x", disable_plan(TELEMETRY[:1]).steps), sim, yes, profile=prof, dry_run=True)
    assert prof.disabled == []

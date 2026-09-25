"""P1.3: health probes (R-11.7) + baseline compare (P0, P11)."""

from __future__ import annotations

from droidforge.adb.sim import IME_GBOARD, FakePhone
from droidforge.data.device_keys import PERMISSION_MONITORING_PROP
from droidforge.engine import guard, health


def test_healthy_sim_reports_nothing(sim) -> None:
    h = health.run(sim)
    assert h.failing == []
    assert health.compare(h, health.run(sim)) == []
    assert h.get("settings_home").value.endswith("OplusSettingsHomepageActivity")
    assert h.get("permission_monitoring").value == "off"


def test_health_is_read_only(sim, phone: FakePhone) -> None:
    before, n = phone.state(), len(phone.log)
    health.run(sim)
    assert phone.state() == before
    assert all(not guard.check_read(c, sim).write for c in phone.log[n:])


def test_break_ui_is_two_plus_regressions(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.break_ui()
    now = health.run(sim)
    regs = health.compare(base, now)
    names = {r.probe for r in regs}
    assert len(regs) >= 2
    assert {"settings_home", "permission_ui", "cfg:mMaterialColor", "permission_monitoring"} <= names
    colour = next(r for r in regs if r.probe == "cfg:mMaterialColor")
    assert colour.before == "17179869184" and colour.after == "0" and "material_color_value" in colour.message
    assert {p.name for p in now.failing} >= {"settings_home", "permission_ui", "cfg:mMaterialColor"}


def test_permission_monitoring_reported_even_if_baseline_had_it_on(sim, phone: FakePhone) -> None:
    phone.permission_monitoring_disabled = True
    base = health.run(sim)
    regs = health.compare(base, health.run(sim))
    assert [r.probe for r in regs] == ["permission_monitoring"]
    assert "Turn it off: Developer options > bottom of the list, then reboot" in regs[0].message
    assert health.advice(regs)[0].startswith("1) If the 'Disable permission monitoring'")


def test_permission_monitoring_unknown_on_real_phone(sim, phone: FakePhone) -> None:
    del phone.props[PERMISSION_MONITORING_PROP]  # a ROM without the property: `getprop` -> empty
    h = health.run(sim)
    assert h.get("permission_monitoring").value == "unknown" and h.get("permission_monitoring").ok is None
    assert health.compare(h, health.run(sim)) == []


def test_declared_changes_are_not_regressions(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.imes[IME_GBOARD] = True
    phone.settings["secure"]["default_input_method"] = IME_GBOARD
    now = health.run(sim)
    assert [r.probe for r in health.compare(base, now)] == ["ime"]
    assert health.compare(base, now, declared=["ime:default"]) == []


def test_display_changes_are_regressions(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.settings["system"]["font_scale"] = "1.3"
    phone.config.font_scale = "1.3"
    phone.config.night = False
    names = {r.probe for r in health.compare(base, health.run(sim))}
    assert {"font_scale", "cfg:fontScale", "night", "cfg:night"} <= names


def test_language_change_in_config_is_a_regression(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.set_device_locales(["en-US"])
    assert "cfg:locales" in {r.probe for r in health.compare(base, health.run(sim))}


def test_crash_and_dead_systemui(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.crash("com.android.settings")
    phone.packages["com.android.systemui"].running = False
    regs = {r.probe: r for r in health.compare(base, health.run(sim))}
    assert "com.android.settings" in regs["crashes"].message
    assert "alive:com.android.systemui" in regs


def test_disabled_launcher_is_caught(sim, phone: FakePhone) -> None:
    base = health.run(sim)
    phone.packages["com.android.launcher"].enabled = False
    regs = {r.probe for r in health.compare(base, health.run(sim))}
    assert "launcher" in regs


def test_report_roundtrip(sim) -> None:
    h = health.run(sim)
    assert health.HealthReport.from_dict(h.to_dict()).to_dict() == h.to_dict()


def test_advice_without_switch_starts_with_undo() -> None:
    assert health.advice([])[0].startswith("2) Undo")
    assert "Reset all settings" in health.advice([])[-1]

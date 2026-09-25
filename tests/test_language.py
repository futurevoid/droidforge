"""P2.1: language (R-3.1 read + open Settings; R-3.2 per-app language for picked user apps only)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor, guard
from droidforge.engine.history import History
from droidforge.features import language
from tests.helpers import yes

SRC = Path(language.__file__)


def test_status_reads_only(sim, phone: FakePhone) -> None:
    before = phone.state()
    st = language.status(sim)
    assert st.chinese_first and not st.english_first and st.first == "zh-Hans-CN"
    assert phone.state() == before
    phone.set_device_locales(["en-US", "ar-EG"])
    assert language.status(sim).english_first


def test_open_language_settings_then_recheck(sim, phone: FakePhone) -> None:
    before_state = phone.state()
    st = language.status(sim)
    plan = language.open_language_settings(sim)
    assert [s.cmd for s in plan.steps] == ["am start -a android.settings.LOCALE_SETTINGS"]
    assert any("drag it to the top" in n for n in plan.notes) and any("Arabic" in n for n in plan.notes)
    assert executor.run(plan, sim, yes).status == "done"
    assert phone.started == ["android.settings.LOCALE_SETTINGS"] and phone.state() == before_state
    assert language.recheck(st, sim).startswith("Device language unchanged")
    phone.set_device_locales(["en-US", "zh-Hans-CN"])   # the user did it in Settings
    assert "is now en-US" in language.recheck(st, sim)


def _all_plans(sim) -> list:
    return [language.open_language_settings(sim), language.open_app_languages(sim),
            language.app_language_plan(sim, ["com.whatsapp", "com.tencent.mm", "org.telegram.messenger"], "en-US,ar-EG"),
            language.reset_app_language_plan(sim, ["com.tencent.mm"])]


def test_no_plan_contains_a_forbidden_command(sim) -> None:
    for plan in _all_plans(sim):
        for s in plan.steps:
            guard.check(s, sim)  # raises on anything forbidden or not allowlisted, incl. undo
            for c in [s.cmd] + s.undo:
                assert "system_locales" not in c and "persist.sys.locale" not in c and "CHANGE_CONFIGURATION" not in c


def test_module_source_has_no_forbidden_technique() -> None:
    text = SRC.read_text(encoding="utf-8")
    for bad in ("settings put", "setprop", "resetprop", "app_process", "updateConfiguration", "CHANGE_CONFIGURATION",
                "updatePersistentConfiguration", "MoreLocale"):
        assert bad not in text, bad
    tree = ast.parse(text)
    assert not any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("sh", "adb") for n in ast.walk(tree))


def test_system_app_refused_with_explanation(sim) -> None:
    pick = language.pick_app_language(sim, ["com.android.settings", "com.heytap.market", "com.android.launcher",
                                            "com.google.android.inputmethod.latin", "com.whatsapp"])
    assert set(pick.refused) == {"com.android.settings", "com.heytap.market", "com.android.launcher",
                                 "com.google.android.inputmethod.latin"}
    assert "Settings > Language" in pick.refused["com.heytap.market"]
    assert [s.pkg for s in pick.plan.steps] == ["com.whatsapp"]
    assert any(n.startswith("Refused com.android.settings:") for n in pick.plan.notes)


def test_undo_restores_exact_previous(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    plan = language.app_language_plan(sim, ["com.tencent.mm", "com.whatsapp"], "en-US,ar-EG")
    assert executor.run(plan, sim, yes, history=h).status == "done"
    assert phone.packages["com.tencent.mm"].locales == "en-US,ar-EG"
    assert executor.run(h.rollback_to(h.entries()[0].id), sim, yes, history=h).status == "done"
    assert phone.packages["com.tencent.mm"].locales == "zh-CN" and phone.packages["com.whatsapp"].locales == ""


def test_already_set_and_custom_languages(sim, phone: FakePhone) -> None:
    phone.packages["com.whatsapp"].locales = "en-US"
    phone.packages["org.telegram.messenger"].locales = "fr-FR"
    pick = language.pick_app_language(sim, ["com.whatsapp", "org.telegram.messenger"], "en-US")
    assert pick.already == ["com.whatsapp"] and pick.kept == {"org.telegram.messenger": "fr-FR"}
    assert pick.plan.steps == []
    over = language.pick_app_language(sim, ["org.telegram.messenger"], "en-US", override_custom=True)
    assert [s.cmd for s in over.plan.steps] == ["cmd locale set-app-locales org.telegram.messenger --user 0 "
                                                "--locales en-US"]
    assert over.plan.steps[0].undo == ["cmd locale set-app-locales org.telegram.messenger --user 0 --locales fr-FR"]


def test_candidates_are_user_apps_only(sim) -> None:
    c = language.candidates(sim)
    assert "com.whatsapp" in c and "com.tencent.mm" in c
    assert "com.google.android.inputmethod.latin" not in c
    assert not any(p.startswith(("com.android.", "com.oplus.", "com.coloros.")) for p in c)


def test_old_android_refused(sim, phone: FakePhone) -> None:
    phone.props["ro.build.version.sdk"] = "32"
    sim.forget_props()
    pick = language.pick_app_language(sim, ["com.whatsapp"])
    assert pick.refused == {"com.whatsapp": "per-app language needs Android 13+"}
    assert language.candidates(sim) == []


def test_invalid_locale_list(sim) -> None:
    with pytest.raises(ValueError):
        language.app_language_plan(sim, ["com.whatsapp"], "en-US; reboot")


def test_reset_to_previous_values(sim, phone: FakePhone) -> None:
    phone.packages["com.whatsapp"].locales = "en-US"
    plan = language.reset_app_language_plan(sim, ["com.whatsapp", "com.tencent.mm"], {"com.tencent.mm": "zh-CN"})
    assert [s.cmd for s in plan.steps] == ["cmd locale set-app-locales com.whatsapp --user 0"]

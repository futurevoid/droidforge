"""P2.2: keyboard (R-3.4) - Gboard, Chinese IMEs off, secure keyboard removal, Gboard languages."""

from __future__ import annotations

from droidforge.adb.sim import IME_BAIDU, IME_GBOARD, IME_SECURE, IME_SOGOU, FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.features import keyboard
from tests.helpers import yes


def test_gboard_switch_and_undo(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    plan = keyboard.gboard_plan(sim)
    assert [s.cmd for s in plan.steps] == [f"ime enable {IME_GBOARD}", f"ime set {IME_GBOARD}"]
    assert plan.steps[1].undo == [f"ime set {IME_SOGOU}"] and plan.reboot_check
    rep = executor.run(plan, sim, yes, history=h)
    assert rep.status == "done" and rep.offer_reboot
    assert phone.settings["secure"]["default_input_method"] == IME_GBOARD
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, history=h)
    assert phone.settings["secure"]["default_input_method"] == IME_SOGOU and not phone.imes[IME_GBOARD]


def test_gboard_missing_opens_play(sim, phone: FakePhone) -> None:
    phone.packages["com.google.android.inputmethod.latin"].present = False
    plan = keyboard.gboard_plan(sim)
    assert plan.steps[0].cmd.endswith("'market://details?id=com.google.android.inputmethod.latin'")
    assert plan.steps[0].risk == "read" and "not installed" in plan.notes[0]


def test_gboard_already_default(sim, phone: FakePhone) -> None:
    phone.set_default_ime(IME_GBOARD)
    plan = keyboard.gboard_plan(sim)
    assert plan.steps == [] and "already" in plan.notes[0]


def test_chinese_imes_only_after_gboard(sim, phone: FakePhone) -> None:
    plan = keyboard.chinese_imes_plan(sim)
    assert plan.steps == [] and "Gboard the default keyboard first" in plan.notes[0]
    executor.run(keyboard.gboard_plan(sim), sim, yes)
    plan = keyboard.chinese_imes_plan(sim)
    assert sorted(s.cmd for s in plan.steps) == sorted([f"ime disable {IME_SOGOU}", f"ime disable {IME_BAIDU}"])
    assert executor.run(plan, sim, yes).status == "done"
    assert phone.imes[IME_SECURE] and not phone.imes[IME_SOGOU]      # the secure keyboard is its own action
    assert phone.packages["com.sohu.inputmethod.sogouoem"].enabled    # app stays installed


def test_secure_keyboard_removal(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    h = History(phone.serial)
    plan = keyboard.secure_keyboard_plan(sim)
    cmds = [s.cmd for s in plan.steps]
    assert cmds == [f"ime disable {IME_SECURE}", "am force-stop com.oplus.securitykeyboard",
                    "pm uninstall --user 0 com.oplus.securitykeyboard"]
    assert plan.steps[2].fallbacks[0].cmd == "pm disable-user --user 0 com.oplus.securitykeyboard"
    rep = executor.run(plan, sim, yes, history=h)
    assert rep.status == "done", rep.error
    assert not phone.packages["com.oplus.securitykeyboard"].user0
    assert IME_SECURE not in sim.out("ime list -s")
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, history=h)
    assert phone.state() == initial


def test_secure_keyboard_refused_while_current(sim, phone: FakePhone) -> None:
    phone.settings["secure"]["default_input_method"] = IME_SECURE
    plan = keyboard.secure_keyboard_plan(sim)
    assert plan.steps == [] and "current keyboard" in plan.notes[0]


def test_secure_keyboard_fallback_disable(sim, phone: FakePhone) -> None:
    phone.packages["com.oplus.securitykeyboard"].refuse = {"uninstall"}
    rep = executor.run(keyboard.secure_keyboard_plan(sim), sim, yes)
    assert rep.status == "done"
    assert not phone.packages["com.oplus.securitykeyboard"].enabled and phone.packages["com.oplus.securitykeyboard"].user0


def test_gboard_languages_screen(sim, phone: FakePhone) -> None:
    before = phone.state()
    rep = executor.run(keyboard.gboard_languages_plan(sim), sim, yes)
    assert rep.status == "done" and phone.state() == before
    assert phone.started[-1].endswith("preference.SettingsActivity")


def test_chinese_detection() -> None:
    assert keyboard.is_chinese_ime(IME_SOGOU) and keyboard.is_chinese_ime(IME_BAIDU)
    assert not keyboard.is_chinese_ime(IME_GBOARD) and not keyboard.is_chinese_ime(IME_SECURE)

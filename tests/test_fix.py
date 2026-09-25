"""P3.5 / R-12.5: breakage detection, repair plans, `droidforge fix`."""

from __future__ import annotations

import pytest

from droidforge import cli
from droidforge.adb.sim import FakePhone, neo8_cn
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.features import doctor, fix
from droidforge.session import open_session
from tests.helpers import TELEMETRY, WRITE_PREFIXES, disable_plan, yes


def healthy_session_then(phone: FakePhone, dev, disable: int = 2):
    prof, hist = Profile.for_device(phone.serial), History(phone.serial)
    assert doctor.run(dev, prof, hist).healthy          # saves the healthy baseline
    if disable:
        executor.run(disable_plan(TELEMETRY[:disable]), dev, yes, history=hist, profile=prof)
    return prof, hist


def test_from_report(sim, phone: FakePhone) -> None:
    phone.side_effects[rf"disable-user --user 0 {TELEMETRY[1]}$"] = lambda ph: ph.break_ui()
    rep = executor.run(disable_plan(TELEMETRY[:3]), sim, yes)
    b = fix.from_report(rep)
    assert b.source == "plan" and b.switch_on and b.explained
    assert f"Disable {TELEMETRY[0]}" in b.recent
    text = "\n".join(b.lines())
    assert "Settings home screen" in text and "Turn it off: Developer options" in text and "Reset all settings" in text


def test_startup_healthy_is_none(sim, phone: FakePhone) -> None:
    prof, hist = healthy_session_then(phone, sim)
    assert fix.check_startup(sim, prof, hist) is None


def test_break_between_sessions_explained(sim, phone: FakePhone) -> None:
    prof, hist = healthy_session_then(phone, sim)
    phone.packages["com.whatsapp"].enabled = False            # anything; the health probes are what counts
    phone.side_effects[rf"enable --user 0 {TELEMETRY[0]}$"] = lambda ph: ph.unbreak_ui()
    phone.break_ui()
    b = fix.check_startup(sim, prof, hist)
    assert b is not None and b.source == "startup" and b.explained
    assert [s.cmd for s in b.repair.steps] == [f"pm enable --user 0 {p}" for p in reversed(TELEMETRY[:2])]
    assert executor.run(b.repair, sim, yes, history=hist, profile=prof).status == "done"
    assert fix.recheck(sim, prof) == []


def test_unexplained_break_no_writes(sim, phone: FakePhone) -> None:
    prof, hist = healthy_session_then(phone, sim, disable=0)
    phone.settings["system"]["font_scale"] = "1.3"
    b = fix.check_startup(sim, prof, hist)
    assert b is not None and not b.explained and b.repair.steps == []
    assert any("will not write anything" in a for a in b.advice())
    assert any("Reset all settings" in a for a in b.advice())


def test_no_baseline_uses_failing_probes(sim, phone: FakePhone) -> None:
    phone.break_ui()
    b = fix.check_startup(sim, Profile(), None)
    assert b is not None and b.switch_on and b.repair is None


def test_describe_change() -> None:
    from droidforge.engine.snapshot import Change
    assert fix.describe_change(Change("setting:system:font_scale", "1.0", "1.3")) == \
        "Setting system:font_scale: 1.0 -> 1.3"


# ---------------------------------------------------------------- CLI
def _cli_with(phone: FakePhone, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=phone, **kw))


def test_cli_fix_healthy(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    phone = neo8_cn()
    _cli_with(phone, monkeypatch)
    assert cli.main(["-q", "--simulate", "doctor"]) == 0
    assert cli.main(["-q", "--simulate", "fix"]) == 0
    assert "nothing to fix" in capsys.readouterr().out


def test_cli_fix_repairs_with_yes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    phone = neo8_cn()
    _cli_with(phone, monkeypatch)
    s = open_session(phone=phone, simulate=True)
    healthy_session_then(phone, s.device)
    phone.side_effects[rf"enable --user 0 {TELEMETRY[0]}$"] = lambda ph: ph.unbreak_ui()
    phone.break_ui()
    assert cli.main(["-q", "--simulate", "--yes", "fix"]) == 0
    out = capsys.readouterr().out
    assert "What broke:" in out and "pm enable --user 0" in out and "Healthy again." in out and out.isascii()


def test_cli_fix_unexplained_exits_2_without_writes(monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture) -> None:
    phone = neo8_cn()
    _cli_with(phone, monkeypatch)
    assert cli.main(["-q", "--simulate", "doctor"]) == 0
    phone.settings["system"]["font_scale"] = "1.3"
    n = len(phone.log)
    assert cli.main(["-q", "--simulate", "--yes", "fix"]) == 2
    assert "Reset all settings" in capsys.readouterr().out
    writes = [c for c in phone.log[n:] if c.startswith(WRITE_PREFIXES)]
    assert writes == []


def test_cli_confirm_prompt() -> None:
    answers = iter(["I UNDERSTAND", "y"])
    from droidforge.engine import steps
    from droidforge.engine.plan import Plan
    hook = cli.cli_confirm(False, ask=lambda q: next(answers))
    c = hook(Plan("x", [steps.disable("com.x")], typed=["I UNDERSTAND"]))
    assert c.ok and c.typed == ["I UNDERSTAND"]
    assert not cli.cli_confirm(False, ask=lambda q: "n")(Plan("x", [steps.disable("com.x")])).ok

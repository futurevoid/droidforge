"""P1.9: doctor (R-2.8) is read-only, reports probes + regressions, and gives the advice in order."""

from __future__ import annotations

from pathlib import Path

import pytest

from droidforge import cli
from droidforge.adb.sim import FakePhone, neo8_cn
from droidforge.engine import executor, guard
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.features import doctor
from droidforge.session import open_session
from tests.helpers import TELEMETRY, disable_plan, yes


def only_reads(phone: FakePhone, sim, start: int) -> None:
    for c in phone.log[start:]:
        assert not guard.check_read(c, sim).write, c


def test_healthy_doctor_saves_baseline(sim, phone: FakePhone, tmp_path: Path) -> None:
    prof, hist = Profile.for_device(phone.serial), History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:1]), sim, yes, history=hist)
    before, n = phone.state(), len(phone.log)
    rep = doctor.run(sim, prof, hist, backup_dir=tmp_path)
    assert rep.healthy and rep.baseline_saved and Path(rep.baseline_saved).exists()
    assert Profile.for_device(phone.serial).healthy_baseline["settings_home"]["ok"] is True
    rows = dict(rep.rows)
    assert rows["Root"] == "no" and rows["Per-app firewall"].startswith("supported")
    assert rows["droidforge history"].startswith("1 step(s), 1 undoable")
    assert phone.state() == before
    only_reads(phone, sim, n)


def test_break_ui_doctor_prints_failures_and_advice(sim, phone: FakePhone) -> None:
    phone.break_ui()
    n = len(phone.log)
    rep = doctor.run(sim, Profile(), None)
    assert not rep.healthy and rep.baseline_saved is None
    text = "\n".join(rep.lines())
    assert "[FAIL] Settings home screen" in text and "[FAIL] Permission screen" in text
    assert "[FAIL] System accent colour: 0" in text
    assert "permission monitoring" not in text.lower()          # owner decision: doctor skips the switch
    assert rep.advice[0].startswith("2) Undo") and "Reset all settings" in rep.advice[-1]
    assert text.index("2) Undo") < text.index("3) Last resort")
    only_reads(phone, sim, n)


def test_regressions_vs_last_healthy_baseline(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    assert doctor.run(sim, prof, None).healthy
    phone.settings["system"]["font_scale"] = "1.3"   # the user changed it between sessions: information only
    rep = doctor.run(sim, prof, None)
    assert rep.healthy and rep.regressions == [] and [r.probe for r in rep.changes] == ["font_scale"]
    assert "information, not an error" in "\n".join(rep.lines())
    assert prof.healthy_baseline["font_scale"]["value"] == "1.3"   # the new reference: it is not reported again
    assert doctor.run(sim, prof, None).changes == []
    phone.crash("com.android.systemui")                # a real problem still is one
    rep = doctor.run(sim, prof, None)
    assert [r.probe for r in rep.regressions] == ["crashes"] and not rep.healthy
    assert rep.advice[0].startswith("2) Undo")


def test_settings_process_coming_and_going_is_not_a_change(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    phone.packages["com.android.settings"].running = True
    assert doctor.run(sim, prof, None).healthy
    phone.packages["com.android.settings"].running = False
    rep = doctor.run(sim, prof, None)
    assert rep.healthy and rep.regressions == [] and rep.changes == []


def test_doctor_does_not_check_the_switch(sim, phone: FakePhone) -> None:
    phone.permission_monitoring_disabled = True        # switch on, everything else healthy
    rep = doctor.run(sim, Profile(), None)
    assert rep.healthy and "permission monitoring" not in "\n".join(rep.lines()).lower()
    assert "permission_monitoring" not in rep.health.probes


# ---------------------------------------------------------------- CLI
def test_cli_simulate_doctor(capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["-q", "--simulate", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "Everything droidforge checks looks healthy." in out and out.isascii()


def test_cli_doctor_broken_exits_nonzero(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = neo8_cn()
    ph.break_ui()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=ph, **kw))
    assert cli.main(["-q", "--simulate", "doctor"]) == 2
    out = capsys.readouterr().out
    assert "Reset all settings" in out and "Turn it off: Developer options" not in out


def test_cli_without_adb_explains(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr("droidforge.adb.real.find_adb", lambda: None)
    assert cli.main(["doctor"]) == 1
    assert "sudo pacman -S android-tools" in capsys.readouterr().err

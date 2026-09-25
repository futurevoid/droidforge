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
    assert "'Disable permission monitoring' is ON" in text
    assert rep.advice[0].startswith("1) If the 'Disable permission monitoring'")
    assert "Reset all settings" in rep.advice[-1]
    assert text.index("1) If the") < text.index("2) Undo") < text.index("3) Last resort")
    only_reads(phone, sim, n)


def test_regressions_vs_last_healthy_baseline(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    assert doctor.run(sim, prof, None).healthy
    phone.settings["system"]["font_scale"] = "1.3"   # changed between sessions, droidforge did not do it
    rep = doctor.run(sim, prof, None)
    assert [r.probe for r in rep.regressions] == ["font_scale"]
    assert "Changed since the last healthy check:" in "\n".join(rep.lines())
    assert rep.advice[0].startswith("2) Undo")
    assert prof.healthy_baseline["font_scale"]["value"] == "1.0"  # a broken state never becomes the baseline


def test_unknown_permission_switch_is_not_called_healthy(sim, phone: FakePhone) -> None:
    del phone.props["persist.sys.permission.enable"]
    text = "\n".join(doctor.run(sim, None, None).lines())
    assert "[??  ] 'Disable permission monitoring' switch: unknown" in text


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
    assert "Reset all settings" in out and "Turn it off: Developer options" in out


def test_cli_without_adb_explains(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr("droidforge.adb.real.find_adb", lambda: None)
    assert cli.main(["doctor"]) == 1
    assert "sudo pacman -S android-tools" in capsys.readouterr().err

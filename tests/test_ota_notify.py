"""P4.9: OTA detection -> previewed re-apply (R-2.5, P14); notify-send (R-2.7)."""

from __future__ import annotations

from droidforge import notify
from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.profile import Profile
from droidforge.features import ota
from tests.helpers import TELEMETRY, disable_plan, yes


def test_first_connect_is_not_an_ota(sim, phone: FakePhone) -> None:
    assert not ota.check(sim, Profile.for_device(phone.serial)).changed


def test_ota_shows_what_was_undone_and_asks(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(disable_plan(TELEMETRY[:2]), sim, yes, profile=prof)
    phone.packages[TELEMETRY[1]].enabled = True               # the update re-enabled it
    phone.props["ro.build.fingerprint"] = "realme/RMX8899/new:16/NEW/2:user/release-keys"
    sim.forget_props()
    before = phone.state()
    rep = ota.check(sim, prof)
    assert rep.changed and rep.new.endswith("NEW/2:user/release-keys") and phone.state() == before
    assert [s.cmd for s in rep.plan.steps] == [f"pm disable-user --user 0 {TELEMETRY[1]}"]
    assert rep.reverted and TELEMETRY[1] in rep.reverted[0]
    assert executor.run(rep.plan, sim, yes, profile=prof).status == "done"
    assert not ota.check(sim, prof).changed                     # executor stored the new fingerprint


def test_acknowledge_without_reapply(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    prof.note_device(sim)
    phone.props["ro.build.fingerprint"] = "x/y/z:16/A/1:user/release-keys"
    sim.forget_props()
    assert ota.check(sim, prof).changed
    ota.acknowledge(prof, sim)
    assert not ota.check(sim, prof).changed


def test_locked_packages_are_not_reapplied_outside_expert(sim, phone: FakePhone) -> None:
    prof = Profile(fingerprint="old", disabled=["com.android.ims.rcsservice", TELEMETRY[0]])
    rep = ota.check(sim, prof)
    assert [s.pkg for s in rep.plan.steps] == [TELEMETRY[0]]
    assert any("expert mode" in n for n in rep.plan.notes)


def test_notify_is_guarded_and_simulated(sim, phone: FakePhone) -> None:
    assert notify.command("Done's", "a\nb") == "notify-send -a droidforge 'Done s' 'a b'"
    assert notify.notify("droidforge", "Plan finished", sim)
    assert phone.host_log[-1] == "notify-send -a droidforge droidforge Plan finished"

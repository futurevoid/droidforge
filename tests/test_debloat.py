"""P2.3: UAD-NG data + debloat plans (port of the legacy mock scenarios)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from droidforge.adb.sim import IME_BAIDU, FakePhone
from droidforge.data import uad
from droidforge.engine import executor, safety
from droidforge.engine.history import History
from droidforge.engine.plan import Confirmation, Plan
from droidforge.engine.profile import Profile
from droidforge.features import debloat
from tests.helpers import UAD_SAMPLE, yes


def confirm_all(plan: Plan) -> Confirmation:
    return Confirmation(True, list(plan.typed))


# ---------------------------------------------------------------- listing
def test_listing_tiers_and_order(sim) -> None:
    rows = debloat.listing(sim, UAD_SAMPLE, tiers=("Recommended", "Advanced"))
    tiers = [r.tier for r in rows]
    assert tiers == sorted(tiers, key=lambda t: debloat.TIER_RANK[t])
    pkgs = [r.pkg for r in rows]
    assert "com.heytap.market" in pkgs and "com.coloros.assistantscreen" in pkgs
    assert "com.coloros.gallery3d" not in pkgs and "com.coloros.pictorial" not in pkgs
    assert all(r.status == "enabled" for r in rows)
    assert debloat.listing(sim, UAD_SAMPLE, tiers=("Recommended",), keyword="heytap")[0].pkg.startswith("com.heytap")


def test_scan_default_all_keyword(sim) -> None:
    default = [r.pkg for r in debloat.scan(sim, UAD_SAMPLE)]
    assert "com.heytap.market" in default and "com.whatsapp" not in default
    assert not any("overlay" in p for p in default)          # R-4.3b hidden by default
    assert "com.whatsapp" in [r.pkg for r in debloat.scan(sim, UAD_SAMPLE, "all")]
    assert [r.pkg for r in debloat.scan(sim, UAD_SAMPLE, "whatsapp")] == ["com.whatsapp"]
    locked = {r.pkg: r.verdict.level for r in debloat.scan(sim, UAD_SAMPLE, "pictorial")}
    assert locked == {"com.coloros.pictorial": "locked", "com.heytap.pictorial": "ok"}


def test_info(sim) -> None:
    text = "\n".join(debloat.info(sim, ["com.heytap.market", "com.whatsapp"], UAD_SAMPLE))
    assert "Rating : Recommended" in text and "Needed by  : com.nearme.gamecenter" in text
    assert "Not in the UAD-NG list." in text


# ---------------------------------------------------------------- preflight
def test_preflight_notes_and_typed(sim) -> None:
    plan = debloat.disable_plan(sim, ["com.android.systemui", "com.heytap.market", "com.coloros.gallery3d",
                                      "com.oplus.camera", "com.coloros.gamespace", "com.not.here"], UAD_SAMPLE)
    notes = "\n".join(plan.notes)
    assert "Locked, skipped: com.android.systemui" in notes and "--expert" in notes
    assert "com.heytap.market is needed by com.nearme.gamecenter" in notes
    assert "keep-list" in notes and "Not on this phone: com.not.here" in notes
    assert plan.typed == [safety.TYPED_GUARDED, safety.TYPED_EXPERT_TIER]
    assert [s.pkg for s in plan.steps] == ["com.heytap.market", "com.coloros.gallery3d", "com.oplus.camera",
                                           "com.coloros.gamespace"]
    assert plan.reboot_check and not plan.expert
    assert executor.run(plan, sim, yes).status == "refused"           # typed strings missing
    assert executor.run(plan, sim, confirm_all).status == "done"


def test_already_disabled(sim, phone: FakePhone) -> None:
    phone.packages["com.opos.cs"].enabled = False
    plan = debloat.disable_plan(sim, ["com.opos.cs"], UAD_SAMPLE)
    assert plan.steps == [] and "Already disabled: com.opos.cs" in plan.notes


def test_expert_mode_admits_locked(sim, phone: FakePhone) -> None:
    p = "com.android.ims.rcsservice"
    plan = debloat.disable_plan(sim, [p], UAD_SAMPLE, expert_mode=True)
    assert plan.expert and p in plan.typed and plan.steps[0].risk == "locked"
    assert executor.run(plan, sim, confirm_all, expert_mode=False).status == "refused"
    assert executor.run(plan, sim, confirm_all, expert_mode=True).status == "done"
    assert not phone.packages[p].enabled


# ---------------------------------------------------------------- legacy mock scenarios
def test_protected_package_escalates_to_suspend(sim, phone: FakePhone) -> None:
    p = "com.oplus.sauhelper"                 # ROM refuses disable-user
    rep = executor.run(debloat.force_plan(sim, [p], UAD_SAMPLE), sim, yes)
    assert rep.status == "done"
    r = rep.results[0]
    assert r.ok and r.step.cmd == f"pm suspend --user 0 {p}" and phone.packages[p].suspended


def test_suspend_refused_escalates_to_remove(sim, phone: FakePhone) -> None:
    p = "com.coloros.prome.service"           # ROM refuses disable-user and suspend
    plan = debloat.force_plan(sim, [p], UAD_SAMPLE)
    assert [f.cmd for f in plan.steps[0].fallbacks] == [f"pm suspend --user 0 {p}", f"pm uninstall -k --user 0 {p}",
                                                        f"cmd connectivity set-package-networking-enabled false {p}"]
    assert any("disable -> suspend" in n for n in plan.notes)
    h = History(phone.serial)
    rep = executor.run(plan, sim, yes, history=h)
    assert rep.status == "done" and rep.results[0].attempts[-1] == f"pm uninstall -k --user 0 {p}"
    assert not phone.packages[p].user0
    executor.run(h.undo([h.entries()[0].id]), sim, yes, history=h)
    assert phone.packages[p].user0                 # undo reverses the stage that took effect


def test_everything_refused_suggests_neuter(sim, phone: FakePhone) -> None:
    p = "com.opos.cs"
    phone.packages[p].refuse = {"disable", "suspend", "uninstall"}
    phone.firewall_supported = False           # no chain-3 firewall on this build: no fourth stage
    rep = executor.run(debloat.force_plan(sim, [p], UAD_SAMPLE), sim, yes)
    assert not rep.results[0].ok and rep.results[0].applied == []
    assert debloat.protected_by_rom(rep.results) == [f"{p} is protected by the ROM itself. Neuter can still silence it."]


def test_neuter_and_unneuter(sim, phone: FakePhone) -> None:
    p = "com.heytap.market"
    prof = Profile.for_device(phone.serial)
    plan = debloat.neuter_plan(sim, [p], UAD_SAMPLE)
    cmds = [s.cmd for s in plan.steps]
    assert f"pm revoke {p} android.permission.POST_NOTIFICATIONS" in cmds and f"am force-stop {p}" in cmds
    assert sum(c.startswith(f"cmd appops set {p}") for c in cmds) == 4
    assert executor.run(plan, sim, yes, profile=prof).status == "done"
    assert prof.neutered == {p: ["android.permission.POST_NOTIFICATIONS"]}
    assert phone.packages[p].appops["RUN_ANY_IN_BACKGROUND"] == "ignore"
    back = debloat.enable_plan(sim, [p], prof, UAD_SAMPLE)
    assert executor.run(back, sim, yes, profile=prof).status == "done"
    assert phone.packages[p].perms["android.permission.POST_NOTIFICATIONS"] and phone.packages[p].appops == {}
    assert prof.neutered == {}


def test_ime_package_declares_its_keyboards(sim, phone: FakePhone) -> None:
    plan = debloat.disable_plan(sim, ["com.baidu.input_oppo"], UAD_SAMPLE)
    assert f"ime:enabled:{IME_BAIDU}" in plan.steps[0].touches
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done" and rep.undeclared == []


def test_remove_then_restore(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    assert executor.run(debloat.remove_plan(sim, ["com.heytap.mcs"], UAD_SAMPLE), sim, yes).status == "done"
    assert "com.heytap.mcs" not in sim.packages()
    assert debloat.remove_plan(sim, ["com.heytap.mcs"], UAD_SAMPLE).steps == []   # already removed
    assert executor.run(debloat.restore_plan(sim, ["com.heytap.mcs"], UAD_SAMPLE), sim, yes).status == "done"
    assert phone.state() == initial


def test_user_app_debloat_does_not_offer_reboot(sim) -> None:
    assert not debloat.disable_plan(sim, ["com.whatsapp"], UAD_SAMPLE).reboot_check


def test_bulk_select(sim) -> None:
    rows = debloat.scan(sim, UAD_SAMPLE, "game")
    ctx = safety.SafetyContext.from_device(sim, UAD_SAMPLE)
    assert "com.coloros.gamespace" not in debloat.bulk(rows, ctx)
    assert "com.nearme.gamecenter" in debloat.bulk(rows, ctx)


# ---------------------------------------------------------------- UAD data
def test_uad_cache_and_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "uad.json"
    assert uad.load_cached(f) == {} and uad.status_line(f) == "UAD-NG: not downloaded"
    big = {f"com.p{i}": {"removal": "Recommended", "list": "Oem"} for i in range(1200)}

    def fake_urlopen(req, timeout):
        return io.BytesIO(json.dumps(big).encode())
    monkeypatch.setattr(uad.urllib.request, "urlopen", fake_urlopen)
    ok, msg = uad.update(path=f)
    assert ok and "1200" in msg and uad.load_cached(f)["com.p1"]["removal"] == "Recommended"
    assert uad.status_line(f).startswith("UAD-NG: 1200 pkgs")

    monkeypatch.setattr(uad.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(b'{"com.x": {}}'))
    ok, msg = uad.update(path=f)
    assert not ok and "keeping the cached copy" in msg and len(uad.load_cached(f)) == 1200


def test_uad_formats(tmp_path: Path) -> None:
    assert uad.normalise([{"id": "com.a", "removal": "Expert"}]) == {"com.a": {"id": "com.a", "removal": "Expert"}}
    f = tmp_path / "bad.json"
    f.write_text("{corrupt")
    assert uad.load_cached(f) == {}
    assert uad.tier(UAD_SAMPLE, "com.heytap.market") == "Recommended"
    assert uad.needed_by(UAD_SAMPLE, "com.heytap.market") == ["com.nearme.gamecenter"]
    assert uad.description(UAD_SAMPLE, "com.heytap.market", 8) == "HeyTa..."


def test_safety_reads_the_cached_uad(sim, df_home: Path) -> None:
    f = uad.cache_file()
    f.write_text(json.dumps({"com.oplus.weird": {"removal": "Unsafe"}, "com.heytap.market": {"removal": "Expert"}}))
    ctx = safety.SafetyContext.from_device(sim)
    assert safety.verdict("com.oplus.weird", ctx).locked
    assert safety.verdict("com.heytap.market", ctx).level == "expert"

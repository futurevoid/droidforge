"""P0.2: config.py (XDG paths, config.json) and log.py (verbosity, sinks, debug log)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import List

import pytest

from droidforge import config
from droidforge.log import LogLine, Logger, ascii_safe, console_sink


# ---------------------------------------------------------------- config
def test_paths_follow_droidforge_home(df_home: Path) -> None:
    p = config.paths()
    assert p.config_file == df_home / "config" / "config.json"
    assert p.sub("history") == df_home / "data" / "history"
    assert p.sub("history").is_dir()
    with pytest.raises(ValueError):
        p.sub("elsewhere")


def test_paths_default_to_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DROIDFORGE_HOME")
    p = config.paths()
    assert p.config_dir.name == "droidforge" and p.data_dir.name == "droidforge"


def test_config_defaults_and_roundtrip(df_home: Path) -> None:
    c = config.Config()
    assert c.get("verbosity") == 3 and c.get("theme")
    c.set("theme", "hacker")
    c.set("last_device", "ABC123")
    c2 = config.Config()
    assert c2.get("theme") == "hacker" and c2.get("last_device") == "ABC123"


def test_config_keeps_unknown_keys_and_clamps_verbosity(df_home: Path) -> None:
    p = config.paths()
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text(json.dumps({"verbosity": 9, "future_key": 1}))
    c = config.Config()
    assert c.get("verbosity") == 3 and c.get("future_key") == 1


def test_config_corrupt_file_falls_back(df_home: Path) -> None:
    p = config.paths()
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text("{not json")
    assert config.Config().get("verbosity") == 3


# ---------------------------------------------------------------- log
def collect(lg: Logger) -> List[LogLine]:
    lines: List[LogLine] = []
    lg.add_sink(lines.append)
    return lines


def run_example(lg: Logger) -> None:
    lg.command("adb shell pm list packages")
    lg.result(0, 12, "\n".join(f"package:p{i}" for i in range(20)), "warn line")
    lg.command("adb shell getprop ro.build.version.sdk", plumbing=True)
    lg.result(0, 3, "36", "", plumbing=True)
    lg.trace("decided something")
    lg.trace("cache hit", 3)
    lg.ok("Disabled com.x")


def test_level_1_results_only(tmp_path: Path) -> None:
    lg = Logger(1, tmp_path / "d.log")
    lines = collect(lg)
    run_example(lg)
    assert [ln.kind for ln in lines] == ["ok"]


def test_level_2_commands_truncated_no_plumbing(tmp_path: Path) -> None:
    lg = Logger(2, tmp_path / "d.log")
    lines = collect(lg)
    run_example(lg)
    kinds = [ln.kind for ln in lines]
    assert kinds.count("cmd") == 1                    # plumbing command hidden
    assert kinds.count("out") == 15 and kinds.count("more") == 1
    assert "err" in kinds and "trace" in kinds
    assert not any("cache hit" in ln.text for ln in lines)
    assert lines[0].text.strip().startswith("$ adb shell pm list")
    exit_line = next(ln for ln in lines if ln.kind == "exit").text
    assert "-> exit 0 | 12 ms | 20 line(s) out, 1 err" in exit_line


def test_level_3_everything_with_timestamps(tmp_path: Path) -> None:
    lg = Logger(3, tmp_path / "d.log")
    lines = collect(lg)
    run_example(lg)
    kinds = [ln.kind for ln in lines]
    assert kinds.count("cmd") == 2 and kinds.count("out") == 21 and "more" not in kinds
    assert any("cache hit" in ln.text for ln in lines)
    import re
    assert re.search(r"\d\d:\d\d:\d\d \$ adb", lines[0].text)


@pytest.mark.parametrize("level", [1, 2, 3])
def test_debug_log_always_full(tmp_path: Path, level: int) -> None:
    dbg = tmp_path / "d.log"
    lg = Logger(level, dbg)
    run_example(lg)
    text = dbg.read_text()
    assert text.count("out | package:p") == 20
    assert "err | warn line" in text
    assert "RUN   adb shell getprop" in text and "TRACE cache hit" in text
    assert "EXIT  0  (12 ms, 20 stdout / 1 stderr lines)" in text


def test_cycle_and_clamp() -> None:
    lg = Logger(3)
    assert lg.cycle() == 1 and lg.cycle() == 2 and lg.cycle() == 3
    lg.verbosity = 0
    assert lg.verbosity == 1


def test_broken_sink_does_not_raise(tmp_path: Path) -> None:
    lg = Logger(3, tmp_path / "d.log")

    def bad(_: LogLine) -> None:
        raise RuntimeError("boom")
    lg.add_sink(bad)
    lg.ok("still fine")
    assert "SINK ERROR" in (tmp_path / "d.log").read_text()


def test_console_sink_is_ascii() -> None:
    buf = io.StringIO()
    lg = Logger(3)
    lg.add_sink(console_sink(buf, color=False))
    lg.info("device language: 中文")
    out = buf.getvalue()
    assert out.isascii() and "[*] device language:" in out
    assert ascii_safe("é") == "\\xe9"

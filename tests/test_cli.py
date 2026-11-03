from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prop_rules_checker.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = str(ROOT / "examples/sample-trades.csv")
FIX = ROOT / "tests/fixtures"


def test_violations_exit_1_and_text_output(capsys):
    assert main([EXAMPLE, "--rules", "example-1step-trailing"]) == 1
    out = capsys.readouterr().out
    assert "Weekend holding" in out and "FAIL" in out and "Assumptions" in out
    assert "not advice" in out


def test_clean_run_exit_0(tmp_path, capsys):
    p = tmp_path / "t.csv"
    p.write_text(
        "close_time,pnl\n2026-03-02 10:00,100\n2026-03-03 10:00,90\n"
        "2026-03-04 10:00,80\n2026-03-05 10:00,95\n"
    )
    assert main([str(p), "-r", "example-funded-account"]) == 0
    assert "0 violation(s)" in capsys.readouterr().out


def test_json_output_and_news(capsys):
    code = main(
        [
            str(FIX / "synthetic_mt4_statement.htm"),
            "-r",
            "example-2step-challenge",
            "--news",
            str(FIX / "synthetic_news_events.csv"),
            "--json",
            "--warn-at",
            "80",
            "--source-tz",
            "UTC",
        ]
    )
    assert code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["source_format"] == "mt4" and data["warn_at"] == 0.8
    news = next(r for r in data["results"] if r["rule"] == "news_trading")
    assert news["status"] == "fail" and news["findings"][0]["trade_ids"] == ["1000007"]


def test_input_errors_exit_2(tmp_path, capsys):
    assert main([EXAMPLE]) == 2
    assert main([str(tmp_path / "nope.csv"), "-r", "example-1step-trailing"]) == 2
    assert "input error" in capsys.readouterr().err
    assert main([EXAMPLE, "-r", "no-such-preset"]) == 2
    with pytest.raises(SystemExit) as exc:
        main([EXAMPLE, "-r", "example-1step-trailing", "--warn-at", "abc"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        main([EXAMPLE, "-r", "example-1step-trailing", "--warn-at", "0"])


def test_list_commands(capsys):
    assert main(["--list-presets"]) == 0
    assert "example-2step-challenge" in capsys.readouterr().out
    assert main(["--list-formats"]) == 0
    assert "tradingview-paper" in capsys.readouterr().out


def test_many_findings_are_truncated(tmp_path, capsys):
    rows = "\n".join(
        f"t{i},EURUSD,buy,9,2026-03-02T10:{i:02d}:00Z,2026-03-02T10:{i:02d}:30Z,1"
        for i in range(15)
    )
    p = tmp_path / "t.csv"
    p.write_text("id,symbol,side,volume,open_time,close_time,pnl\n" + rows + "\n")
    assert main([str(p), "-r", "example-1step-trailing"]) == 1
    assert "more (use --json for all)" in capsys.readouterr().out


def test_python_dash_m():
    proc = subprocess.run(
        [sys.executable, "-m", "prop_rules_checker", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0.1.0" in proc.stdout

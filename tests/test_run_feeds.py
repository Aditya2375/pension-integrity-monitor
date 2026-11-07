"""Regression: the headless feed runner must complete against the fixture set
and surface breaker/watch state (it previously crashed unpacking the pipeline
result, and loaded whole files into memory)."""
import os, sys, tempfile, pathlib, importlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

FIX = pathlib.Path(__file__).parent / "fixtures"


def test_run_feeds_headless(tmp_path, monkeypatch, capsys):
    os.environ["PIM_DB"] = str(tmp_path / "headless.sqlite3")
    os.environ["PIM_CHECKPOINT_DIR"] = str(tmp_path / "checkpoints")
    from pim import db
    importlib.reload(db)
    import scripts.run_feeds as runner
    importlib.reload(runner)
    out = tmp_path / "flags.csv"
    monkeypatch.setattr(sys, "argv", ["run_feeds.py", "--dir", str(FIX), "--out", str(out)])
    runner.main()
    captured = capsys.readouterr().out
    assert "pipeline:" in captured
    assert out.exists()
    lines = out.read_text().strip().splitlines()
    assert lines[0].startswith("rank,case_id,pensioner_id")
    assert len(lines) > 1  # fixtures contain flag-worthy cases

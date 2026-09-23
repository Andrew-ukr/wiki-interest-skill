"""CLI smoke tests: every sub-command is wired to an existing handler; analyze/report/runs work end to end."""
import pytest

import wikiinterest.cli as cli
from conftest import FakeClient
from test_pipeline_report import router


def test_every_subcommand_has_a_handler():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    for name, subparser in sub.choices.items():
        fn = subparser.get_default("fn")
        assert callable(fn), name


@pytest.fixture
def fake_client(tmp_out, monkeypatch):
    client = FakeClient(tmp_out, router)
    monkeypatch.setattr(cli, "Client", lambda: client)
    monkeypatch.setattr(cli, "resolve_period", lambda *a, **k: ("2024-09", "2026-08"))
    return client


def run_cli(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_analyze_report_runs_via_cli(fake_client, capsys):
    code, out, err = run_cli(["analyze", "--qid", "Q1666254", "--langs", "pl,cs,uk"], capsys)
    assert code == 0, err
    assert "ANSWER CHECKLIST" in out and "pl=NO ARTICLE" in out
    run_id = out.split("## Run ")[1].split()[0]
    code, out, err = run_cli(["report", "--run", run_id, "--conclusion", "Чеська аудиторія росте."], capsys)
    assert code == 0, err
    assert "(1 page)" in out and "conclusion check: OK" in out
    code, out, _ = run_cli(["runs", "list"], capsys)
    assert run_id in out


def test_bad_input_gives_error_not_traceback(fake_client, capsys):
    code, _, err = run_cli(["analyze", "--qid", "Q1", "--langs", " ", "--weights", "price=1"], capsys)
    assert code == 2 and err.startswith("ERROR:")

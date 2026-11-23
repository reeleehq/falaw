"""``python -m falaw`` dispatch for every command except ``refresh-llm-rates`` (tested in test_main_cli)."""

import pytest

import falaw.__main__ as cli


@pytest.mark.parametrize("argv", [[], ["-h"], ["--help"]])
def test_help_prints_the_module_doc_and_exits_zero(argv, capsys):
    assert cli.main(argv) == 0
    assert "refresh-llms" in capsys.readouterr().out


def test_unknown_command_exits_two_on_stderr(capsys):
    assert cli.main(["nope"]) == 2
    assert "Unknown command: nope" in capsys.readouterr().err


def test_refresh_llms_and_state_print_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "refresh_llms", lambda: {"llms": "ok"})
    monkeypatch.setattr(cli, "refresh_state", lambda: {"etag": "x"})
    assert cli.main(["refresh-llms"]) == 0
    assert '"llms": "ok"' in capsys.readouterr().out
    assert cli.main(["state"]) == 0
    assert '"etag": "x"' in capsys.readouterr().out


@pytest.mark.parametrize("argv, force", [(["refresh-full"], False), (["refresh-full", "--force"], True)])
def test_refresh_full_passes_force(monkeypatch, capsys, argv, force):
    seen = []
    monkeypatch.setattr(cli, "refresh_full_docs", lambda **kw: seen.append(kw) or {})
    assert cli.main(argv) == 0
    assert seen == [{"force": force}]


def test_regen_skill_writes_both_skill_dirs(monkeypatch, capsys):
    dirs = []
    monkeypatch.setattr(cli, "write_skill_files", lambda d: dirs.append(d) or [d])
    assert cli.main(["regen-skill"]) == 0
    assert len(dirs) == 2
    assert str(dirs[0]).replace("\\", "/").endswith("data/skills/falaw")
    assert str(dirs[1]).replace("\\", "/").endswith(".claude/skills/falaw")
    assert capsys.readouterr().out.count("wrote") == 2


def test_export_schema_prints_each_path(monkeypatch, capsys):
    import falaw.schema_export as se

    seen = []
    monkeypatch.setattr(se, "export_schema", lambda d: seen.append(d) or ["a.json", "b.json"])
    assert cli.main(["export-schema", "out"]) == 0
    assert cli.main(["export-schema"]) == 0
    assert seen == ["out", None]
    assert "a.json" in capsys.readouterr().out

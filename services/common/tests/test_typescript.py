"""The generated TypeScript copy of the enums matches the Python source."""

from pathlib import Path

from rmn_common import status, typescript


def test_every_enum_member_is_rendered():
    source = typescript.render()
    for enum, name in typescript.ENUMS.items():
        assert f"export enum {name} {{" in source
        for member in enum:
            assert f"  {member.name} = '{member.value}'," in source


def test_committed_webapp_file_is_up_to_date():
    # `python -m rmn_common.typescript` rewrites it
    path = typescript.DEFAULT_PATH
    assert path.exists(), f"{path} missing: run python -m rmn_common.typescript"
    assert path.read_text() == typescript.render()


def test_check_mode_reports_a_stale_file(tmp_path: Path, capsys):
    target = tmp_path / "contracts.ts"
    assert typescript.main([str(target)]) == 0
    assert typescript.main(["--check", str(target)]) == 0
    target.write_text("export enum JobStatus {}\n")
    assert typescript.main(["--check", str(target)]) == 1
    assert "stale" in capsys.readouterr().out


def test_every_status_enum_is_exported():
    enums = {
        obj
        for obj in vars(status).values()
        if isinstance(obj, type)
        and issubclass(obj, status.Enum)
        and obj is not status.Enum
    }
    assert enums == set(typescript.ENUMS)

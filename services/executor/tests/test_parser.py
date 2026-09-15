"""Path resolution helpers of the command-line parser."""

import os

import pytest

from process_copy.parser import check_path, try_alternative_root_path, try_alternative_root_paths


def test_check_path_handles_files_and_globs(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    assert check_path(str(tmp_path / "a.pdf")) is True
    assert check_path(str(tmp_path / "nope.pdf")) is False
    assert check_path(str(tmp_path / "*.pdf")) == [str(tmp_path / "a.pdf")]


def test_empty_path_gives_nothing():
    assert try_alternative_root_paths("") == []
    assert try_alternative_root_paths(None) == []
    assert try_alternative_root_path("") is None


def test_absolute_paths_are_globbed_or_trusted(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    missing = str(tmp_path / "missing.pdf")
    assert try_alternative_root_paths(str(tmp_path / "a.pdf")) == [str(tmp_path / "a.pdf")]
    assert try_alternative_root_paths(missing) == []
    assert try_alternative_root_paths(missing, check=False) == [missing]


def test_relative_paths_prefer_the_root_then_the_cwd(tmp_path, monkeypatch):
    root = tmp_path / "root"
    cwd = tmp_path / "cwd"
    for folder in (root, cwd):
        folder.mkdir()
        (folder / "a.pdf").write_text("x")
    (cwd / "only-here.pdf").write_text("x")
    monkeypatch.chdir(cwd)

    assert try_alternative_root_paths("a.pdf", root=str(root)) == [str(root / "a.pdf")]
    assert try_alternative_root_paths("a.pdf") == [str(cwd / "a.pdf")]
    # not under the root: falls back to the working directory
    assert try_alternative_root_paths("only-here.pdf", root=str(root)) == [str(cwd / "only-here.pdf")]
    # unchecked paths are joined without looking at the disk
    assert try_alternative_root_paths("new.pdf", root=str(root), check=False) == [str(root / "new.pdf")]
    assert try_alternative_root_paths("new.pdf", check=False) == [os.path.abspath("new.pdf")]


def test_missing_relative_path_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        try_alternative_root_paths("missing.pdf")


def test_single_path_rejects_ambiguous_globs(tmp_path):
    (tmp_path / "a1.pdf").write_text("x")
    (tmp_path / "a2.pdf").write_text("x")
    assert try_alternative_root_path(str(tmp_path / "a1.pdf")) == str(tmp_path / "a1.pdf")
    with pytest.raises(ValueError, match="several possible paths"):
        try_alternative_root_path(str(tmp_path / "a*.pdf"))


def test_latex_input_does_not_accumulate_across_runs():
    # one process handles many jobs: the course and session lines of every
    # previous run used to stay in Latex.input_content
    import argparse

    from process_copy import config, parser

    run = argparse.Namespace(course="MTH1106", session="A25", name=None, suffix=None)
    parser.set_latex_input(run)
    first = config.Latex.input_content
    assert first.count("\\cours") == 1 and first.count("\\session") == 1
    assert run.suffix == "MTH1106_A25_"
    parser.set_latex_input(argparse.Namespace(course="MTH1106", session="A25", name=None, suffix=None))
    assert config.Latex.input_content == first
    parser.set_latex_input(argparse.Namespace(course=None, session=None, name=None, suffix=None))
    assert config.Latex.input_content == config.Latex.base_input_content

"""Statistics report: boxplots and the LaTeX tables fed to pdflatex."""

import os
import shutil
from pathlib import Path

import pytest

import numpy as np

from utils import stats


def test_default_question_names():
    assert stats.default_question_names(3) == ["Q1", "Q2", "Q3"]
    assert stats.default_question_names(0) == []


def test_makedir_path_creates_and_resolves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = stats.makedir_path("out/deep")
    assert path == (tmp_path / "out" / "deep").resolve()
    assert path.is_dir()
    assert stats.makedir_path("out/deep") == path  # idempotent


def test_remove_non_pdfs_keeps_pdfs_and_folders(tmp_path):
    for name in ("a.pdf", "b.txt", "c.png"):
        (tmp_path / name).write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.txt").write_text("x")

    stats.remove_non_pdfs(str(tmp_path))

    assert sorted(os.listdir(tmp_path)) == ["a.pdf", "sub"]
    assert (tmp_path / "sub" / "d.txt").exists()


def test_one_boxplot_per_question_plus_the_total(tmp_path):
    notes = np.array([[1, 2, 3], [4, 5, 6]])
    files = stats.create_all_boxplots(notes, tmp_dir=str(tmp_path / "plots"))
    assert [f.name for f in files] == ["Q1.png", "Q2.png", "Total.png"]
    assert all(f.stat().st_size > 0 for f in files)


def test_boxplots_use_the_given_question_names(tmp_path):
    notes = np.array([[1, 2], [3, 4]])
    files = stats.create_all_boxplots(notes, tmp_dir=str(tmp_path), question_names=["Q1", "Q3"])
    assert [f.name for f in files] == ["Q1.png", "Q3.png", "Total.png"]


def test_stats_latex_writes_the_tables(tmp_path, monkeypatch):
    # pdflatex is not part of the test environment: capture what would be compiled
    compiled = {}

    def fake_tex_pdf(latex_file, tmp_dir, latex_cmd="pdflatex"):
        compiled["latex_file"] = latex_file
        compiled["tmp_dir"] = tmp_dir
        return "main.pdf"

    monkeypatch.setattr(stats, "create_tex_pdf", fake_tex_pdf)
    notes = np.array([[10.0, 8.0], [3.0, 5.0]])

    out = stats.create_stats_latex(
        "Émilie",
        0,
        2,
        notes,
        [10, 5, 15],
        ["Q1.png", "Q3.png", "Total.png"],
        latex_dir=str(tmp_path / "tex"),
        TMP_DIR=str(tmp_path / "tmp"),
        question_names=["Q1", "Q3"],
    )

    tmp_dir = (tmp_path / "tmp").resolve()
    assert out == tmp_dir / "main.pdf"
    assert compiled["latex_file"] == (tmp_path / "tex").resolve() / "main.tex"
    assert compiled["tmp_dir"] == tmp_dir

    data = (tmp_dir / "data.tex").read_text()
    assert "\\renewcommand{\\nom}{Emilie}" in data  # accents stripped for LaTeX
    assert "\\renewcommand{\\widthratio}{0.50}" in data

    lines = (tmp_dir / "stats.tex").read_text().splitlines()
    graphic = "\\includegraphics[width=\\widthratio \\textwidth]"
    assert lines[0] == f"1 (/ 10) & 10.0 & 9.00 & {graphic}{{Q1.png}} \\\\ \\hline"
    assert lines[1] == f"3 (/ 5) & 3.0 & 4.00 & {graphic}{{Q3.png}} \\\\ \\hline"
    assert lines[2] == f"Total (/ 15) & 13.0 & 13.00 & {graphic}{{Total.png}}"


def test_stats_latex_for_the_class_average_leaves_the_student_column_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "create_tex_pdf", lambda *a, **k: "main.pdf")
    notes = np.array([[10.0, 8.0]])
    stats.create_stats_latex(
        "Moyennes", None, 1, notes, [10, 10], ["Q1.png", "Total.png"],
        latex_dir=str(tmp_path / "tex"), TMP_DIR=str(tmp_path / "tmp"),
    )
    lines = (tmp_path / "tmp" / "stats.tex").read_text().splitlines()
    assert lines[0].startswith("1 (/ 10) &  & 9.00 &")
    assert lines[1].startswith("Total (/ 10) &  & 9.00 &")


def test_tex_escape_neutralises_every_special_character():
    hostile = "}\\input{/etc/passwd}\\newcommand{\\x}{"
    escaped = stats.tex_escape(hostile)
    assert "\\input" not in escaped
    assert escaped.startswith("\\}\\textbackslash{}input\\{")
    assert stats.tex_escape("Smith & Wesson 100% #1 $_ ~^") == (
        "Smith \\& Wesson 100\\% \\#1 \\$\\_ \\textasciitilde{}\\textasciicircum{}"
    )
    assert stats.tex_escape("Plain Name") == "Plain Name"


def test_the_student_name_is_escaped_before_it_reaches_latex(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "create_tex_pdf", lambda *a, **k: "main.pdf")
    stats.create_stats_latex(
        "}\\input{secret.csv}\\newcommand{\\x}{", None, 1, np.array([[1.0]]), [1, 1], ["Q1.png", "T.png"],
        latex_dir=str(tmp_path / "tex"), TMP_DIR=str(tmp_path / "tmp"),
    )
    data = (tmp_path / "tmp" / "data.tex").read_text()
    assert "\\input{secret.csv}" not in data
    assert "\\renewcommand{\\nom}{\\}\\textbackslash{}input\\{secret.csv\\}" in data


def test_create_tex_pdf_runs_in_the_tmp_dir_without_shell_escape(tmp_path):
    # a stand-in for pdflatex that records how it was called and fails
    fake = tmp_path / "fakelatex"
    fake.write_text("#!/bin/sh\necho \"cwd=$(pwd)\"\necho \"args=$*\"\nexit 3\n")
    fake.chmod(0o755)
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    before = os.getcwd()

    with pytest.raises(ChildProcessError, match="exit code 3"):
        stats.create_tex_pdf(tmp_path / "main.tex", tmp_dir, latex_cmd=str(fake))

    assert os.getcwd() == before  # no chdir left behind
    log = (tmp_dir / "stdout.log").read_text()
    assert f"cwd={tmp_dir.resolve()}" in log
    assert "-no-shell-escape" in log and "-interaction=nonstopmode" in log and "-halt-on-error" in log


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_a_hostile_name_compiles_to_a_pdf_that_reads_nothing(tmp_path):
    tex_dir = Path(__file__).resolve().parent.parent / "tex"
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    secret = tmp_dir / "secret.txt"
    secret.write_text("THE-SECRET-ROSTER")
    boxplot = stats.create_boxplot(np.array([1.0, 2.0, 3.0]), "Q1", str(tmp_dir))
    total = stats.create_boxplot(np.array([1.0, 2.0, 3.0]), "Total", str(tmp_dir))

    stats.create_stats_latex(
        "}\\input{secret.txt}\\newcommand{\\x}{", 0, 1, np.array([[1.0, 2.0, 3.0]]), [3, 3],
        [str(boxplot), str(total)], latex_dir=str(tex_dir), TMP_DIR=str(tmp_dir),
    )
    log = (tmp_dir / "stdout.log").read_text()
    assert (tmp_dir / "main.pdf").exists()
    assert "secret.txt" not in log.replace("secret.txt}", "")  # never opened as a file
    assert "(./secret.txt" not in log


def test_boxplots_outside_the_tmp_dir_are_copied_in(tmp_path, monkeypatch):
    # job a119c7b2: boxplots in TMP_DIR, stats compiled in TMP_DIR/tex, and
    # pdflatex (openin_any=p) refused ../Q1.png
    monkeypatch.setattr(stats, "create_tex_pdf", lambda *a, **k: "main.pdf")
    plots = stats.create_all_boxplots(np.array([[1.0, 2.0, 3.0]]), tmp_dir=str(tmp_path))
    tmp_dir = tmp_path / "tex"
    stats.create_stats_latex(
        "Statistiques", None, 1, np.array([[1.0, 2.0, 3.0]]), [3, 3], [str(p) for p in plots],
        latex_dir=str(tmp_path), TMP_DIR=str(tmp_dir),
    )
    stats_tex = (tmp_dir / "stats.tex").read_text()
    assert "../" not in stats_tex
    assert "{Q1.png}" in stats_tex and "{Total.png}" in stats_tex
    assert (tmp_dir / "Q1.png").is_file() and (tmp_dir / "Total.png").is_file()


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_stats_compile_with_boxplots_made_in_the_parent_dir(tmp_path):
    tex_dir = Path(__file__).resolve().parent.parent / "tex"
    plots = stats.create_all_boxplots(np.array([[1.0, 2.0, 3.0]]), tmp_dir=str(tmp_path))
    out = stats.create_stats_latex(
        "Statistiques", None, 1, np.array([[1.0, 2.0, 3.0]]), [3, 3], [str(p) for p in plots],
        latex_dir=str(tex_dir), TMP_DIR=str(tmp_path / "tex"),
    )
    assert out.is_file()

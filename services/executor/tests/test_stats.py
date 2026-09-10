"""Statistics report: boxplots and the LaTeX tables fed to pdflatex."""

import os

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

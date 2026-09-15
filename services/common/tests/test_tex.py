"""LaTeX escaping shared by the executor and the server."""

import subprocess

import pytest

from rmn_common.tex import LATEX_ENV, LATEX_FLAGS, TEX_SPECIALS, tex_escape


def test_plain_text_is_unchanged():
    assert tex_escape("Marie Curie") == "Marie Curie"
    assert tex_escape(1234567) == "1234567"


@pytest.mark.parametrize("char", sorted(TEX_SPECIALS))
def test_every_special_character_is_neutralised(char):
    escaped = tex_escape(f"a{char}b")
    assert escaped.startswith("a") and escaped.endswith("b")
    # the raw character only survives behind a backslash
    assert char not in escaped.replace(TEX_SPECIALS[char], "")


def test_input_injection_cannot_leave_the_argument():
    hostile = "}\\input{/etc/passwd}\\newcommand{\\x}{"
    assert "\\input{" not in tex_escape(hostile)


def test_flags_and_environment_close_the_escape_hatches():
    assert "-no-shell-escape" in LATEX_FLAGS
    assert "-halt-on-error" in LATEX_FLAGS
    assert LATEX_ENV["openin_any"] == "p"


@pytest.mark.skipif(
    subprocess.run(["which", "pdflatex"], capture_output=True).returncode != 0,
    reason="pdflatex not installed",
)
def test_a_hostile_name_compiles_under_pdflatex(tmp_path):
    (tmp_path / "doc.tex").write_text(
        "\\documentclass{article}\\begin{document}%s\\end{document}"
        % tex_escape("O'Neil & Sons #1 $5 100% _ {x} ~ ^ \\ }\\input{/etc/passwd}{")
    )
    subprocess.run(
        ["pdflatex", *LATEX_FLAGS, "doc.tex"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/Library/TeX/texbin", **LATEX_ENV},
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert (tmp_path / "doc.pdf").exists()

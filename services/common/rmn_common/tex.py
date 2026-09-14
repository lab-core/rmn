"""LaTeX helpers shared by the executor (stats report) and the server (front pages).

Values coming from a Moodle csv or a zip folder name are typeset: a name with
``&``, ``%``, ``#`` or ``_`` used to break the compile, and one with ``}\\input{``
read arbitrary files into the PDF.
"""

# characters LaTeX gives a meaning to, and how to typeset them literally
TEX_SPECIALS = {
    "\\": "\\textbackslash{}",
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}

# no shell escape, no prompt on error (a compile error hung until the timeout)
LATEX_FLAGS = ["-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error"]

# environment for pdflatex: ``\\input`` and ``\\openin`` may only read files under
# the working directory (TeX Live's default ``openin_any = a`` reads any file)
LATEX_ENV = {"openin_any": "p", "openout_any": "p"}


def tex_escape(text):
    """Escape ``text`` so LaTeX typesets it literally."""
    return "".join(TEX_SPECIALS.get(c, c) for c in str(text))

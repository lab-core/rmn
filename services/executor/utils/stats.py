from pathlib import Path
import os
import unidecode
import subprocess


latex_line = "{} & {} & \\includegraphics[width=\\widthratio \\textwidth]{{{}}}"
n_latex_line = latex_line
latex_line += " \\\\ \\hline"


def create_stats_latex(nom, n_questions, notes, total, boxplots, latex_dir="tex", width_plot_ratio=0.5, tmp_dir="tmp"):
    """
    width_plot_ratio = percentage of the width of the page to be used by the boxplot
    """
    TMP_DIR = Path(tmp_dir).resolve()
    if not TMP_DIR.is_dir():
        os.makedirs(tmp_dir)

    with open(TMP_DIR.joinpath("data.tex"), "w") as f:
        # remove ascents
        u_nom = unidecode.unidecode(nom)
        f.write("\\renewcommand{\\nom}{%s}\n" % u_nom)
        f.write("\\renewcommand{\\widthratio}{%.2f}\n" % width_plot_ratio)

    with open(TMP_DIR.joinpath("stats.tex"), "w") as f:
        for i in range(n_questions):
            f.write(latex_line.format(i+1, notes[i], boxplots[i])+"\n")
        f.write(n_latex_line.format("Total (/ %d)" % total, sum(notes), boxplots[-1])+"\n")

    TEX_DIR = Path(latex_dir).resolve()
    fpdf = create_tex_pdf(TEX_DIR.joinpath("main.tex"), TMP_DIR)
    return TMP_DIR.joinpath(fpdf)


def create_tex_pdf(latex_file, tmp_dir, latex_cmd="pdflatex"):
    # compile latex file
    current = os.getcwd()
    os.chdir(tmp_dir)
    flog = "stdout.log"
    with open(flog, "w") as fstdout:
        try:
            print(latex_file)
            subprocess.check_call([latex_cmd, latex_file], stdout=fstdout, timeout=5)
        except subprocess.TimeoutExpired:
            with open(flog) as f:
                print(f.read())
            raise ChildProcessError("Subprocess latex time out after 5 seconds.")
    os.chdir(current)

    # return path to pdf
    fname = os.path.basename(latex_file)
    fpdf = fname.rsplit(".", 1)[0] + ".pdf"
    return fpdf


if __name__ == "__main__":
    f_boxplot = Path("tex").resolve().joinpath("boxplot.png")
    fpdf = create_stats_latex("George", 1, [5], 10, [f_boxplot, f_boxplot])
    print("Pdf %s created" % fpdf)

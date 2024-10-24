from pathlib import Path
import os
import shutil
import unidecode
import subprocess
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np


latex_line = "{} & {} & {:.2f} & \\includegraphics[width=\\widthratio \\textwidth]{{{}}}"
n_latex_line = latex_line
latex_line += " \\\\ \\hline"


def create_stats_latex(nom, index, n_questions, all_notes, totals, boxplots, latex_dir="tex", width_plot_ratio=0.5, TMP_DIR="tmp"):
    """
    width_plot_ratio = percentage of the width of the page to be used by the boxplot
    """
    if isinstance(TMP_DIR, str):
        TMP_DIR = makedir_path(TMP_DIR)

    with open(TMP_DIR.joinpath("data.tex"), "w") as f:
        # remove ascents
        u_nom = unidecode.unidecode(nom)
        f.write("\\renewcommand{\\nom}{%s}\n" % u_nom)
        f.write("\\renewcommand{\\widthratio}{%.2f}\n" % width_plot_ratio)

    averages = np.average(all_notes, axis=1)
    with open(TMP_DIR.joinpath("stats.tex"), "w") as f:
        for i in range(n_questions):
            f.write(latex_line.format("%d (/ %d)" % (i+1, totals[i]), all_notes[i][index] if index is not None else "",
                                      averages[i], boxplots[i])+"\n")
        f.write(n_latex_line.format("Total (/ %d)" % totals[-1],
                                    sum(notes[index] for notes in all_notes) if index is not None else "",
                                    sum(averages), boxplots[-1])+"\n")

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


def create_boxplot(notes, title, tmp_dir="tmp"):
    # Create a horizontal boxplot
    plt.figure(figsize=(6, 2))
    sns.set_style('darkgrid')
    sns.set_palette('Set2')
    sns.boxplot(x=notes, orient='h')

    # Add labels and title
    plt.xlabel('Note')
    plt.title(title)

    # Show the plot
    TMP_DIR = makedir_path(tmp_dir)
    f_boxplot = TMP_DIR.joinpath(title+".png")
    plt.savefig(f_boxplot)  # save the figure
    plt.clf()  # clear the figure
    return f_boxplot


def create_all_boxplots(all_notes, tmp_dir="tmp"):
    """
    all_notes: it's a 2D numpy array that contains an array with all the notes for each question
    """
    # Iterate through each question and create its associated boxplot
    f_boxplots = [create_boxplot(notes, "Q%d" % (q+1), tmp_dir) for q, notes in enumerate(all_notes)]

    # create the final boxplot for the total
    f_boxplots.append(create_boxplot(sum(all_notes), "Total", tmp_dir))

    return f_boxplots


def makedir_path(dir_name):
    DIR = Path(dir_name).resolve()
    if not DIR.is_dir():
        os.makedirs(dir_name)
    return DIR


def remove_non_pdfs(directory):
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if not filename.endswith('.pdf'):
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')


# if __name__ == "__main__":
#     import numpy as np
#     # Generate some notes for 100 copies and 2 questions
#     np.random.seed(10)
#     all_notes = np.array([np.random.randint(low=2, high=11, size=100), np.random.randint(low=0, high=8, size=100)])
#     f_boxplots = create_all_boxplots(all_notes)
#     fpdf = create_stats_latex("George", 0, 2, all_notes, 20, f_boxplots)

#     fpdf = create_stats_latex("Moyennes", None, 2, all_notes, 20, f_boxplots)

#     # f_boxplot = Path("tex").resolve().joinpath("boxplot.png")
#     # fpdf = create_stats_latex("George", 1, [5], 10, [f_boxplot, f_boxplot])

#     print("Pdf %s created" % fpdf)

#     # remove tmp folder once the boxplots are not used anymore
#     # os.remove('tmp')

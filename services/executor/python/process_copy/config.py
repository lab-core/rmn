# regex to find a matricule: 7 digits followed by not a number or the end of the line
re_mat = '[1-2]\\d{6}(?=(?:\\D|$))'
len_mat = 7
min_documents_for_max_questions = 1

grade_box = {
    "devoir": {
        'grade': (.1, .9, .6, .9),  # x1, x2, y1, y2 in % of the page width and height
        # 'trim': [(-1, 3)]  # i, n: n number of digits to remove at the end of the ith box
    },
    "exam": {
        'grade': (0.82, .96, 0.15, 0.55),
        # i, n: n number of digits to remove at the end of the ith box. -1 means to trim everything
        # 'trim': [(0, -1), (1, 2), (2, 2), (3, 3), (4, 2), (5, 3)]
    }
}
# default coordinates
matricule_box = {
    "exam": {
        'front': (0.05, 0.85, 0.15, 0.35),
        'regular': (0.55, 0.95, 0.05, 0.13),
        'separate_box': True  # True if there are some boxes for each digit of the matricule
    }
}

# digit the model confuses -> digit it may actually be. The second one is added
# to the candidates of a box with probability 0, so it is only chosen when the
# total check needs it: a printed or handwritten 1 with a top flag reads as 7.
known_mistmatch = {7: 1}
# same for the handwritten digits of a matricule. A candidate added here only
# ranks after every real candidate, so it never changes a standalone reading;
# it lets the lookup against the class lists recover a matricule whose digit
# the model does not even propose (a 9 written like a 3, a thin 2 read as 1).
known_mistmatch_matricule = {7: 1, 3: 9, 1: 2}
# margins (fraction of the digit's size) around a digit in the 28 x 28 square
# given to the model; the probabilities are averaged over them. The model was
# trained on MNIST (digit in about 70% of the frame) mixed with frame-filling
# digits. A wider 0.4 framing reads a flat handwritten 0 as a 9.
digit_margins = [0.1, 0.25]

class Latex:
    cmd = "pdflatex"
    input_file = 'data.tex'
    input_content = "\\renewcommand{\\nom}{%s}\n\\renewcommand{\\matricule}{%s}\n"


# MoodleFields moved to rmn_common.moodle (shared with the server)


# --- decimal part of a recognised grade ---------------------------------------
# Decimal parts a grade can take, as the student writes them: "0" for a whole
# number, "5" for a half, "25" and "75" for the quarters. The digit
# combinations recognised in a box are tried by decreasing probability and the
# first one whose decimal part is listed here wins. When none is, the decimal
# part is replaced by one drawn at random among the allowed parts written with
# the same number of digits: a single recognised digit can only become ".5",
# the one-digit part other than "0". Edit this list to change what is allowed.
allowed_decimals = ["0", "25", "5", "75"]

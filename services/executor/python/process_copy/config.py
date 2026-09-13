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

known_mistmatch = {}

class Latex:
    cmd = "pdflatex"
    input_file = 'data.tex'
    input_content = "\\renewcommand{\\nom}{%s}\n\\renewcommand{\\matricule}{%s}\n"


class MoodleFields:
    mat = 'Matricule'
    name = 'Nom complet'
    id = 'Identifiant'
    question = 'Question'
    grade = 'Note'
    max = 'Note maximale'
    mdate = 'Dernière modification (note)'
    status = 'Statut'
    status_start_filter = 'Remis'
    group = '(?i)(gr|groupe?s?)$'


# --- decimal part of a recognised grade ---------------------------------------
# Decimal parts a grade can take (quarters of a point).
allowed_decimals_part = [.25, .5, .75]

# How a recognised decimal part is stored, keyed by the recognised decimals
# rounded to two digits. One recognised digit means the student wrote one
# decimal digit, and the only one-digit quarter is .5: whatever the digit was
# read as (".1", ".7", ...), it is stored as .5. A recognised decimal part that
# is neither listed here nor in allowed_decimals_part is snapped to the nearest
# allowed value (or 0). Edit this table to change the conversions.
decimal_conversions = {
    0.1: 0.5,
    0.2: 0.5,
    0.3: 0.5,
    0.4: 0.5,
    0.6: 0.5,
    0.7: 0.5,
    0.8: 0.5,
    0.9: 0.5,
}

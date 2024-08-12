import os

DIR = os.path.abspath(os.path.dirname(__file__))

default_templates = {
    "Page de couverture": {
        "src": os.path.join(DIR, 'couverture', 'page_couverture_exam.docx'),
        'grade_box': [0.82, .96, 0.15, 0.55],
        'matricule_box': [0.05, 0.85, 0.15, 0.35]
    },
    "Page intérieure": {
        "src": os.path.join(DIR, 'interieur', 'template_exam.tex'),
        'matricule_box': [0.55, 0.95, 0.05, 0.13]
    }
}

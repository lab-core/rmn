"""Column names of a Moodle grades export (French Moodle)."""


class MoodleFields:
    mat = "Matricule"
    name = "Nom complet"
    id = "Identifiant"
    question = "Question"
    grade = "Note"
    max = "Note maximale"
    mdate = "Dernière modification (note)"
    status = "Statut"
    status_start_filter = "Remis"
    # regex matched against the column names to find the group column
    group = "(?i)(gr|groupe?s?)$"

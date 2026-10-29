# 10. Rendre les notes sur Moodle

Retournez dans le devoir Moodle → **Consulter tous les travaux remis**. Les deux imports se font avec le menu **Action d'évaluation**.

## Importer les notes

1. **Action d'évaluation** → **Importer le formulaire d'évaluation**.
2. Déposez le `notes.csv` téléchargé de rmn.
3. Cochez l'option qui autorise la mise à jour des notes modifiées plus récemment dans Moodle que dans le fichier, si des notes ont déjà été saisies dans Moodle.
4. **Importer le formulaire d'évaluation** : Moodle affiche la liste des notes qu'il va modifier. Vérifiez-la, puis **Confirmer**.

Moodle associe chaque ligne à un étudiant par la colonne `Identifiant` et lit la colonne `Note`. Les colonnes Q1, Q2… ajoutées par rmn sont ignorées par Moodle, mais restent utiles dans vos archives.

> **Étudiants sans copie** : rmn leur met la note **0** (leurs colonnes Q1, Q2… restent vides). Si une absence est justifiée, supprimez la ligne de l'étudiant du `notes.csv` avant l'import, ou corrigez sa note dans Moodle après.

## Déposer les copies corrigées

1. **Action d'évaluation** → **Déposer plusieurs fichiers de feedback dans un fichier ZIP**.
2. Déposez `moodle.zip` **tel quel**, sans le décompresser ni renommer ses dossiers : Moodle reconnaît chaque étudiant par le nom de son dossier.
3. Moodle liste les fichiers qu'il va associer à chaque étudiant : **Confirmer**.
4. S'il y a plusieurs zip (`moodle-2.zip`…), recommencez avec chacun.

<!-- TODO capture : img/moodle-import.png (confirmation de l'import du formulaire d'évaluation) -->

## Publier

Vérifiez quelques étudiants dans **Consulter tous les travaux remis** : la note et le fichier de feedback (la copie corrigée) doivent apparaître. Si le devoir utilise le flux d'évaluation, passez les notes à l'état « Publié » pour que les étudiants les voient ; sinon elles sont visibles dès l'import, selon les réglages du carnet de notes du cours.

> À confirmer sur votre Moodle : le comportement de l'import du formulaire d'évaluation avec le flux d'évaluation activé.

C'est terminé. La tâche reste archivée dans rmn : vous pourrez retélécharger les fichiers, ou la **Dupliquer** pour l'examen suivant.

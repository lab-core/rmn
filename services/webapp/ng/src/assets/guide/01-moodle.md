# 1. Préparer le devoir Moodle

rmn échange avec Moodle par l'activité **Devoir**. Il en lit le *formulaire d'évaluation* (un csv avec un étudiant par ligne) et y renvoie les notes et les copies corrigées. Créez le devoir avant l'examen, ou au plus tard avant de créer la tâche dans rmn.

Dans votre cours : **Activer le mode édition**, puis **Ajouter une activité ou ressource** → **Devoir**.

> Les libellés ci-dessous sont ceux de Moodle 4 en français. Ils peuvent varier légèrement selon la version de votre établissement.

## Les réglages du devoir

| Section | Réglage | Valeur | Pourquoi |
|---------|---------|--------|----------|
| Généraux | Nom | par ex. « Examen final » | – |
| Disponibilité | Dates de remise | cas A : la fenêtre de dépôt ; cas B : sans importance | – |
| Types de remise | Remise de fichiers | cas A : **coché** ; cas B : décoché | cas A : les étudiants déposent leur copie |
| Types de remise | Nombre maximal de fichiers téléversés | **1** | rmn attend un seul PDF par étudiant |
| Types de remise | Types de fichiers acceptés | **.pdf** | rmn ne lit que des PDF |
| Types de feedback | Fichiers de feedback | **coché** | pour renvoyer à chaque étudiant sa copie corrigée |
| Types de feedback | Feuille d'évaluation hors ligne | **coché** | c'est le csv que rmn lit et remplit |
| Types de feedback | Commentaires de feedback | au choix | rmn ne s'en sert pas |
| Note | Type | **Point** | rmn écrit une note en points |
| Note | Note maximale | **le total de l'examen** (bonus compris s'il y en a) | Moodle refuse une note plus grande que le maximum |
| Note | Remises anonymes | **Non** | rmn a besoin du nom et du matricule de chaque étudiant |
| Paramètres des groupes | Mode de groupe | au choix | une colonne « Groupe » du csv sert à trier les copies par groupe |

Enregistrez avec **Enregistrer et afficher**.

<!-- TODO capture : img/moodle-reglages.png (sections Types de remise / Types de feedback du formulaire du devoir) -->

## Le matricule doit être visible

rmn associe chaque copie à un étudiant par son **matricule**. La colonne `Matricule` doit donc figurer dans le formulaire d'évaluation. Elle y figure si le matricule fait partie des *champs d'identité* affichés aux enseignants, ce qui se règle au niveau du site par l'administrateur Moodle. Pour le vérifier, ouvrez le devoir puis **Consulter tous les travaux remis** : une colonne Matricule (ou « Numéro d'identification ») doit apparaître à côté du nom. Sinon, demandez à l'administrateur Moodle de l'ajouter aux champs d'identité.

> À confirmer sur votre Moodle : le libellé exact de la colonne. rmn cherche une colonne nommée exactement `Matricule`.

## Cas A ou cas B ?

- **Cas A** : les étudiants numérisent leur copie (avec un téléphone ou un scanner) et la déposent dans le devoir. Vous récupérez toutes les copies d'un coup (voir [Récupérer les fichiers Moodle](04-fichiers-moodle.md#cas-a--le-zip-des-travaux-remis)).
- **Cas B** : vous ramassez les copies papier et les numérisez vous-même. Le devoir n'a pas besoin de remise de fichiers, mais il doit quand même exister : c'est lui qui fournit la liste des étudiants (le csv) et qui recevra les notes.

Suite : [2. Préparer l'examen](02-examen.md).

# Questions fréquentes

## La tâche reste à « Rectifier les pdf »

Des copies n'ont pas le nombre de pages attendu (1 page de garde + le total de la colonne Nombre de pages). Cliquez sur la tâche : la fenêtre liste les copies concernées. Voir [Copies à rectifier](06-suivi.md#copies-à-rectifier).

## « Veuillez fournir un csv valide »

Le fichier n'est pas un csv, ou une ligne n'a pas le même nombre de colonnes que l'en-tête. Retéléchargez le formulaire d'évaluation de Moodle sans le modifier ([chapitre 4](04-fichiers-moodle.md#le-formulaire-dévaluation-csv)).

## Aucun étudiant ne correspond aux matricules

Le csv n'a pas de colonne `Matricule`, ou elle est vide : le matricule n'est pas affiché dans le devoir Moodle. Voir [Le matricule doit être visible](01-moodle.md#le-matricule-doit-être-visible).

## Un étudiant manque dans la liste des matricules

Il n'était pas inscrit quand le csv a été téléchargé : retéléchargez-le, puis **Mettre à jour csv** dans le tableau de bord.

## Deux copies ont le même matricule

Voir [Matricule utilisé par plusieurs copies](07-matricules.md#matricule-utilisé-par-plusieurs-copies).

## « Finaliser » refuse de démarrer

Des matricules ne sont pas confirmés, ou des copies ne sont pas validées. La ligne Matricules et la colonne Copies corrigées du tableau de bord indiquent ce qui manque.

## Moodle refuse une note

Elle dépasse la **Note maximale** du devoir. Augmentez la note maximale dans Moodle (bonus), ou corrigez la note dans rmn : **Restaurer**, corriger, **Finaliser**.

## Moodle n'associe pas les copies corrigées aux étudiants

Le zip a été décompressé ou ses dossiers renommés, ou bien il vient d'un autre devoir : les identifiants `Participant…` sont propres à chaque devoir. Déposez le `moodle.zip` d'origine dans le devoir dont vient le csv.

## Une copie est arrivée après la création de la tâche

**Copies additionnelles** dans le tableau de bord. Voir [Ajouter des copies ou remplacer le csv](06-suivi.md#ajouter-des-copies-ou-remplacer-le-csv).

## Plusieurs correcteurs

Partagez chaque question avec son correcteur (**Partager** sur la ligne de la question) : il corrige par un lien, sans compte. Voir [Partager la correction](06-suivi.md#partager-la-correction).

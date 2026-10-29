# 12. Administrer rmn

Ce chapitre s'adresse aux administrateurs. Il complète le chapitre [11. Gérer les comptes](11-comptes.md) : un administrateur peut tout ce que peut un gestionnaire, sur tous les comptes, et en plus ce qui suit. Seul un administrateur peut créer un autre administrateur.

## Choisir les gestionnaires d'un compte

La colonne **Gestionnaires** de la page Admin ajoute ou retire les gestionnaires d'un compte. Seuls des comptes Gestionnaire peuvent y figurer ; un administrateur n'en a pas besoin, il gère tous les comptes.

## Prendre le rôle d'un utilisateur

**Prendre le rôle**, sur la ligne d'un compte, ouvre rmn en tant que cet utilisateur, avec tous ses droits : vous voyez ses tâches et pouvez agir pour lui, par exemple pour l'aider à finir une correction. Le menu affiche alors **Revenir à …** en rouge pour retrouver votre compte.

## Changer le rôle, fermer les sessions, supprimer

- **Rôle** : le menu de la colonne Rôle change le rôle d'un compte. Ses sessions ouvertes sont fermées, il se reconnecte avec son nouveau rôle.
- **Fermer les sessions** déconnecte l'utilisateur de tous ses appareils.
- **Supprimer** efface le compte, ses tâches et ses templates, définitivement.

Un administrateur ne peut ni changer son propre rôle ni supprimer son propre compte.

## L'onglet Système

### File d'attente

Le nombre de tâches qui attendent qu'un executor les traite. Il remonte après un dépôt de copies et redescend à mesure qu'elles sont lues.

### Stockage

**Analyser** compte les fichiers que plus aucune tâche ni aucun template ne possède, et montre l'occupation du disque par âge des fichiers. **Nettoyer** supprime les fichiers sans propriétaire ; cochez les options pour supprimer aussi les fichiers inconnus et les tâches dont tous les fichiers ont disparu. Les fichiers modifiés depuis moins de 24 heures ne sont jamais touchés.

### Banque de chiffres

rmn apprend à mieux lire : les chiffres des matricules et des notes que les correcteurs ont confirmés sont gardés pour réentraîner la lecture. **Conserver les chiffres validés** active ou coupe cette conservation pour toutes les tâches. Activée par défaut. Coupée, les chiffres lus ne sont gardés que le temps de la tâche, puis effacés à sa finalisation.

La carte montre ce que la banque contient : le nombre de chiffres et de copies d'où ils viennent, leur répartition de 0 à 9, et leur origine (matricules, cases de note, notes manuscrites). Les **lectures en attente** sont celles des tâches pas encore finalisées : elles n'entrent dans la banque qu'à la finalisation, une fois les matricules et les notes confirmés. **Bien lus à l'époque** compare ce que rmn avait lu à ce que les correcteurs ont confirmé.

### Modèle de lecture

Le modèle qui lit les chiffres. **Évaluer** mesure la part de chiffres qu'il lit juste : sur la partie test de la banque, sur toute la banque et sur MNIST, une collection publique de chiffres manuscrits. Le tableau par chiffre montre en rouge les chiffres lus justes moins de 9 fois sur 10.

**Réentraîner** reprend le modèle livré avec rmn et l'entraîne encore sur la banque, ce qui prend quelques minutes. La banque est partagée une fois pour toutes, copie par copie : environ une copie sur cinq est gardée pour le test et n'entre jamais dans l'entraînement, si bien que les scores sur la partie test sont honnêtes et se comparent d'un entraînement à l'autre. Le score sur toute la banque n'a de sens que pour le modèle d'origine, qui ne l'a jamais vue.

Un modèle entraîné n'est pas mis en service tout seul. La liste des demandes montre son score sur la partie test, en vert quand il fait mieux que le modèle en service ; **Activer** le met en service pour les prochaines lectures, **Modèle d'origine** revient au modèle livré. Les lectures déjà faites ne changent pas. Une seule demande à la fois.

### Anciennes tâches et sessions

**Anciennes tâches** supprime définitivement les tâches de **tous** les utilisateurs ajoutées depuis au moins le nombre de jours indiqué, avec leurs copies. **Anciennes sessions** déconnecte les sessions ouvertes depuis au moins ce nombre de jours.

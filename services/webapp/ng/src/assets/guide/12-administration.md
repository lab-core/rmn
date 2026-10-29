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

### Anciennes tâches et sessions

**Anciennes tâches** supprime définitivement les tâches de **tous** les utilisateurs ajoutées depuis au moins le nombre de jours indiqué, avec leurs copies. **Anciennes sessions** déconnecte les sessions ouvertes depuis au moins ce nombre de jours.

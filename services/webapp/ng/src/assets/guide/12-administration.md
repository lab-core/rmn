# 12. Administrer les comptes

Ce chapitre s'adresse aux gestionnaires et aux administrateurs. Leur page **Admin**, dans le menu, liste les comptes qu'ils gèrent.

## Les rôles

| Rôle | Peut |
|------|------|
| Utilisateur | créer et corriger ses propres tâches |
| Gestionnaire | en plus, créer des comptes Utilisateur et Gestionnaire, et réinitialiser le mot de passe des comptes qu'il gère |
| Administrateur | tout, sur tous les comptes : changer les rôles, choisir les gestionnaires, prendre le rôle d'un utilisateur, supprimer un compte, et l'onglet Système |

Seul un administrateur peut créer un autre administrateur.

## Créer un compte

**Créer un compte** (page Admin, ou page Profil) demande un nom d'utilisateur, un mot de passe et un rôle. Transmettez ce mot de passe à la personne : elle devra le changer à sa première connexion (voir ci-dessous).

Un compte créé par un gestionnaire est géré par lui.

## Premier mot de passe

Un compte nouvellement créé, ou dont le mot de passe a été réinitialisé, porte la mention « mot de passe temporaire ». À sa connexion, son utilisateur arrive sur la page Profil et doit choisir un nouveau mot de passe, différent du temporaire : rien d'autre ne fonctionne avant.

## Réinitialiser un mot de passe

Le bouton de réinitialisation, sur la ligne d'un compte, génère un mot de passe temporaire. Il s'affiche **une seule fois**, avec un bouton pour le copier : transmettez-le à l'utilisateur. Ses sessions ouvertes sont fermées, et il devra choisir un nouveau mot de passe à sa prochaine connexion.

Un gestionnaire ne réinitialise que les comptes qu'il gère.

## Les gestionnaires d'un compte

Un compte peut avoir plusieurs gestionnaires. Celui qui crée un compte en devient le gestionnaire ; un administrateur en ajoute ou en retire dans la colonne **Gestionnaires**. Un gestionnaire voit et réinitialise les comptes qu'il gère, et seulement ceux-là : s'il gère un autre gestionnaire, il ne gère pas pour autant les comptes de celui-ci.

## Prendre le rôle d'un utilisateur

**Prendre le rôle**, sur la ligne d'un compte, ouvre rmn en tant que cet utilisateur, avec tous ses droits : vous voyez ses tâches et pouvez agir pour lui, par exemple pour l'aider à finir une correction. Le menu affiche alors **Revenir à …** en rouge pour retrouver votre compte. Réservé aux administrateurs.

## Changer le rôle, fermer les sessions, supprimer

- **Rôle** : le menu de la colonne Rôle change le rôle d'un compte. Ses sessions ouvertes sont fermées, il se reconnecte avec son nouveau rôle.
- **Fermer les sessions** déconnecte l'utilisateur de tous ses appareils.
- **Supprimer** efface le compte, ses tâches et ses templates, définitivement.

Un administrateur ne peut ni changer son propre rôle ni supprimer son propre compte.

## L'onglet Système

Réservé aux administrateurs.

### File d'attente

Le nombre de tâches qui attendent qu'un executor les traite. Il remonte après un dépôt de copies et redescend à mesure qu'elles sont lues.

### Stockage

**Analyser** compte les fichiers que plus aucune tâche ni aucun template ne possède, et montre l'occupation du disque par âge des fichiers. **Nettoyer** supprime les fichiers sans propriétaire ; cochez les options pour supprimer aussi les fichiers inconnus et les tâches dont tous les fichiers ont disparu. Les fichiers modifiés depuis moins de 24 heures ne sont jamais touchés.

### Anciennes tâches et sessions

**Anciennes tâches** supprime définitivement les tâches de **tous** les utilisateurs ajoutées depuis au moins le nombre de jours indiqué, avec leurs copies. **Anciennes sessions** déconnecte les sessions ouvertes depuis au moins ce nombre de jours.

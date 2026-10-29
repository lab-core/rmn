# 8. Corriger les copies

Depuis le tableau de bord, **Corriger** sur la ligne d'une question. Seules les pages de cette question s'affichent, copie après copie.

![Corriger une question](img/correction.gif)

## Noter une copie

1. Lisez la réponse. Vous pouvez annoter la page avec la barre d'outils du lecteur : **texte**, **dessin** (crayon ou stylet), **gomme**, **annuler / rétablir**. Les annotations sont rendues à l'étudiant avec sa copie.
2. Tapez la note dans le champ **Note**, à côté du titre de la question (« Q2 (/10) »).
3. Validez avec le bouton ✓ ou la touche **Entrée** : la copie passe au vert et la suivante s'ouvre, le curseur déjà dans le champ Note.

Dans la vue **Total**, chaque question a son propre champ de note.

Les flèches de **Version** reviennent aux versions précédentes des annotations d'une copie ; ↺ rétablit la dernière.

## Lecture automatique des notes

Plutôt que de la taper, vous pouvez écrire la note **à la main sur la première page de la question** : avec l'outil dessin du lecteur (validez alors sans rien taper), ou dans les PDF annotés [hors ligne](#corriger-hors-ligne). rmn la lit et la propose dans le champ Note. Une note simple (`7`, `6.5`) ou une fraction du total (`6.5/9`) conviennent, entourées ou non. Une note proposée est encadrée de la couleur de sa confiance, et le survol du champ indique « Note lue automatiquement (confiance N %), à confirmer ». Elle ne compte qu'une fois confirmée par **Entrée** : relisez-la toujours.

Dans le tableau de bord, la colonne Copies corrigées affiche l'avancement de la lecture (« Lecture en cours : N % », puis « Notes lues : … »).

## Les couleurs des copies

| Couleur | Signification |
|---------|---------------|
| gris | non corrigée : pas de note et rien d'écrit sur la page |
| rouge | à confirmer, ou note en cours de lecture |
| bleu → rouge | note lue par rmn : bleu si la lecture est sûre, de plus en plus rouge sinon |
| vert | note validée |
| autres couleurs | copies marquées avec un bouton **Skip** |

Les boutons de couleur **Skip** marquent la copie affichée (par exemple « à revoir avec un collègue ») sans la valider. Masquez la colonne des copies (icône 👁) pour afficher le filtre par couleur.

S'il y a une colonne Groupe dans le csv, **Filtrer par groupe** limite la liste à un groupe.

## Raccourcis clavier

| Touche | Action |
|--------|--------|
| Entrée | valider la note et passer à la copie suivante |
| → / ← | copie suivante / précédente (hors du champ Note) |
| ↓ / ↑ | quatre copies plus bas / plus haut dans la grille |

## Notes au-dessus du maximum

Le tableau de bord signale « N note(s) > max » quand des notes validées dépassent le maximum de la question. Cliquez dessus pour n'afficher que ces copies et les corriger. Si le dépassement est voulu (question bonus), cochez **Bonus** pour cette question.

## Corriger hors ligne

**Gérer mes copies offline** permet de corriger sans connexion ou avec d'autres outils (tablette, logiciel d'annotation) :

1. **Tout télécharger** : un zip avec les copies de la question regroupées en PDF (au plus *Nombre max de copies par pdf* par fichier) et un csv des notes.
2. Annotez les PDF et écrivez-y les notes à la main, ou remplissez le csv.
3. **Tout téléverser** : redéposez le zip. Avec **Lire les notes annotées sur les copies**, rmn lit les notes écrites ; une note saisie dans le csv l'emporte.
4. Confirmez ensuite les notes proposées, comme en ligne.

Suite : [9. Finaliser et télécharger](09-finalisation.md).

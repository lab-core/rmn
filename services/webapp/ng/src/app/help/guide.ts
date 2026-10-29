/**
 * The user guide and the help bubbles of the screens.
 *
 * The guide is the markdown of src/assets/guide (also read on GitHub); a help
 * bubble repeats in one sentence what a section of it explains, and links to
 * that section. Both are kept here so the short texts can be read, and
 * corrected, in one place: when a screen changes, the guide section and its
 * bubble change together (the spec checks every bubble still points to a
 * heading of the guide).
 */

import { UserRole } from '../generated/rmn-contracts';

/** A chapter of the guide: src/assets/guide/<file>.md, shown at /user-guide/<file>. */
export interface GuideChapter {
  file: string;
  title: string;
  /** The least role that sees the chapter in the app; everyone when unset. */
  minRole?: UserRole;
}

export const GUIDE_CHAPTERS: GuideChapter[] = [
  {file: 'README', title: 'Vue d\'ensemble'},
  {file: '01-moodle', title: '1. Préparer le devoir Moodle'},
  {file: '02-examen', title: '2. Préparer l\'examen'},
  {file: '03-template', title: '3. Créer un template'},
  {file: '04-fichiers-moodle', title: '4. Récupérer les fichiers Moodle'},
  {file: '05-nouvelle-tache', title: '5. Créer la tâche'},
  {file: '06-suivi', title: '6. Suivre la tâche'},
  {file: '07-matricules', title: '7. Vérifier les matricules'},
  {file: '08-correction', title: '8. Corriger les copies'},
  {file: '09-finalisation', title: '9. Finaliser et télécharger'},
  {file: '10-retour-moodle', title: '10. Rendre les notes sur Moodle'},
  {file: '11-faq', title: 'Questions fréquentes'},
  {file: '12-comptes', title: '12. Gérer les comptes', minRole: UserRole.MANAGER},
  {file: '13-administration', title: '13. Administrer rmn', minRole: UserRole.ADMIN},
];

const ROLE_ORDER: string[] = [UserRole.USER, UserRole.MANAGER, UserRole.ADMIN];

/** The chapters a role sees: the account chapters stay out of an Utilisateur's
 *  guide, the administration one out of a Gestionnaire's. The files themselves
 *  are not secret (they are on GitHub): this only keeps the guide relevant. */
export function visibleChapters(role: string | undefined): GuideChapter[] {
  const rank = ROLE_ORDER.indexOf(role ?? '');
  return GUIDE_CHAPTERS.filter((c) => !c.minRole || rank >= ROLE_ORDER.indexOf(c.minRole));
}

/** A help bubble: its text and the guide section that says more. */
export interface HelpEntry {
  text: string;
  chapter: string;
  /** The id of a heading of the chapter (see headingId), none for its top. */
  anchor?: string;
}

/**
 * The id GitHub gives a markdown heading, so a link works on both sides:
 * lower case, punctuation dropped, spaces turned into dashes.
 */
export function headingId(text: string): string {
  return text.trim().toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

/** The page of the guide a help entry points to: its chapter, and its heading if any. */
export function guideLink(entry: HelpEntry): string {
  return `/user-guide/${entry.chapter}` + (entry.anchor ? `#${entry.anchor}` : '');
}

export const HELP: Record<string, HelpEntry> = {
  // new task wizard
  'wizard.name': {
    text: 'Un nom qui permet de retrouver la tâche dans la liste, par exemple « MTH1102 Final A26 ».',
    chapter: '05-nouvelle-tache', anchor: 'étape-1--nommer-la-tâche',
  },
  'wizard.templates': {
    text: 'Le template de la page de garde indique où lire le matricule et les cases de notes ; celui des pages suivantes, où lire le matricule sur les autres pages.',
    chapter: '05-nouvelle-tache', anchor: 'étape-2--assigner-les-templates',
  },
  'wizard.copies': {
    text: 'Un zip de PDF, une copie par fichier : le zip « Télécharger tous les travaux remis » de Moodle, ou vos propres numérisations.',
    chapter: '05-nouvelle-tache', anchor: 'étape-3--téléverser-les-copies',
  },
  'wizard.correct': {
    text: 'Décochez si la tâche ne sert qu\'à renommer et trier les copies par matricule, sans notes.',
    chapter: '05-nouvelle-tache', anchor: 'corriger-et-valider-tous-les-matricules',
  },
  'wizard.validate-matricules': {
    text: 'Cochée, chaque matricule lu doit être confirmé à la main ; sinon seuls les matricules douteux sont à vérifier.',
    chapter: '05-nouvelle-tache', anchor: 'corriger-et-valider-tous-les-matricules',
  },
  'wizard.questions': {
    text: 'Pages : nombre de pages de chaque question dans la copie (sert à découper les copies). Points : le maximum de la question. Bonus : la note peut dépasser ce maximum. Ignorer : question absente de cet examen.',
    chapter: '05-nouvelle-tache', anchor: 'le-tableau-des-questions',
  },
  'wizard.stats': {
    text: 'Joint à la copie rendue de chaque étudiant un PDF avec ses notes, et la moyenne, l\'écart-type et l\'histogramme de chaque question.',
    chapter: '05-nouvelle-tache', anchor: 'le-tableau-des-questions',
  },
  'wizard.csv': {
    text: 'Le « formulaire d\'évaluation » téléchargé du devoir Moodle (colonnes Matricule, Identifiant, Nom complet, Note maximale…), sans le modifier.',
    chapter: '05-nouvelle-tache', anchor: 'étape-4--téléverser-le-csv-de-moodle',
  },

  // top menu
  'menu.tasks': {
    text: 'Vos tâches et leur statut. Cliquez sur une tâche pour ouvrir son tableau de bord.',
    chapter: '06-suivi', anchor: 'la-liste-des-tâches',
  },
  'menu.new-task': {
    text: 'Créer une tâche : son nom, les templates, le zip des copies et le csv de Moodle.',
    chapter: '05-nouvelle-tache',
  },
  'menu.templates': {
    text: 'Vos templates : où rmn lit le matricule et les notes sur les pages de vos examens.',
    chapter: '03-template',
  },
  'menu.guide': {
    text: 'Le guide d\'utilisation, de la préparation du devoir Moodle au retour des notes.',
    chapter: 'README',
  },
  'menu.admin': {
    text: 'Les comptes que vous gérez : en créer, réinitialiser un mot de passe.',
    chapter: '12-comptes',
  },
  'menu.profile': {
    text: 'Votre compte : changer votre mot de passe, la sauvegarde des chiffres lus pour améliorer la lecture.',
    chapter: '11-faq', anchor: 'changer-mon-mot-de-passe',
  },
  'menu.stop-impersonating': {
    text: 'Vous agissez à la place d\'un utilisateur : quitte son compte et revient au vôtre.',
    chapter: '13-administration', anchor: 'prendre-le-rôle-dun-utilisateur',
  },
  'menu.logout': {
    text: 'Ferme votre session sur ce navigateur. Les copies gardées pour la correction hors ligne y sont effacées.',
    chapter: '08-correction', anchor: 'corriger-hors-ligne',
  },

  // task list
  'tasks.status': {
    text: 'En préparation → Prêt à la correction → En attente d\'être finalisé → Finalisation en cours → Archivée. « Rectifier les pdf » : des copies n\'ont pas le bon nombre de pages, cliquez sur la tâche.',
    chapter: '06-suivi', anchor: 'les-statuts',
  },

  // dashboard
  'dashboard.questions': {
    text: 'Une ligne par question : copies validées / total, moyenne, écart-type, histogramme. « Corriger » ouvre les copies de la question.',
    chapter: '06-suivi', anchor: 'le-tableau-de-bord',
  },
  'dashboard.reading': {
    text: 'rmn lit les notes écrites sur les copies et les propose, à confirmer, dans la page de correction.',
    chapter: '08-correction', anchor: 'lecture-automatique-des-notes',
  },
  'dashboard.above-max': {
    text: 'Notes validées plus grandes que le maximum de la question : vérifiez-les, ou cochez Bonus si c\'est voulu.',
    chapter: '08-correction', anchor: 'notes-au-dessus-du-maximum',
  },
  'dashboard.matricules': {
    text: 'Matricules confirmés / copies. Tous doivent être confirmés avant de finaliser.',
    chapter: '07-matricules',
  },
  'dashboard.add-copies': {
    text: 'Ajouter des copies arrivées en retard (examen différé…) sans recréer la tâche.',
    chapter: '06-suivi', anchor: 'ajouter-des-copies-ou-remplacer-le-csv',
  },
  'dashboard.update-csv': {
    text: 'Remplacer le formulaire d\'évaluation, par exemple après l\'ajout d\'un étudiant dans Moodle.',
    chapter: '06-suivi', anchor: 'ajouter-des-copies-ou-remplacer-le-csv',
  },
  'dashboard.finalize': {
    text: 'Quand tout est vert : écrit les notes sur les copies, puis prépare le csv et les zip à déposer dans Moodle.',
    chapter: '09-finalisation',
  },
  'dashboard.stats': {
    text: 'Joint à la copie rendue de chaque étudiant un PDF avec ses notes, et la moyenne, l\'écart-type et l\'histogramme de chaque question.',
    chapter: '09-finalisation', anchor: 'les-statistiques-pour-les-élèves',
  },
  'dashboard.absent-zero': {
    text: 'Cochée, un étudiant sans copie notée reçoit 0 dans le csv. Décochée, sa note reste vide et l\'import Moodle n\'y touche pas (absence motivée).',
    chapter: '09-finalisation', anchor: 'les-étudiants-sans-copie',
  },
  'dashboard.share': {
    text: 'Crée un lien pour qu\'un correcteur sans compte corrige cette question (ou vérifie les matricules).',
    chapter: '06-suivi', anchor: 'partager-la-correction',
  },

  'dashboard.read-grades': {
    text: 'Relit les notes écrites sur les copies de cette question (de toutes, sur la ligne Total). Les notes déjà validées sont gardées.',
    chapter: '08-correction', anchor: 'relire-les-notes',
  },
  'dashboard.read-matricules': {
    text: 'Relit les matricules que personne n\'a confirmés. Les copies confirmées ou supprimées ne changent pas.',
    chapter: '07-matricules', anchor: 'relire-les-matricules',
  },

  // grading
  'grading.score': {
    text: 'Tapez la note, puis Entrée pour valider et passer à la copie suivante. Une note proposée par rmn est encadrée de couleur : vérifiez-la.',
    chapter: '08-correction', anchor: 'noter-une-copie',
  },
  'grading.tiles': {
    text: 'Gris : non corrigée. Rouge : à confirmer. Bleu : lue avec confiance, à confirmer. Vert : validée. Les couleurs « Skip » marquent une copie à revoir.',
    chapter: '08-correction', anchor: 'les-couleurs-des-copies',
  },
  'grading.offline': {
    text: 'Tout télécharger : un zip de la question choisie, ou de toutes avec « Tout sélectionner ». Corrigez les PDF ou le csv, puis renvoyez une question ou toutes, dans la même structure.',
    chapter: '08-correction', anchor: 'corriger-hors-ligne',
  },
  'grading.shortcuts': {
    text: 'Entrée : valider. ← → : copie précédente / suivante. ↑ ↓ : quatre copies plus haut / plus bas.',
    chapter: '08-correction', anchor: 'raccourcis-clavier',
  },

  // administration (admin page, profile)
  'admin.roles': {
    text: 'Utilisateur : ses propres tâches. Gestionnaire : crée des comptes et réinitialise ceux qu\'il gère. Administrateur : tous les comptes.',
    chapter: '12-comptes', anchor: 'les-rôles',
  },
  'admin.managers': {
    text: 'Les gestionnaires qui voient ce compte et peuvent réinitialiser son mot de passe. Celui qui crée un compte en devient le gestionnaire.',
    chapter: '13-administration', anchor: 'choisir-les-gestionnaires-dun-compte',
  },
  'admin.create': {
    text: 'Nouveau compte, avec un mot de passe à transmettre : la personne devra le changer à sa première connexion.',
    chapter: '12-comptes', anchor: 'créer-un-compte',
  },
  'admin.temporary': {
    text: 'Ce compte doit choisir un nouveau mot de passe à sa prochaine connexion.',
    chapter: '12-comptes', anchor: 'premier-mot-de-passe',
  },
  'admin.impersonate': {
    text: 'Ouvre rmn en tant que cet utilisateur, avec tous ses droits. « Revenir à … » dans le menu ramène à votre compte.',
    chapter: '13-administration', anchor: 'prendre-le-rôle-dun-utilisateur',
  },
  'admin.reset': {
    text: 'Génère un mot de passe temporaire, affiché une seule fois, et ferme les sessions de l\'utilisateur.',
    chapter: '12-comptes', anchor: 'réinitialiser-un-mot-de-passe',
  },
  'admin.sessions': {
    text: 'Déconnecte l\'utilisateur de tous ses appareils.',
    chapter: '13-administration', anchor: 'changer-le-rôle-fermer-les-sessions-supprimer',
  },
  'admin.delete': {
    text: 'Supprime définitivement le compte, ses tâches et ses templates.',
    chapter: '13-administration', anchor: 'changer-le-rôle-fermer-les-sessions-supprimer',
  },
  'admin.storage': {
    text: 'Analyser compte les fichiers que plus aucune tâche ni aucun template ne possède ; Nettoyer les supprime. Rien de modifié depuis moins de 24 h n\'est touché.',
    chapter: '13-administration', anchor: 'stockage',
  },
  'admin.old-jobs': {
    text: 'Supprime définitivement les tâches de tous les utilisateurs ajoutées depuis au moins ce nombre de jours, avec leurs copies.',
    chapter: '13-administration', anchor: 'anciennes-tâches-et-sessions',
  },
  'admin.old-sessions': {
    text: 'Déconnecte les sessions ouvertes depuis au moins ce nombre de jours.',
    chapter: '13-administration', anchor: 'anciennes-tâches-et-sessions',
  },
  'profile.impersonate': {
    text: 'Choisissez un compte et continuez en tant que cet utilisateur, avec tous ses droits. « Revenir à … » dans le menu ramène à votre compte.',
    chapter: '13-administration', anchor: 'prendre-le-rôle-dun-utilisateur',
  },
  'password.temporary': {
    text: 'Votre mot de passe a été créé ou réinitialisé par un gestionnaire : choisissez-en un nouveau, différent du temporaire.',
    chapter: '11-faq', anchor: 'on-me-demande-un-nouveau-mot-de-passe-à-la-connexion',
  },

  // matricules
  'matricules.select': {
    text: 'Choisissez l\'étudiant dans la liste du csv (tapez le matricule ou le nom), puis validez. La confiance indique la sûreté de la lecture.',
    chapter: '07-matricules', anchor: 'confirmer-un-matricule',
  },
  'matricules.duplicate': {
    text: 'Le même étudiant est associé à plusieurs copies : corrigez l\'une d\'elles, ou supprimez une copie en double.',
    chapter: '07-matricules', anchor: 'matricule-utilisé-par-plusieurs-copies',
  },

  // templates
  'template.zones': {
    text: 'Identification : un rectangle autour des 7 cases du matricule. Questions : un rectangle autour de la seule colonne des cases de note, de Q1 jusqu\'au total, sans les libellés ni les maximums.',
    chapter: '03-template', anchor: 'dessiner-les-zones',
  },

  'template.confirm': {
    text: 'Enregistre le template et essaie d\'en reconnaître les cases : chaque case reconnue est encadrée en rouge, et le nombre de questions s\'affiche. Vérifiez-les.',
    chapter: '03-template', anchor: 'vérifier-la-reconnaissance',
  },

  // final files
  'files.moodle': {
    text: '« moodle » : un dossier par étudiant, à déposer tel quel dans Moodle (« Déposer plusieurs fichiers de feedback dans un fichier ZIP »). « copies » : toutes les copies, par groupe, pour vos archives.',
    chapter: '10-retour-moodle', anchor: 'déposer-les-copies-corrigées',
  },
  'files.notes': {
    text: '« notes » : le formulaire d\'évaluation rempli, à importer dans Moodle (« Importer le formulaire d\'évaluation »).',
    chapter: '10-retour-moodle', anchor: 'importer-les-notes',
  },
};

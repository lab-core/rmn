import { DocumentStatus } from './generated/rmn-contracts';
import { confidenceColour } from './confidence';

// why the grades of a copy may not be where they should on its cover page
// (cover_check, recorded by the executor when it writes them at finalisation)
export const COVER_CHECK_REASONS: {[check: string]: string} = {
  template_position: "cases introuvables sur la copie : notes écrites à l'emplacement des cases du template",
  box_from_template: "une case aux bords recouverts a été replacée d'après le template",
  rules: 'cases trouvées sans le gabarit du template : la colonne des notes peut être la mauvaise',
  not_written: 'cases introuvables : la page de garde est rendue sans les notes',
};

// How much to trust where the grades went, from the surest to the least
// sure, as a confidence on the scale of the matricule tiles (blue: sure, red:
// to look at). Only one box of the table was guessed for box_from_template;
// rules found boxes, maybe the wrong column; template_position found none and
// trusted the template's place; not_written wrote nothing.
const COVER_CHECK_LEVELS: {[check: string]: { label: string, confidence: number }} = {
  box_from_template: { label: 'placement probable', confidence: 0.99 },
  rules: { label: 'placement incertain', confidence: 0.97 },
  template_position: { label: 'placement à vérifier', confidence: 0.95 },
  not_written: { label: 'notes non écrites', confidence: 0 },
};

/** How the grades of a flagged copy were placed: a short label, the reason, a colour. */
export function coverCheck(check: string | null | undefined): { label: string, reason: string, colour: string } | null {
  if (!check) {
    return null;
  }
  const level = COVER_CHECK_LEVELS[check] ?? { label: 'placement à vérifier', confidence: 0 };
  return {
    label: level.label,
    reason: COVER_CHECK_REASONS[check] ?? check,
    colour: confidenceColour(level.confidence, DocumentStatus.HIGH_ACCURACY)!,
  };
}

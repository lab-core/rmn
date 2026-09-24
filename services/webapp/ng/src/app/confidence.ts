import { DocumentStatus } from './generated/rmn-contracts';

// The colours the copy tiles, the score box and the validate button already
// use: red for "à valider", blue for "haute précision". A confidence slides
// between the two instead of jumping from one to the other.
const TO_VALIDATE_RGB: [number, number, number] = [255, 0, 0];
const HIGH_ACCURACY_RGB: [number, number, number] = [65, 65, 247];

// A copy flagged "à valider" (a duplicate matricule, a question the reader
// keeps getting wrong...) must never look confident, whatever the number.
const TO_VALIDATE_MAX_SHADE = 0.6;

/**
 * The colour of a machine reading of confidence `confidence` (0 to 1) on a
 * copy of status `status`, or null when the usual colour of the status
 * applies: nothing was read, or a human validated it, or it is not ready or
 * deleted.
 */
export function confidenceColour(confidence: number | null | undefined, status: string): string | null {
  if (confidence === null || confidence === undefined || Number.isNaN(confidence)) {
    return null;
  }
  if (status !== DocumentStatus.TO_VALIDATE && status !== DocumentStatus.HIGH_ACCURACY) {
    return null;
  }
  let shade = Math.min(1, Math.max(0, confidence));
  if (status === DocumentStatus.TO_VALIDATE) {
    shade = Math.min(shade, TO_VALIDATE_MAX_SHADE);
  }
  const [r, g, b] = TO_VALIDATE_RGB.map((low, i) => Math.round(low + (HIGH_ACCURACY_RGB[i] - low) * shade));
  return `rgb(${r}, ${g}, ${b})`;
}

/** "confiance 73 %", or '' when there is no confidence to show. */
export function confidenceLabel(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined || Number.isNaN(confidence)) {
    return '';
  }
  return `confiance ${Math.round(confidence * 100)} %`;
}

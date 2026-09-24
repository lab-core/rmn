import { confidenceColour, confidenceLabel } from './confidence';
import { DocumentStatus } from './generated/rmn-contracts';

describe('confidenceColour', () => {
  it('slides from the "à valider" red to the "haute précision" blue', () => {
    expect(confidenceColour(0, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(255, 0, 0)');
    expect(confidenceColour(1, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(65, 65, 247)');
    expect(confidenceColour(0.5, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(160, 33, 124)');
  });

  it('never makes a copy still to validate look confident', () => {
    expect(confidenceColour(1, DocumentStatus.TO_VALIDATE)).toBe(confidenceColour(0.6, DocumentStatus.HIGH_ACCURACY));
    expect(confidenceColour(0.2, DocumentStatus.TO_VALIDATE)).toBe(confidenceColour(0.2, DocumentStatus.HIGH_ACCURACY));
  });

  it('leaves the usual colours when there is nothing to shade', () => {
    expect(confidenceColour(null, DocumentStatus.TO_VALIDATE)).toBeNull();
    expect(confidenceColour(undefined, DocumentStatus.HIGH_ACCURACY)).toBeNull();
    // a human validated it: green, whatever the machine thought
    expect(confidenceColour(0.1, DocumentStatus.VALIDATED)).toBeNull();
    expect(confidenceColour(0.9, DocumentStatus.NOT_READY)).toBeNull();
    expect(confidenceColour(0.9, DocumentStatus.DELETED)).toBeNull();
  });

  it('clamps what is out of range', () => {
    expect(confidenceColour(1.4, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(65, 65, 247)');
    expect(confidenceColour(-1, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(255, 0, 0)');
  });
});

describe('confidenceLabel', () => {
  it('rounds to a percentage', () => {
    expect(confidenceLabel(0.734)).toBe('confiance 73 %');
    expect(confidenceLabel(null)).toBe('');
  });
});

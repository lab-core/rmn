import { confidenceColour, confidenceLabel } from './confidence';
import { DocumentStatus } from './generated/rmn-contracts';

describe('confidenceColour', () => {
  it('slides from the "à valider" red to the "haute précision" blue', () => {
    expect(confidenceColour(0, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(255, 0, 0)');
    expect(confidenceColour(1, DocumentStatus.HIGH_ACCURACY)).toBe('rgb(65, 65, 247)');
  });

  it('leaves the blue as soon as the confidence leaves 100 %', () => {
    const blueShare = (c: number) => {
      const [r] = confidenceColour(c, DocumentStatus.HIGH_ACCURACY).match(/\d+/g).map(Number);
      return (255 - r) / (255 - 65);  // 1 = the blue, 0 = the red
    };
    expect(blueShare(0.99)).toBeCloseTo(0.74, 1);
    expect(blueShare(0.95)).toBeCloseTo(0.21, 1);
    expect(blueShare(0.9)).toBeLessThan(0.05);
    expect(blueShare(0.5)).toBe(0);
  });

  it('never makes a copy still to validate look confident', () => {
    // capped at 60 % of the blue: the colour of a 0.6^(1/30) reading
    expect(confidenceColour(1, DocumentStatus.TO_VALIDATE)).toBe(confidenceColour(0.6 ** (1 / 30), DocumentStatus.HIGH_ACCURACY));
    expect(confidenceColour(0.9, DocumentStatus.TO_VALIDATE)).toBe(confidenceColour(0.9, DocumentStatus.HIGH_ACCURACY));
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
  it('rounds down to a percentage: short of certain is never 100 %', () => {
    expect(confidenceLabel(0.734)).toBe('confiance 73 %');
    expect(confidenceLabel(0.996)).toBe('confiance 99 %');
    expect(confidenceLabel(1)).toBe('confiance 100 %');
    expect(confidenceLabel(0.29)).toBe('confiance 29 %');
    expect(confidenceLabel(null)).toBe('');
  });
});

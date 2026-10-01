import { upgradeLegacyInk } from './legacy-ink';

/** A drawing as pdf.js 4.6 (ngx-extended-pdf-viewer 21) stored it. */
function legacy(paths: { bezier: number[]; points: number[] }[]): any {
  return { annotationType: 15, color: [255, 0, 0], thickness: 2, opacity: 1, pageIndex: 3,
           rotation: 0, rect: [0, 0, 100, 100], paths };
}

describe('upgradeLegacyInk', () => {
  it('turns each pdf.js 4 stroke into a pdf.js 6 line and its points', () => {
    const old = legacy([
      { bezier: [1, 2, 3, 4, 5, 6, 7, 8], points: [1, 2, 7, 8] },
      { bezier: [9, 9], points: [9, 9] },  // a dot
    ]);
    const upgraded: any = upgradeLegacyInk(old);
    expect(upgraded.paths.lines[0]).toEqual([NaN, NaN, NaN, NaN, 1, 2, 3, 4, 5, 6, 7, 8]);
    expect(upgraded.paths.lines[1]).toEqual([NaN, NaN, NaN, NaN, 9, 9]);
    expect(upgraded.paths.points).toEqual([[1, 2, 7, 8], [9, 9]]);
    // everything else is kept, and the stored annotation is not touched
    expect({ ...upgraded, paths: undefined }).toEqual({ ...old, paths: undefined });
    expect(Array.isArray(old.paths)).toBeTrue();
  });

  it('draws straight segments for a stroke saved without its bezier', () => {
    const upgraded: any = upgradeLegacyInk(legacy([{ bezier: [], points: [0, 0, 10, 0, 20, 5] }]));
    expect(upgraded.paths.lines[0]).toEqual(
      [NaN, NaN, NaN, NaN, 0, 0, 0, 0, 10, 0, 10, 0, 10, 0, 20, 5, 20, 5]);
  });

  it('leaves the pdf.js 6 drawings and the other annotations alone', () => {
    const current: any = { ...legacy([]), paths: { lines: [[NaN, NaN, NaN, NaN, 1, 1]], points: [[1, 1]] } };
    expect(upgradeLegacyInk(current)).toBe(current);
    const text: any = { annotationType: 3, value: 'ok', pageIndex: 0 };
    expect(upgradeLegacyInk(text)).toBe(text);
    expect(upgradeLegacyInk(undefined)).toBeUndefined();
  });
});

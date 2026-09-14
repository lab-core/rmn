import { csvLines, detectSeparator, splitCsvLine, stripBom } from './csv';

describe('csv helpers', () => {
  it('splits quoted fields and doubled quotes', () => {
    expect(splitCsvLine('1234567,"Dupont, Jean",A,12.5', ',')).toEqual(['1234567', 'Dupont, Jean', 'A', '12.5']);
    expect(splitCsvLine('a;"say ""hi"";x";', ';')).toEqual(['a', 'say "hi";x', '']);
    expect(splitCsvLine('', ',')).toEqual(['']);
  });

  it('detects the separator from the header', () => {
    expect(detectSeparator('Matricule,Nom complet,Note')).toBe(',');
    expect(detectSeparator('Matricule;Nom complet;Note')).toBe(';');
    expect(detectSeparator('Matricule;"Nom, complet";Note')).toBe(';');
  });

  it('strips the byte-order mark and skips blank lines', () => {
    expect(stripBom('\ufeffMatricule')).toBe('Matricule');
    expect(csvLines('\ufeffa,b\r\n1,2\r\n\n')).toEqual(['a,b', '1,2']);
  });
});

import { GUIDE_CHAPTERS, HELP, headingId, visibleChapters } from './guide';

/** The ids of the headings of a markdown chapter, as GitHub and the app give them. */
function headingIds(markdown: string): string[] {
  return markdown.split('\n')
    .filter((line) => /^#{1,4} /.test(line))
    .map((line) => headingId(line.replace(/^#+ /, '')));
}

describe('headingId', () => {
  it('follows the anchors of GitHub', () => {
    expect(headingId('Étape 1 : Nommer la tâche')).toBe('étape-1--nommer-la-tâche');
    expect(headingId('Les couleurs des copies')).toBe('les-couleurs-des-copies');
    expect(headingId('Matricule utilisé par plusieurs copies')).toBe('matricule-utilisé-par-plusieurs-copies');
  });
});

// the real files of src/assets/guide, served by karma like by the app
describe('the help bubbles and the guide', () => {
  const chapters = new Map<string, string>();

  beforeAll(async () => {
    for (const chapter of GUIDE_CHAPTERS) {
      const response = await fetch(`/assets/guide/${chapter.file}.md`);
      chapters.set(chapter.file, response.ok ? await response.text() : '');
    }
  });

  it('every chapter of the table of contents exists', () => {
    for (const chapter of GUIDE_CHAPTERS) {
      expect(chapters.get(chapter.file)).withContext(chapter.file).not.toBe('');
    }
  });

  it('every bubble leads to a heading of the guide', () => {
    for (const [key, entry] of Object.entries(HELP)) {
      const markdown = chapters.get(entry.chapter);
      expect(markdown).withContext(`${key}: chapter ${entry.chapter}`).toBeTruthy();
      if (entry.anchor && markdown) {
        expect(headingIds(markdown)).withContext(`${key}: #${entry.anchor}`).toContain(entry.anchor);
      }
    }
  });

  it('every link between chapters leads to a heading', () => {
    for (const [file, markdown] of chapters) {
      for (const match of markdown.matchAll(/\]\((?:\.\/)?([\w-]+)\.md(?:#([^)]+))?\)/g)) {
        const target = chapters.get(match[1]);
        expect(target).withContext(`${file} -> ${match[1]}`).toBeTruthy();
        if (match[2] && target) {
          expect(headingIds(target)).withContext(`${file} -> ${match[1]}#${match[2]}`).toContain(match[2]);
        }
      }
    }
  });
});

describe('visibleChapters', () => {
  const files = (role?: string) => visibleChapters(role).map((c) => c.file);

  it('keeps the account chapters out of an Utilisateur\'s guide', () => {
    expect(files('Utilisateur')).not.toContain('12-comptes');
    expect(files(undefined)).not.toContain('12-comptes');
    expect(files('Utilisateur')).toContain('11-faq');
  });

  it('gives a Gestionnaire the accounts, not the administration', () => {
    expect(files('Gestionnaire')).toContain('12-comptes');
    expect(files('Gestionnaire')).not.toContain('13-administration');
  });

  it('gives an Administrateur every chapter', () => {
    expect(files('Administrateur')).toEqual(GUIDE_CHAPTERS.map((c) => c.file));
  });
});

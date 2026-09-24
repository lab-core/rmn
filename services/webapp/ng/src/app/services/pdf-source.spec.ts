import { PDFSource } from './pdf-source';

describe('PDFSource', () => {
  const pdf = new Blob(['%PDF-1.4'], { type: 'application/pdf' });

  beforeEach(() => localStorage.clear());

  it('clamps its version to the last one and tells when it is too old to reuse', () => {
    const source = new PDFSource(3, 'blob:3', 5);
    source.setLastVersion(2);
    expect(source.version).toBe(2);
    const unversioned = new PDFSource(4);
    unversioned.setLastVersion(1);
    expect(unversioned.version).toBe(1);

    expect(source.canBeUsed(undefined)).toBeTrue();
    expect(source.canBeUsed(10, 2)).toBeTrue();
    expect(source.canBeUsed(10, 1)).toBeFalse();
    source.timestamp_min -= 20;
    expect(source.isOlderThan(10)).toBeTrue();
    expect(source.canBeUsed(10)).toBeFalse();
  });

  it('round-trips through a dictionary carrying the pdf in base64', async () => {
    const source = new PDFSource(7, URL.createObjectURL(pdf), 1);
    source.setLastVersion(3);
    source.annotations = [{ annotationType: 3 } as any];

    const dict = await source.toJSONDict();
    expect(dict['base64']).toBe('data:application/pdf;base64,' + btoa('%PDF-1.4'));
    expect(dict.lastVersion).toBe(3);

    const copy = new PDFSource();
    await copy.loadDict(dict);
    expect([copy.index, copy.version, copy.lastVersion]).toEqual([7, 1, 3]);
    expect(copy.annotations).toEqual([{ annotationType: 3 } as any]);
    expect(copy.url).toMatch(/^blob:/);
    expect(await copy.blob.text()).toBe('%PDF-1.4');
    const revoke = spyOn(URL, 'revokeObjectURL').and.callThrough();
    copy.destroy();
    expect(revoke).toHaveBeenCalledWith(copy.url);
  });

  it('takes the blob of the dictionary when it has one', async () => {
    const copy = new PDFSource();
    await copy.loadDict({ index: 1, version: 0, annotations: [], blob: pdf });
    expect(copy.blob).toBe(pdf);
    expect(copy.url).toMatch(/^blob:/);
  });

  it('keeps an annotation draft per job and copy, restored only for the same version', () => {
    const source = new PDFSource(2, 'blob:2', 1);
    source.annotations = [{ annotationType: 15 } as any];
    source.save('job');
    expect(JSON.parse(localStorage.getItem('job_pdf_2')).version).toBe(1);

    const same = new PDFSource(2, 'blob:2', 1);
    same.restore('job');
    expect(same.modified).toBeTrue();
    expect(same.annotations.length).toBe(1);

    const newer = new PDFSource(2, 'blob:2', 2);
    newer.restore('job');
    expect(newer.modified).toBeUndefined();
    expect(newer.annotations).toEqual([]);

    source.clear('job');
    expect(localStorage.getItem('job_pdf_2')).toBeNull();
    new PDFSource(0, undefined, 0).save('job');
    new PDFSource(1, undefined, 0).save('job');
    PDFSource.clearAll('job', 2);
    expect(localStorage.length).toBe(0);
    new PDFSource(5).destroy();  // no url: nothing to revoke
  });
});

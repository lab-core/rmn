import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { DocumentsService, PDFSource } from './documents.service';
import { UserService } from './user.service';

const userStub = {
  addTokens: (form: FormData) => {
    form.append('user_id', 'alice');
    form.append('token', 'tok');
  }
};

describe('PDFSource', () => {
  beforeEach(() => localStorage.clear());

  it('clamps its version to the last known one', () => {
    const newer = new PDFSource(0, 'blob:x', 5);
    newer.setLastVersion(3);
    expect(newer.version).toBe(3);

    const unknown = new PDFSource(0, 'blob:x');
    unknown.setLastVersion(2);
    expect(unknown.version).toBe(2);

    const older = new PDFSource(0, 'blob:x', 1);
    older.setLastVersion(2);
    expect(older.version).toBe(1);
    expect(older.lastVersion).toBe(2);
  });

  it('knows when it is too old or the wrong version to be reused', () => {
    const source = new PDFSource(0, 'blob:x', 2);
    expect(source.isOlderThan(1)).toBeFalse();
    expect(source.canBeUsed(undefined)).toBeTrue();
    expect(source.canBeUsed(15, 2)).toBeTrue();
    expect(source.canBeUsed(15, 3)).toBeFalse();

    source.timestamp_min -= 10;
    expect(source.isOlderThan(5)).toBeTrue();
    expect(source.canBeUsed(5)).toBeFalse();
    expect(source.canBeUsed(20)).toBeTrue();
  });

  it('saves and restores its annotations for the same version only', () => {
    const source = new PDFSource(4, 'blob:x', 2);
    source.annotations = [{ id: 'a' } as any];
    source.save('job');
    expect(localStorage.getItem('job_pdf_4')).not.toBeNull();

    const same = new PDFSource(4, 'blob:y', 2);
    same.restore('job');
    expect(same.annotations).toEqual([{ id: 'a' }] as any);
    expect(same.modified).toBeTrue();

    const other = new PDFSource(4, 'blob:z', 3);
    other.restore('job');
    expect(other.annotations).toEqual([]);
    expect(other.modified).toBeUndefined();

    source.clear('job');
    expect(localStorage.getItem('job_pdf_4')).toBeNull();
  });

  it('clearAll drops every saved copy of one job', () => {
    for (let i = 0; i < 3; i++) {
      new PDFSource(i, 'u', 1).save('job');
    }
    new PDFSource(0, 'u', 1).save('other');

    PDFSource.clearAll('job', 3);

    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem('other_pdf_0')).not.toBeNull();
  });

  it('revokes its object URL on destroy', () => {
    spyOn(URL, 'revokeObjectURL');
    new PDFSource(0, 'blob:x').destroy();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x');
    new PDFSource(0).destroy(); // no URL: nothing to revoke
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});

describe('DocumentsService', () => {
  let service: DocumentsService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: UserService, useValue: userStub },
      ]
    });
    service = TestBed.inject(DocumentsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('fetches the document list with the credentials', async () => {
    const pending = service.getDocuments('job', true, [1, 2]);
    const req = http.expectOne('/api/documents');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('questions')).toBe('true');
    expect(form.get('documents_indices')).toBe('[1,2]');
    expect(form.get('user_id')).toBe('alice');
    req.flush({ response: [{ document_index: 1 }] });
    await pending;

    expect(service.documentsList).toEqual([{ document_index: 1 }]);
    expect(service.questions).toBeTrue();
  });

  it('reuses a fresh pdf source and refetches a stale or different version', async () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:1');
    const pending = service.getPdfSource('job', 0, false);
    const req = http.expectOne('/api/document/download');
    expect(req.request.responseType).toBe('blob');
    expect((req.request.body as FormData).get('document_index')).toBe('0');
    req.flush(new Blob(['%PDF']));
    const source = await pending;
    expect(source.url).toBe('blob:1');
    expect(source.index).toBe(0);

    expect(await service.getPdfSource('job', 0, false)).toBe(source);
    http.expectNone('/api/document/download');

    expect(service.getAvailablePdfSource('job', 0, 2)).toBeUndefined();
    source.timestamp_min -= 60;
    expect(service.getAvailablePdfSource('job', 0, undefined, 15)).toBeUndefined();
  });

  it('downloadPdf fetches the annotations and restores local edits of that version', async () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:2');
    const local = new PDFSource(1, 'x', 3);
    local.setLastVersion(4);
    local.annotations = [{ id: 'local' } as any];
    local.save('job');  // what the browser kept from an earlier session

    const pending = service.downloadPdf('job', 1, true, 3);
    http.expectOne('/api/document/download').flush(new Blob(['%PDF']));
    await new Promise(resolve => setTimeout(resolve)); // the annotations request follows the download
    const annotations = http.expectOne('/api/document/annotations');
    expect((annotations.request.body as FormData).get('version')).toBe('3');
    annotations.flush({ last_version: 4, annotations: [{ id: 'server' }] });

    const source = await pending;
    expect(source.version).toBe(3);
    expect(source.lastVersion).toBe(4);
    // the local edits of the same version win over the server's annotations
    expect(source.annotations).toEqual([{ id: 'local' }] as any);
    expect(source.modified).toBeTrue();
  });

  it('a negative version is requested as version 0', async () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:3');
    const pending = service.downloadPdf('job', 1, false, -2);
    const req = http.expectOne('/api/document/download');
    expect((req.request.body as FormData).get('version')).toBe('0');
    expect((req.request.body as FormData).get('with_annotations')).toBe('true');
    req.flush(new Blob(['%PDF']));
    await pending;
  });

  it('returns null when the download fails', async () => {
    spyOn(console, 'error');
    const pending = service.downloadPdf('job', 0, false);
    http.expectOne('/api/document/download').flush(new Blob(), { status: 404, statusText: 'Not Found' });
    expect(await pending).toBeNull();
  });

  it('clearPdfSources revokes every object URL', async () => {
    spyOn(URL, 'createObjectURL').and.returnValues('blob:a', 'blob:b');
    spyOn(URL, 'revokeObjectURL');
    for (const index of [0, 1]) {
      const pending = service.downloadPdf('job', index, false);
      http.expectOne('/api/document/download').flush(new Blob(['%PDF']));
      await pending;
    }

    service.clearPdfSources();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:a');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:b');
    expect(service.getAvailablePdfSource('job', 0)).toBeUndefined();
  });
});

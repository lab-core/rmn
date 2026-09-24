import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpEventType } from '@angular/common/http';
import JSZip from 'jszip';
import { PDFArray, PDFDocument, PDFName } from 'pdf-lib';

import { PdfManagementDialogComponent } from './pdf-management-dialog.component';
import { DocumentsService } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub, waitUntil } from '../../testing/helpers';

describe('PdfManagementDialogComponent', () => {
  let fixture: ComponentFixture<PdfManagementDialogComponent>;
  let component: PdfManagementDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;

  beforeEach(() => {
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [PdfManagementDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRefSpy() },
        { provide: UserService, useValue: userServiceStub() },
        { provide: DocumentsService, useValue: {} },
        { provide: MAT_DIALOG_DATA, useValue: {
          jobId: 'job', index: '1', jobName: 'Exam', nPagesPerQuestion: [['Q1', 2]],
          nMaxPointsPerQuestion: new Map([['Q1', 10], ['Q2', 12]]), bonusEnabledMap: new Map(),
          examsList: [], allExamsList: [], offlineCopies: new Map(),
        } },
      ],
    });
    fixture = TestBed.createComponent(PdfManagementDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('shows the default batch size and takes the user settings', () => {
    const input = fixture.nativeElement.querySelector('#maxCopies') as HTMLInputElement;
    expect(input.value).toBe('40');
    component.setmaxCopies({ target: { valueAsNumber: 25 } });
    expect(component.maxCopiesPerPdf).toBe(25);
    component.setCsvSeparator({ target: { value: ';' } });
    expect(component.csvSeparator).toBe(';');
  });

  it('reads the grades of a csv, detecting the separator and decimal comma', async () => {
    const grades: any = {};
    const comma = new Blob(['Fichier,Index,Note\nQ1.pdf,0,8.5\nQ1.pdf,1,7\nbad,row\n\n']);
    expect(await component.parseCSVGrades('notes.csv', comma, grades)).toBe(2);
    expect(grades).toEqual({ 0: 8.5, 1: 7 });
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('invalid row: bad,row'), 'Erreur!');

    const semicolon = new Blob(['Fichier;Index;Note\nQ1.pdf;3;7,5\n']);
    const more: any = {};
    expect(await component.parseCSVGrades('notes.csv', semicolon, more)).toBe(1);
    expect(more).toEqual({ 3: 7.5 });
  });

  it('copes with a byte-order mark, quoted separators and a non-numeric Index', async () => {
    const grades: any = {};
    const csv = new Blob(['\ufeffFichier,Nom,Index,Note\n"Q1, a.pdf","Dupont, Jean",2,9\nQ1.pdf,x,abc,5\n']);
    expect(await component.parseCSVGrades('notes.csv', csv, grades)).toBe(1);
    expect(grades).toEqual({ 2: 9 });
    // the row with the bad index used to be dropped without a word
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('invalid Index'), 'Erreur!');
  });

  it('refuses a csv without the Index and Note columns', async () => {
    const grades: any = {};
    expect(await component.parseCSVGrades('notes.csv', new Blob(['Fichier,Copie\na,1\n']), grades)).toBe(-1);
    expect(grades).toEqual({});
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('Note or/and Index'), 'Erreur!');
  });

  it('marks pages with a hidden annotation and recognises them again in place', async () => {
    const doc = await PDFDocument.create();
    doc.addPage();
    doc.addPage();
    component.addAnnotation(doc, 0);
    component.addAnnotation(doc, 1);

    expect(component.checkAnnotationAndRemove(doc, 0)).toBeTrue();
    expect(component.checkAnnotationAndRemove(doc, 1)).toBeTrue();
    const annots = doc.getPages()[0].node.lookup(PDFName.of('Annots')) as PDFArray;
    expect(annots.size()).toBe(0);  // the marker is stripped once checked
  });

  it('detects a page that was moved to another position', async () => {
    const source = await PDFDocument.create();
    source.addPage();
    component.addAnnotation(source, 0);  // marked as page 0

    const dest = await PDFDocument.create();
    dest.addPage();
    const [copied] = await dest.copyPages(source, [0]);
    dest.addPage(copied);  // now at position 1

    expect(component.checkAnnotationAndRemove(dest, 1)).toBeFalse();
  });

  it('stamps the copy number on the first page without changing the page count', async () => {
    const doc = await PDFDocument.create();
    doc.addPage([612, 792]);
    await component.addCopyIndex(doc, 42);
    await component.hideCopyIndex(doc, 0);
    expect(doc.getPageCount()).toBe(1);
    const bytes = await doc.save();
    expect(bytes.length).toBeGreaterThan(500);
  });

  // The dialog is opened from the correction screen of one question, but the
  // zip sent back carries whatever was exported -- often every question -- and
  // so does its csv. Matching only the selected question dropped the rest on
  // the floor and warned about the indices it could not place.
  it('grades copies of every question of the task, not only the selected one', () => {
    const q1: any = { document_index: 0, question: 'Q1', status: 'TO VALIDATE' };
    const q2: any = { document_index: 1, question: 'Q2', status: 'TO VALIDATE' };
    component.data.examsList = [q1];            // the question being corrected
    component.data.allExamsList = [q1, q2];     // the whole task

    component.applyImportedGrades({ 0: 8.5, 1: 11 });

    expect(q1.grade).toBe(8.5);
    expect(q1.status).toBe('VALIDATED');
    expect(q2.grade).toBe(11);
    expect(q2.status).toBe('VALIDATED');
    expect(notification.showWarning).not.toHaveBeenCalled();
  });

  it('holds back a grade that is negative or above its question maximum', () => {
    const q1: any = { document_index: 0, question: 'Q1', status: 'TO VALIDATE' };
    const q2: any = { document_index: 1, question: 'Q2', status: 'TO VALIDATE' };
    component.data.allExamsList = [q1, q2];

    component.applyImportedGrades({ 0: 12, 1: -1, 7: 5 });

    // Q1 is out of 10, Q2 out of 12
    expect(q1.status).toBe('TO VALIDATE');
    expect(q2.status).toBe('TO VALIDATE');
    expect(notification.showError).toHaveBeenCalledWith(
      jasmine.stringContaining('0, 1'), 'Erreur');
    expect(notification.showWarning).toHaveBeenCalledWith(
      jasmine.stringContaining('7'), 'Attention');
  });

  it('names the questions the server refused to replace', () => {
    component.reportSkippedQuestions({ response: 'OK', skipped_questions: ['Q2', 'Q3'] });
    expect(notification.showWarning).toHaveBeenCalledWith(
      jasmine.stringContaining('Q2, Q3'), 'Attention');

    notification.showWarning.calls.reset();
    // an upload that wrote everything it carried says nothing
    component.reportSkippedQuestions({ response: 'OK', skipped_questions: [] });
    component.reportSkippedQuestions({ response: 'OK' });
    expect(notification.showWarning).not.toHaveBeenCalled();
  });

  // A Q3 share link lists Q3's copies and nothing else, so the pages of the
  // other questions in the zip have nowhere to be split back to. They were
  // dropped here, before the upload -- which is why the server, which only
  // ever saw Q3, had nothing to refuse.
  it('says a question of the zip has no copies reachable from this link', () => {
    component.data.allExamsList = [
      { document_index: 0, question: 'Q3' },
      { document_index: 1, question: 'Q3' },
    ];

    expect(component.copiesOfQuestion('Q3').length).toBe(2);
    expect(notification.showWarning).not.toHaveBeenCalled();

    expect(component.copiesOfQuestion('Q1')).toEqual([]);
    expect(notification.showWarning).toHaveBeenCalledWith(
      jasmine.stringContaining('Q1'), 'Attention');
  });
});

/** A pdf of `pages` blank letter pages, as bytes. */
async function pdfBytes(pages: number): Promise<Uint8Array<ArrayBuffer>> {
  const doc = await PDFDocument.create();
  for (let i = 0; i < pages; i++) {
    doc.addPage([612, 792]);
  }
  return (await doc.save()) as Uint8Array<ArrayBuffer>;
}

function dataUri(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((b) => { binary += String.fromCharCode(b); });
  return 'data:application/pdf;base64,' + btoa(binary);
}

/** A zip holding `files` (name -> content), as a File the dialog can take. */
async function zipFile(files: Record<string, Uint8Array | string>): Promise<File> {
  const zip = new JSZip();
  for (const [name, content] of Object.entries(files)) {
    zip.file(name, content);
  }
  return new File([await zip.generateAsync({ type: 'blob' })], 'back.zip');
}

/** Read back the `file` part of the form sent to documents/replace. */
async function sentZip(form: FormData): Promise<JSZip> {
  return JSZip.loadAsync(form.get('file') as File);
}

describe('PdfManagementDialogComponent export and import', () => {
  let component: PdfManagementDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let docService: jasmine.SpyObj<DocumentsService>;
  let data: any;
  let savedBlobs: Blob[];
  let downloads: string[];

  beforeEach(() => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    docService = jasmine.createSpyObj<DocumentsService>('DocumentsService', ['getPdfSource', 'getAvailablePdfSource']);
    data = {
      jobId: 'job', index: '1', jobName: 'Exam', nPagesPerQuestion: [['Q1', 1], ['Q2', 2]],
      nMaxPointsPerQuestion: new Map([['Q1', 10], ['Q2', 12]]), bonusEnabledMap: new Map(),
      examsList: [], allExamsList: [], offlineCopies: new Map(),
    };
    TestBed.configureTestingModule({
      declarations: [PdfManagementDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: userServiceStub() },
        { provide: DocumentsService, useValue: docService },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    component = TestBed.createComponent(PdfManagementDialogComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);

    // the failures below are logged on top of the notification the user sees
    spyOn(console, 'error');
    spyOn(console, 'warn');

    // file-saver hands the zip to an anchor it clicks: keep the blob, skip the download
    savedBlobs = [];
    downloads = [];
    const createObjectURL = URL.createObjectURL.bind(URL);
    spyOn(URL, 'createObjectURL').and.callFake((blob: Blob) => {
      savedBlobs.push(blob);
      return createObjectURL(blob);
    });
    spyOn(HTMLAnchorElement.prototype, 'dispatchEvent').and.callFake(function (this: HTMLAnchorElement) {
      downloads.push(this.download);
      return true;
    });
  });

  afterEach(() => http.verify());

  async function exportZip(): Promise<JSZip> {
    await component.downloadAllFilesAsZip();
    await waitUntil(() => downloads.length > 0);
    return JSZip.loadAsync(savedBlobs.at(-1));
  }

  it('exports the copies of each question merged in batches with a grades csv', async () => {
    const page = URL.createObjectURL(new Blob([await pdfBytes(1)], { type: 'application/pdf' }));
    docService.getPdfSource.and.resolveTo({ url: page } as any);
    data.examsList = [
      { document_index: 0, question: 'Q1', filename: 'Q1_0', status: 'VALIDATED', grade: 7 },
      { document_index: 1, question: 'Q1', filename: 'Q1_1', status: 'TO VALIDATE' },
      { document_index: 2, question: 'Q1', filename: 'Q1_2', status: 'NOT READY' },
    ];
    component.maxCopiesPerPdf = 1;
    component.csvSeparator = ';';

    const zip = await exportZip();

    expect(downloads).toEqual(['Exam_Q1.zip']);
    expect(Object.keys(zip.files).sort()).toEqual(['Q1/', 'Q1/Q1.pdf', 'Q1/Q1_1.pdf', 'Q1/notes.csv']);
    const csv = await zip.file('Q1/notes.csv').async('string');
    expect(csv).toBe('Fichier;Index;Note\r\nQ1.pdf;0;7\r\nQ1_1.pdf;1;\r\n');
    // the copy that is not ready is neither fetched nor exported
    expect(docService.getPdfSource).toHaveBeenCalledTimes(2);
    expect(docService.getPdfSource).toHaveBeenCalledWith('job', 0, false, undefined, -1);
    const first = await PDFDocument.load(await zip.file('Q1/Q1.pdf').async('arraybuffer'));
    expect(first.getSubject()).toBe('Q1.pdf');
    expect(first.getPageCount()).toBe(1);
    expect(component.percentageDone).toBe(100);
    expect(component.processing).toBeFalse();
    expect(notification.showSuccess).toHaveBeenCalledWith('Téléchargement terminé!', 'Success');
    expect(dialogRef.close).toHaveBeenCalledWith({ hasDownloadedZip: true });
  });

  it('exports offline copies from the local store and names the zip after the task', async () => {
    data.index = 'Tout sélectionner';
    data.offlineCopies.set(4, { file64: dataUri(await pdfBytes(2)) });
    data.examsList = [{ document_index: 4, question: 'Q2', filename: 'Q2_4', status: 'VALIDATED', offline: true }];

    const zip = await exportZip();

    expect(downloads).toEqual(['Exam.zip']);
    expect(docService.getPdfSource).not.toHaveBeenCalled();
    const merged = await PDFDocument.load(await zip.file('Q2/Q2.pdf').async('arraybuffer'));
    expect(merged.getPageCount()).toBe(2);
  });

  it('stops the export when an offline copy is nowhere to be found', async () => {
    data.examsList = [{ document_index: 9, question: 'Q1', filename: 'Q1_9', status: 'VALIDATED', offline: true }];
    docService.getAvailablePdfSource.and.returnValue(undefined);

    await component.downloadAllFilesAsZip();

    expect(notification.showError).toHaveBeenCalledWith('Copie 9 introuvable hors ligne.', 'Erreur');
    expect(component.processing).toBeFalse();
    expect(downloads).toEqual([]);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  // The whole round trip: what the export produced, sent back unchanged, is
  // split into one pdf per copy and replaces them with the csv grades.
  it('splits an exported zip back into its copies and uploads them with the grades', async () => {
    const page = URL.createObjectURL(new Blob([await pdfBytes(1)], { type: 'application/pdf' }));
    docService.getPdfSource.and.resolveTo({ url: page } as any);
    const copies = [
      { document_index: 0, question: 'Q1', filename: 'Q1_0', status: 'TO VALIDATE' },
      { document_index: 1, question: 'Q1', filename: 'Q1_1', status: 'TO VALIDATE' },
      { document_index: 2, question: 'Q1', filename: 'Q1_2', status: 'TO VALIDATE' },
    ];
    data.examsList = copies;
    data.allExamsList = copies;
    component.maxCopiesPerPdf = 2;  // Q1.pdf holds two copies, Q1_1.pdf the third
    const exported = await exportZip();
    exported.file('Q1/notes.csv', 'Fichier,Index,Note\nQ1.pdf,0,8\nQ1.pdf,1,\nQ1_1.pdf,2,4.5\n');
    exported.file('__MACOSX/Q1/._Q1.pdf', 'resource fork');
    const back = new File([await exported.generateAsync({ type: 'blob' })], 'back.zip');
    component.readGrades = false;

    component.onFileSelected({ target: { files: [back] } });
    const req = await waitForUpload();

    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('user_id')).toBe('alice');
    expect(JSON.parse(form.get('grades') as string)).toEqual({ 0: 8, 2: 4.5 });
    expect(form.get('questions')).toBe('true');
    expect(form.get('read_grades')).toBe('false');
    const split = await sentZip(form);
    expect(Object.keys(split.files).sort()).toEqual(['Q1_0.pdf', 'Q1_1.pdf', 'Q1_2.pdf']);
    const copy = await PDFDocument.load(await split.file('Q1_2.pdf').async('arraybuffer'));
    expect(copy.getPageCount()).toBe(1);
    // the markers the export added are stripped from the pages sent back
    const annots = copy.getPages()[0].node.lookup(PDFName.of('Annots')) as PDFArray;
    expect(annots.size()).toBe(0);
    expect(copies[0]['grade']).toBe(8);
    expect(copies[0].status).toBe('VALIDATED');
    expect(copies[1]['grade']).toBeUndefined();
    expect(component.info).toBe('Uploading (4/4)');

    req.event({ type: HttpEventType.UploadProgress, loaded: 3, total: 4 });
    expect(component.percentageDone).toBe(75);
    req.flush({ response: 'OK', skipped_questions: ['Q2'] });
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('Q2'), 'Attention');
    expect(notification.showSuccess).toHaveBeenCalledWith('Fichiers remplacés avec succès!', 'Succès');
    expect(dialogRef.close).toHaveBeenCalledWith({ hasUploadedZip: true });
    expect(component.processing).toBeFalse();
  });

  async function waitForUpload() {
    await waitUntil(() => matchReplace().length > 0);
    return matchReplace()[0];
  }

  let pending: any[] = [];
  function matchReplace() {
    pending = pending.concat(http.match((r) => r.url.endsWith('documents/replace')));
    return pending;
  }

  beforeEach(() => { pending = []; });

  /** A pdf of `pages` pages as the export writes it: subject, markers. */
  async function exportedPdf(name: string, pages: number, order?: number[]): Promise<Uint8Array> {
    const doc = await PDFDocument.create();
    for (let i = 0; i < pages; i++) {
      doc.addPage([612, 792]);
      component.addAnnotation(doc, i);
    }
    doc.setSubject(name);
    if (!order) {
      return doc.save();
    }
    const shuffled = await PDFDocument.create();
    (await shuffled.copyPages(doc, order)).forEach((p) => shuffled.addPage(p));
    shuffled.setSubject(name);
    return shuffled.save();
  }

  it('drops the files that are not pdf of a question and takes a drop on the zone', async () => {
    data.allExamsList = [{ document_index: 5, question: 'Q2', filename: 'Q2_5', status: 'TO VALIDATE' }];
    const back = await zipFile({ 'Q2/Q2.pdf': await exportedPdf('Q2.pdf', 2), 'readme.pdf': await pdfBytes(1) });
    const event = { preventDefault: jasmine.createSpy('preventDefault'), dataTransfer: { files: [back] } } as any;

    component.onDrop(event);
    const req = await waitForUpload();

    expect(event.preventDefault).toHaveBeenCalled();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('does not match a question'), 'Warning');
    const split = await sentZip(req.request.body);
    expect(Object.keys(split.files)).toEqual(['Q2_5.pdf']);
    expect((await PDFDocument.load(await split.file('Q2_5.pdf').async('arraybuffer'))).getPageCount()).toBe(2);
    expect(req.request.body.get('read_grades')).toBe('true');
    req.flush({ response: 'OK' });
    expect(notification.showWarning).not.toHaveBeenCalled();
  });

  it('ignores a drop or a selection without a file and lets the drag through', () => {
    const upload = spyOn(component, 'uploadZipFile');
    component.onDrop({ preventDefault: () => {}, dataTransfer: { files: [] } } as any);
    component.onFileSelected({ target: { files: [] } });
    const over = { preventDefault: jasmine.createSpy('preventDefault') } as any;
    component.onDragOver(over);
    expect(over.preventDefault).toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it('warns when the pages sent back cover fewer copies than the question has', async () => {
    data.allExamsList = [
      { document_index: 0, question: 'Q1', filename: 'Q1_0' },
      { document_index: 1, question: 'Q1', filename: 'Q1_1' },
      { document_index: 2, question: 'Q3', filename: 'Q3_2' },
    ];
    await component.uploadZipFile(await zipFile({ 'Q1.pdf': await exportedPdf('Q1.pdf', 1) }));
    const req = await waitForUpload();

    expect(notification.showWarning).toHaveBeenCalledWith(
      jasmine.stringContaining('missing: 1 copies'), 'Warning');
    expect(Object.keys((await sentZip(req.request.body)).files)).toEqual(['Q1_0.pdf']);
    req.flush('boom', { status: 500, statusText: 'Server Error' });
    expect(notification.showError).toHaveBeenCalledWith('Erreur lors du remplacement des fichiers', 'Erreur');
    expect(component.processing).toBeFalse();
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('refuses a pdf whose name no longer matches the one it was exported under', async () => {
    await component.uploadZipFile(await zipFile({ 'Q1_1.pdf': await exportedPdf('Q1.pdf', 1) }));

    expect(notification.showError).toHaveBeenCalledWith(
      jasmine.stringContaining('Q1_1.pdf instead of Q1.pdf'), 'Error');
    expect(component.processing).toBeFalse();
    expect(matchReplace()).toEqual([]);
  });

  it('refuses a pdf whose pages were reordered', async () => {
    await component.uploadZipFile(await zipFile({ 'Q2.pdf': await exportedPdf('Q2.pdf', 2, [1, 0]) }));

    expect(notification.showError).toHaveBeenCalledWith(
      jasmine.stringContaining('page 1 is not at the right place'), 'Error');
    expect(component.processing).toBeFalse();
    expect(matchReplace()).toEqual([]);
  });

  it('refuses a question whose number of pages the task does not know', async () => {
    await component.uploadZipFile(await zipFile({ 'Q7.pdf': await exportedPdf('Q7.pdf', 1) }));

    expect(notification.showError).toHaveBeenCalledWith('Nombre de pages inconnu pour Q7.', 'Erreur');
    expect(component.processing).toBeFalse();
    expect(matchReplace()).toEqual([]);
  });

  it('flags the copies whose pages lost their marker and goes on with the others', async () => {
    data.allExamsList = [{ document_index: 0, question: 'Q1', filename: 'Q1_0' }];
    // a page without any annotation: checking its marker throws
    await component.uploadZipFile(await zipFile({ 'Q1.pdf': await (async () => {
      const doc = await PDFDocument.create();
      doc.addPage();
      doc.setSubject('Q1.pdf');
      return doc.save();
    })() }));
    const req = await waitForUpload();

    expect(notification.showWarning).toHaveBeenCalledWith(
      'The Q1 have errors on copies: 1. Check them.', 'Warning');
    req.flush({ response: 'OK' });
  });

  it('reports a pdf of the zip it cannot read', async () => {
    await component.uploadZipFile(await zipFile({ 'Q1.pdf': 'not a pdf' }));
    const req = await waitForUpload();

    expect(notification.showError).toHaveBeenCalledWith('Error processing merged file: Q1.pdf.', 'Erreur');
    expect(Object.keys((await sentZip(req.request.body)).files)).toEqual([]);
    req.flush({ response: 'OK' });
  });

  it('reports a file that is not a zip', async () => {
    await component.uploadZipFile(new File(['plain text'], 'notes.txt'));

    expect(notification.showError).toHaveBeenCalledWith('Erreur lors du traitement du fichier zip', 'Erreur');
    expect(component.processing).toBeFalse();
  });

  it('reports an empty csv', async () => {
    expect(await component.parseCSVGrades('notes.csv', new Blob(['']), {})).toBe(-1);
    expect(notification.showError).toHaveBeenCalledWith('Csv file (notes.csv) is empty.', 'Erreur!');
  });

  it('shows the progress overlay and the step while processing', () => {
    const fixture = TestBed.createComponent(PdfManagementDialogComponent);
    fixture.componentInstance.processing = true;
    fixture.componentInstance.info = 'Splitting (3/4)';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('mat-spinner')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.files-uploading-steps').textContent).toContain('Splitting (3/4)');
  });
});

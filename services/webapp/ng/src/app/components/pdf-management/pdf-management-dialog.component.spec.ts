import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { PDFArray, PDFDocument, PDFName } from 'pdf-lib';

import { PdfManagementDialogComponent } from './pdf-management-dialog.component';
import { DocumentsService } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

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
          nMaxPointsPerQuestion: new Map([['Q1', 10]]), bonusEnabledMap: new Map(), examsList: [], offlineCopies: new Map(),
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
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('invalid row 4'), 'Erreur!');

    const semicolon = new Blob(['Fichier;Index;Note\nQ1.pdf;3;7,5\n']);
    const more: any = {};
    expect(await component.parseCSVGrades('notes.csv', semicolon, more)).toBe(1);
    expect(more).toEqual({ 3: 7.5 });
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
});

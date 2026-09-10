import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import JSZip from 'jszip';

import { TaskRetryDialogComponent } from './task-retry-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

const MESSAGES = ['Erreur: a.pdf a 1 page manquante.', 'Erreur: b.pdf a 2 pages de trop.'];
const pdf = (name: string) => new File(['%PDF'], name, { type: 'application/pdf' });

describe('TaskRetryDialogComponent', () => {
  let fixture: ComponentFixture<TaskRetryDialogComponent>;
  let component: TaskRetryDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;

  const create = (messages: string[] = MESSAGES) => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [TaskRetryDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: userServiceStub() },
        { provide: MAT_DIALOG_DATA, useValue: { taskId: 'job', taskName: 'Exam', taskMessages: messages } },
      ],
    });
    fixture = TestBed.createComponent(TaskRetryDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    spyOn(console, 'error');
  };

  afterEach(() => http.verify());

  it('lists the rejected copies from the error messages', () => {
    create();
    expect(component.filenames).toEqual(['a.pdf a 1 page manquante.', 'b.pdf a 2 pages de trop.']);
    expect(fixture.nativeElement.querySelectorAll('.filename-text').length).toBe(2);
    expect(component.isFileNamesEmpty()).toBeFalse();
    expect(component.isContinueDisabled()).toBeTrue();
  });

  it('a task without messages disables ignore and the zip download', () => {
    create(null);
    expect(component.filenames).toEqual([]);
    expect(component.isFileNamesEmpty()).toBeTrue();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    const ignore = buttons.find(b => b.textContent.includes('Ignorer'));
    expect(ignore.disabled).toBeTrue();
  });

  it('keeps only pdf files from a selection and extracts pdfs out of zips', async () => {
    create();
    const zip = new JSZip();
    zip.file('c.pdf', '%PDF');
    zip.file('dir/.hidden.pdf', '%PDF');
    zip.file('notes.txt', 'x');
    const zipFile = new File([await zip.generateAsync({ type: 'blob' })], 'copies.zip');

    component.onFileSelected({ target: { files: [pdf('a.pdf'), new File(['x'], 'readme.txt', { type: 'text/plain' }), zipFile] } });
    await fixture.whenStable();
    await new Promise(resolve => setTimeout(resolve, 20));

    expect(component.selectedFiles.map(f => f.name)).toEqual(['a.pdf', 'c.pdf']);
    expect(component.disabled).toBeFalse();
    expect(component.isContinueDisabled()).toBeFalse();

    component.deleteFile(0);
    expect(component.selectedFiles.map(f => f.name)).toEqual(['c.pdf']);
    expect(component.isContinueDisabled()).toBeTrue();
  });

  it('accepts dropped files', async () => {
    create();
    const drop = new DragEvent('drop', { cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [pdf('a.pdf')] } });
    component.onDrop(drop);
    await fixture.whenStable();
    expect(drop.defaultPrevented).toBeTrue();
    expect(component.selectedFiles.length).toBe(1);
  });

  it('ignore and continue asks the server to resume and closes with IGNORED', () => {
    create();
    component.ignoreAndContinue();
    const req = http.expectOne('/api/job/ignore');
    expect((req.request.body as FormData).get('job_id')).toBe('job');
    req.flush({ response: 'OK' });
    expect(notification.showSuccess).toHaveBeenCalled();
    expect(dialogRef.close).toHaveBeenCalledWith('IGNORED');
  });

  it('retry uploads the files with progress and closes with CORRECTED', () => {
    create();
    component.selectedFiles = [pdf('a.pdf'), pdf('b.pdf')];
    component.retryJob();
    expect(component.uploading).toBeTrue();

    const req = http.expectOne('/api/job/continue');
    const form = req.request.body as FormData;
    expect((form.get('file0') as File).name).toBe('a.pdf');
    expect((form.get('file1') as File).name).toBe('b.pdf');
    req.event({ type: HttpEventType.UploadProgress, loaded: 1, total: 4 });
    expect(component.uploadProgress).toBe(25);
    req.flush({ response: 'OK' });

    expect(component.uploading).toBeFalse();
    expect(component.uploadedFiles).toEqual(['a.pdf', 'b.pdf']);
    expect(component.selectedFiles).toEqual([]);
    expect(dialogRef.close).toHaveBeenCalledWith('CORRECTED');
  });

  it('a failed upload clears the spinner and warns', () => {
    create();
    component.selectedFiles = [pdf('a.pdf')];
    component.retryJob();
    http.expectOne('/api/job/continue').flush('boom', { status: 500, statusText: 'Error' });
    expect(component.uploading).toBeFalse();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('téléversement'), 'ERREUR');
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('downloading a rejected copy requests it as a blob', () => {
    create();
    component.downloadFile('a.pdf');
    const req = http.expectOne('/api/incorrect/download');
    expect((req.request.body as FormData).get('file')).toBe('a.pdf');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(), { status: 404, statusText: 'Not Found' });
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('téléchargement'), 'ERREUR');
  });

  it('cancel closes without a status', () => {
    create();
    component.cancel();
    expect(dialogRef.close).toHaveBeenCalledWith('');
  });
});

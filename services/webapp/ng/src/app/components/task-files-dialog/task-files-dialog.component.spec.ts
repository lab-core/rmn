import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { TaskFilesDialogComponent } from './task-files-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, settle, userServiceStub } from '../../testing/helpers';

describe('TaskFilesDialogComponent', () => {
  let fixture: ComponentFixture<TaskFilesDialogComponent>;
  let component: TaskFilesDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let dialog: MatDialog;
  let tasks: any;

  const create = (data: any) => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    tasks = { updateTaskStatus: jasmine.createSpy('updateTaskStatus').and.resolveTo(undefined) };
    TestBed.configureTestingModule({
      declarations: [TaskFilesDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: TasksService, useValue: tasks },
        { provide: UserService, useValue: userServiceStub() },
        { provide: MAT_DIALOG_DATA, useValue: { taskId: 'job', nbZipFile: 2, stats: true, ...data } },
      ],
    });
    fixture = TestBed.createComponent(TaskFilesDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    dialog = TestBed.inject(MatDialog);
    fixture.detectChanges();
  };

  afterEach(() => http.verify());

  const inputs = () => Array.from(fixture.nativeElement.querySelectorAll('input[type=text]')) as HTMLInputElement[];

  it('lists one row per zip plus the csv and the stats pdf, with default names', () => {
    create({});
    expect(inputs().map(i => [i.id, i.value])).toEqual([
      ['zip_file-index-0', 'copies'],
      ['zip_file-index-1', 'moodle'],
      ['notes_csv_file', 'notes'],
      ['stats_pdf_file', 'stats'],
    ]);
    expect(component.setDefaultZipValues(2)).toBe('moodle-2');
    expect(fixture.nativeElement.querySelectorAll('button').length).toBe(8);  // download + share per row
  });

  it('hides the share buttons and the stats row when not applicable', () => {
    create({ stats: false, share: true, nbZipFile: 1 });
    expect(inputs().map(i => i.id)).toEqual(['zip_file-index-0', 'notes_csv_file']);
    expect(fixture.nativeElement.querySelectorAll('button').length).toBe(2);
  });

  it('refuses an empty file name', () => {
    create({});
    inputs()[2].value = '   ';
    component.checkInputBox('notes_csv_file', false);
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('nom de fichier'), 'ERREUR');
    http.expectNone('/api/files/share');
  });

  it('downloads through a share link carrying the chosen file name', async () => {
    create({});
    const click = spyOn(HTMLAnchorElement.prototype, 'click');

    component.checkInputBox('zip_file', false, 1);
    const req = http.expectOne('/api/files/share');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('file')).toBe('zip_file');
    expect(form.get('zip_index')).toBe('1');
    req.flush({ response: { share_url: 'https://rmn/api/files/download?job_id=job&token=t' } });
    await settle();

    const anchor = fixture.nativeElement.querySelector('#download-file') as HTMLAnchorElement;
    expect(anchor.getAttribute('href')).toBe('https://rmn/api/files/download?job_id=job&token=t&filename=moodle.zip');
    expect(anchor.getAttribute('download')).toBe('moodle.zip');
    expect(click).toHaveBeenCalled();

    component.checkInputBox('notes_csv_file', false);
    http.expectOne('/api/files/share').flush({ response: { share_url: 'https://rmn/f?x' } });
    await settle();
    expect(anchor.getAttribute('download')).toBe('notes.csv');

    inputs()[3].value = 'moyennes';
    component.checkInputBox('stats_pdf_file', false);
    http.expectOne('/api/files/share').flush({ response: { share_url: 'https://rmn/f?y' } });
    await settle();
    expect(anchor.getAttribute('download')).toBe('moyennes.pdf');
  });

  it('share opens the share dialog and relays its outcome', () => {
    create({});
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of({ success: true, message: 'Le lien a été copié' }) } as any);

    component.checkInputBox('zip_file', true, 0);

    expect(dialog.open).toHaveBeenCalledWith(TaskShareDialogComponent, jasmine.objectContaining({
      data: { taskId: 'job', taskName: 'copies', file: 'zip_file', shareType: 'file', zip_index: 0 },
    }));
    expect(notification.showSuccess).toHaveBeenCalledWith('Le lien a été copié', 'Succès!');

    (dialog.open as jasmine.Spy).and.returnValue({ afterClosed: () => of({ success: false, message: 'nope' }) } as any);
    component.checkInputBox('notes_csv_file', true);
    expect(notification.showError).toHaveBeenCalledWith('nope', 'Erreur!');
  });

  it('restore puts the task back in validation and closes with the new status', async () => {
    create({});
    await component.restore();
    expect(tasks.updateTaskStatus).toHaveBeenCalledWith('job', 'VALIDATION');
    expect(dialogRef.close).toHaveBeenCalledWith('VALIDATION');
    component.cancel();
    expect(dialogRef.close).toHaveBeenCalledWith(undefined);
  });
});

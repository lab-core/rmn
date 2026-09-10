import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { CsvUpdateDialogComponent } from './csv-update-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('CsvUpdateDialogComponent', () => {
  let fixture: ComponentFixture<CsvUpdateDialogComponent>;
  let component: CsvUpdateDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  const csv = new File(['Matricule,Nom complet\n'], 'notes.csv', { type: 'text/csv' });

  beforeEach(() => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [CsvUpdateDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: userServiceStub() },
        { provide: MAT_DIALOG_DATA, useValue: { jobId: 'job-1' } },
      ],
    });
    fixture = TestBed.createComponent(CsvUpdateDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    spyOn(console, 'error');
  });

  afterEach(() => http.verify());

  it('uploads the selected file for the job and closes on OK', async () => {
    component.onFileSelected({ target: { files: [csv] } });

    const req = http.expectOne('/api/job/update/csv');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job-1');
    expect(form.get('user_id')).toBe('alice');
    expect((form.get('csv') as File).name).toBe('notes.csv');
    req.flush({ response: 'OK' });
    await fixture.whenStable();

    expect(notification.showSuccess).toHaveBeenCalled();
    expect(dialogRef.close).toHaveBeenCalled();
  });

  it('reports a refused csv and keeps the dialog open', async () => {
    component.onFileSelected({ target: { files: [csv] } });
    http.expectOne('/api/job/update/csv').flush({ response: 'Error: bad csv' });
    await fixture.whenStable();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('Erreur'), 'Erreur');
    expect(dialogRef.close).not.toHaveBeenCalled();

    component.onFileSelected({ target: { files: [csv] } });
    http.expectOne('/api/job/update/csv').flush('boom', { status: 500, statusText: 'Error' });
    await fixture.whenStable();
    expect(notification.showError).toHaveBeenCalledTimes(2);
  });

  it('accepts a dropped file and ignores empty selections', () => {
    const drop = new DragEvent('drop', { cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [csv] } });
    component.onDrop(drop);
    expect(drop.defaultPrevented).toBeTrue();
    http.expectOne('/api/job/update/csv').flush({ response: 'OK' });

    component.onFileSelected({ target: { files: [] } });
    http.expectNone('/api/job/update/csv');

    const over = new DragEvent('dragover', { cancelable: true });
    component.onDragOver(over);
    expect(over.defaultPrevented).toBeTrue();
  });
});

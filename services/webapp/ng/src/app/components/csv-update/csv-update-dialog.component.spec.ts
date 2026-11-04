import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { CsvUpdateDialogComponent } from './csv-update-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub, waitUntil } from '../../testing/helpers';

describe('CsvUpdateDialogComponent', () => {
  let fixture: ComponentFixture<CsvUpdateDialogComponent>;
  let component: CsvUpdateDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  const csv = (name: string) => new File(['Matricule,Nom complet\n'], name, { type: 'text/csv' });

  function create(lists?: string[]) {
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
        { provide: MAT_DIALOG_DATA, useValue: { jobId: 'job-1', lists } },
      ],
    });
    fixture = TestBed.createComponent(CsvUpdateDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    spyOn(console, 'error');
  }

  const names = () => Array.from(fixture.nativeElement.querySelectorAll('.list-name') as NodeListOf<HTMLElement>)
    .map((e) => e.textContent.trim());
  const saveButton = () => fixture.nativeElement.querySelector('.save-lists') as HTMLButtonElement;
  const pending = () => http.match('/api/jobs/update/csv');

  afterEach(() => http.verify());

  it('lists the task\'s lists, a task given one as « notes », and saves nothing unchanged', () => {
    create();
    expect(names()).toEqual(['notes']);
    expect(saveButton().disabled).toBeTrue();
    component.save();
    http.expectNone('/api/jobs/update/csv');
  });

  it('replaces the list: the old one removed, the new file added, and closes on OK', async () => {
    create();
    (fixture.nativeElement.querySelector('.remove-list') as HTMLButtonElement).click();
    component.onFileSelected({ target: { files: [csv('notes.csv')] } });
    fixture.detectChanges();
    expect(names()).toEqual(['notes', 'notes.csv (ajoutée)']);

    saveButton().click();
    const req = http.expectOne('/api/jobs/update/csv');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job-1');
    expect(form.get('user_id')).toBe('alice');
    expect(form.get('keep')).toBe('[]');
    expect((form.getAll('csv') as File[]).map((f) => f.name)).toEqual(['notes.csv']);
    req.flush({ response: 'OK' });
    await waitUntil(() => dialogRef.close.calls.count() > 0);

    expect(notification.showSuccess).toHaveBeenCalled();
    expect(dialogRef.close).toHaveBeenCalledWith(true);
  });

  it('keeps some lists, adds several files and refuses to remove them all', () => {
    create(['A', 'B']);
    component.kept[0].keep = false;
    component.addFiles([csv('C.csv'), csv('D.csv'), csv('C.csv')]);
    expect(component.added.map((f) => f.name)).toEqual(['D.csv', 'C.csv']);
    component.removeAdded(0);
    component.save();
    const form = http.expectOne('/api/jobs/update/csv').request.body as FormData;
    expect(form.get('keep')).toBe('["B"]');
    expect((form.getAll('csv') as File[]).map((f) => f.name)).toEqual(['C.csv']);

    component.kept[1].keep = false;
    component.added = [];
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.alert').textContent).toContain('au moins une liste');
    expect(saveButton().disabled).toBeTrue();
  });

  it('asks which list a student found in several belongs to, and saves again', async () => {
    create(['A']);
    const open = spyOn(component['dialog'], 'open').and.returnValue(
      { afterClosed: () => of({ '2345678': 'B' }) } as unknown as MatDialogRef<unknown>);
    component.addFiles([csv('B.csv')]);
    component.save();
    http.expectOne('/api/jobs/update/csv').flush(
      { response: 'Error: ...', duplicates: [{ matricule: '2345678', name: 'Bob B', lists: ['A', 'B'] }] },
      { status: 409, statusText: 'Conflict' });

    let retried: ReturnType<typeof pending> = [];
    await waitUntil(() => (retried = pending()).length > 0);
    expect(open).toHaveBeenCalled();
    const [req] = retried;
    expect((req.request.body as FormData).get('assignments')).toBe('{"2345678":"B"}');
    req.flush({ response: 'OK' });
    await waitUntil(() => dialogRef.close.calls.count() > 0);
    expect(dialogRef.close).toHaveBeenCalledWith(true);
  });

  it('says why the server refused and keeps the dialog open', async () => {
    create(['A']);
    component.addFiles([csv('B.csv')]);
    component.save();
    http.expectOne('/api/jobs/update/csv').flush(
      { response: "Error: « B » n'a pas de colonne Matricule." }, { status: 400, statusText: 'Bad Request' });
    await waitUntil(() => notification.showError.calls.count() > 0);
    expect(notification.showError).toHaveBeenCalledWith("« B » n'a pas de colonne Matricule.", 'Erreur');
    expect(dialogRef.close).not.toHaveBeenCalled();
    expect(component.saving).toBeFalse();

    component.save();
    http.expectOne('/api/jobs/update/csv').flush({ response: 'Error: bad csv' });
    await waitUntil(() => notification.showError.calls.count() > 1);
    expect(notification.showError).toHaveBeenCalledWith('Erreur lors du remplacement du fichier csv', 'Erreur');
  });

  it('downloads a list as the task has it now', async () => {
    create(['Section A', 'Section B']);
    const saved: string[] = [];
    spyOn(HTMLAnchorElement.prototype, 'dispatchEvent').and.callFake(function (this: HTMLAnchorElement) {
      saved.push(this.download);
      return true;
    });
    (fixture.nativeElement.querySelectorAll('.download-list')[1] as HTMLButtonElement).click();

    const req = http.expectOne('/api/jobs/class_lists/download');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job-1');
    expect(form.get('name')).toBe('Section B');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['Matricule\n1\n'], { type: 'text/csv' }));
    await waitUntil(() => saved.length > 0);
    expect(saved).toEqual(['Section B.csv']);
    expect(component.kept.every((l) => l.keep)).toBeTrue();  // downloading removes nothing
  });

  it('says when a list cannot be downloaded', async () => {
    create(['A']);
    component.download('A');
    http.expectOne('/api/jobs/class_lists/download').flush(new Blob(['x']), { status: 404, statusText: 'Not Found' });
    await waitUntil(() => notification.showError.calls.count() > 0);
    expect(notification.showError).toHaveBeenCalledWith("La liste « A » n'a pas pu être téléchargée.", 'Erreur');
  });

  it('accepts dropped files and lets the drag through', () => {
    create();
    const drop = new DragEvent('drop', { cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [csv('A.csv'), csv('B.csv')] } });
    component.onDrop(drop);
    expect(drop.defaultPrevented).toBeTrue();
    expect(component.added.map((f) => f.name)).toEqual(['A.csv', 'B.csv']);

    component.onFileSelected({ target: { files: [] } });
    expect(component.added.length).toBe(2);

    const over = new DragEvent('dragover', { cancelable: true });
    component.onDragOver(over);
    expect(over.defaultPrevented).toBeTrue();
  });
});

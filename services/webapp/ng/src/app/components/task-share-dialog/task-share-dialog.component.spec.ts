import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Clipboard } from '@angular/cdk/clipboard';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';

import { DialogData, TaskShareDialogComponent } from './task-share-dialog.component';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, settle, userServiceStub } from '../../testing/helpers';

describe('TaskShareDialogComponent', () => {
  let fixture: ComponentFixture<TaskShareDialogComponent>;
  let component: TaskShareDialogComponent;
  let http: HttpTestingController;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let clipboard: jasmine.SpyObj<Clipboard>;
  let tasks: any;

  const create = (data: Partial<DialogData>) => {
    dialogRef = dialogRefSpy();
    clipboard = jasmine.createSpyObj('Clipboard', ['copy']);
    tasks = {
      setvalidatingTaskId: jasmine.createSpy('setvalidatingTaskId'),
      getTask: jasmine.createSpy('getTask').and.resolveTo({ groups: ['A', 'B'] }),
    };
    TestBed.configureTestingModule({
      declarations: [TaskShareDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: Clipboard, useValue: clipboard },
        { provide: TasksService, useValue: tasks },
        { provide: UserService, useValue: userServiceStub() },
        { provide: MAT_DIALOG_DATA, useValue: { taskId: 'job', taskName: 'Exam', shareType: 'job', ...data } },
      ],
    });
    fixture = TestBed.createComponent(TaskShareDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();  // ngOnInit posts the share request
  };

  beforeEach(() => spyOn(console, 'error'));

  afterEach(() => http.verify());

  it('asks the server for a link scoped to the question and copies it', async () => {
    create({ questionIndex: 2, all: true });
    const req = http.expectOne('/api/job/share');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('question_index')).toBe('2');
    expect(form.get('all')).toBe('true');
    expect(form.get('user_id')).toBe('alice');
    req.flush({ response: { share_url: 'https://rmn/task-validation/?job_id=job&token=t1' } });
    await settle();
    fixture.detectChanges();
    await settle(1);  // ngModel writes the view a microtask after change detection

    expect(component.url).toBe('https://rmn/task-validation/?job_id=job&token=t1');
    expect((fixture.nativeElement.querySelector('input') as HTMLInputElement).value).toBe(component.url);
    expect(fixture.nativeElement.textContent).toContain('Exam');

    component.share();
    expect(clipboard.copy).toHaveBeenCalledWith(component.url);
    expect(dialogRef.close).toHaveBeenCalledWith({ success: true, message: 'Le lien a été copié' });
  });

  it('a matricule share lists the groups and appends the chosen one to the link', async () => {
    create({ shareType: 'matricule' });
    http.expectOne('/api/matricule/share').flush({ response: { share_url: 'https://rmn/m?job_id=job&token=t2' } });
    await settle();
    fixture.detectChanges();

    expect(tasks.setvalidatingTaskId).toHaveBeenCalledWith('job');
    expect(component.groupsList).toEqual(['', 'A', 'B']);
    expect(fixture.nativeElement.querySelector('select')).not.toBeNull();

    component.group = 'A';
    component.getUrl();
    expect(component.url).toBe('https://rmn/m?job_id=job&token=t2&group=A');
    component.group = '';
    component.getUrl();
    expect(component.url).toBe('https://rmn/m?job_id=job&token=t2');
  });

  it('closes with an error when the task cannot be shared or the request fails', async () => {
    create({});
    http.expectOne('/api/job/share').flush({ response: {} });
    await settle();
    expect(dialogRef.close).toHaveBeenCalledWith({ success: false, message: 'Vous ne pouvez pas partager cette tâche.' });

    TestBed.resetTestingModule();
    create({});
    http.expectOne('/api/job/share').flush('nope', { status: 404, statusText: 'Not Found' });
    await settle();
    expect(dialogRef.close).toHaveBeenCalledWith(
      { success: false, message: 'Une erreur est intervenue lors du partage de la tâche !' });
  });

  it('unshare revokes the link for the same scope', async () => {
    create({ all: true });
    http.expectOne('/api/job/share').flush({ response: { share_url: 'https://rmn/d?job_id=job&token=t3' } });
    await settle();

    component.unshare();
    const req = http.expectOne('/api/job/unshare');
    expect((req.request.body as FormData).get('all')).toBe('true');
    req.flush({ response: 'OK' });
    expect(dialogRef.close).toHaveBeenCalledWith(
      { success: true, message: "L'accès a été enlevé pour cette tâche." });
  });

  it('unshare keeps the scope of question 0', async () => {
    create({ questionIndex: 0 });
    http.expectOne('/api/job/share').flush({ response: { share_url: 'https://rmn/x' } });
    await settle();
    component.unshare();
    const req = http.expectOne('/api/job/unshare');
    expect((req.request.body as FormData).get('question_index')).toBe('0');  // was dropped as falsy
    req.flush({ response: 'OK' });
  });

  it('unshare reports a refusal', async () => {
    create({});
    http.expectOne('/api/job/share').flush({ response: { share_url: 'https://rmn/x' } });
    await settle();
    component.unshare();
    http.expectOne('/api/job/unshare').flush({ response: 'Error' });
    expect(dialogRef.close).toHaveBeenCalledWith(
      { success: false, message: "L'accès n'a pas pu être enlevé pour cette tâche." });
  });
});

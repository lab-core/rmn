import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { TasksHistoryComponent, PAGE_SIZE_KEY, PAGE_SIZE_OPTIONS } from './tasks-history.component';
import { TaskRetryDialogComponent } from '../task-retry-dialog/task-retry-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { WarningDialogComponent } from '../warning-dialog/warning-dialog.component';
import { ErrorInfoDialogComponent } from '../error-info-dialog/error-info-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, socketServiceStub, userServiceStub, settle } from '../../testing/helpers';

const JOBS = [
  {
    job_id: 'j1', job_name: 'Retry me', job_status: 'RETRY', queued_time: '2026-09-01 10:00:00',
    front_template_name: 'Front', regular_template_name: 'Regular',
    job_infos: "['Erreur: a.pdf a 1 page manquante.', 'Erreur: b.pdf a 2 pages de trop.']",
  },
  {
    job_id: 'j2', job_name: 'Validate me', job_status: 'VALIDATION', queued_time: '2026-09-02 10:00:00',
    front_template_name: 'Front', regular_template_name: 'Regular', job_infos: '',
  },
];

describe('TasksHistoryComponent', () => {
  let fixture: ComponentFixture<TasksHistoryComponent>;
  let component: TasksHistoryComponent;
  let http: HttpTestingController;
  let router: Router;
  let dialog: MatDialog;
  let notification: jasmine.SpyObj<NotificationService>;
  let socket: any;

  beforeEach(async () => {
    notification = notificationSpy();
    socket = socketServiceStub();
    TestBed.configureTestingModule({
      declarations: [TasksHistoryComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: NotificationService, useValue: notification },
        { provide: SocketService, useValue: socket },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    dialog = TestBed.inject(MatDialog);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(console, 'error');

    fixture = TestBed.createComponent(TasksHistoryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/jobs').flush({ response: JSON.parse(JSON.stringify(JOBS)) });
    await settle();  // ngOnInit awaits the list before joining the rooms
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('loads the jobs, decodes their status and the retry messages', () => {
    expect(component.tasksList.length).toBe(2);
    const retry = component.tasksList[0];
    expect(retry.info).toBe('Rectifier les pdf');
    expect(retry.job_infos).toEqual(['Erreur: a.pdf a 1 page manquante.', 'Erreur: b.pdf a 2 pages de trop.']);
    expect(retry.queued_time instanceof Date).toBeTrue();
    expect(component.tasksList[1].info).toBe('Prêt à la correction et vérification des matricules');

    const cells = Array.from(fixture.nativeElement.querySelectorAll('td.job_name_css')).map((c: HTMLElement) => c.textContent.trim());
    expect(cells.sort()).toEqual(['Retry me', 'Validate me']);
    expect(socket.join).toHaveBeenCalledWith('alice');
  });

  it('a socket status change updates the row and notifies', async () => {
    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'j2', status: 'ARCHIVED' }));
    expect(component.tasksList[1].job_status).toBe('ARCHIVED');
    expect(component.tasksList[1].info).toBe('Archivée');
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('Validate me'), 'Alerte!');

    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'unknown', status: 'RUN' }));
    expect(notification.showInfo).toHaveBeenCalledTimes(1);
  });

  it('a task can be duplicated: the wizard opens on it', () => {
    // the row of a known task: the table's order is its own business
    const row = Array.from(fixture.nativeElement.querySelectorAll('tr.element-row'))
      .find((r: HTMLElement) => r.textContent.includes('Retry me')) as HTMLElement;
    const button = Array.from(row.querySelectorAll('button'))
      .find((b: HTMLButtonElement) => b.textContent.trim() === 'Dupliquer') as HTMLButtonElement;
    expect(button).withContext('the list must offer it').toBeDefined();

    button.click();

    expect(router.navigate).toHaveBeenCalledWith(['/new-exam-correction', 'j1']);
  });

  it('filters the table', () => {
    component.applyFilter({ target: { value: '  Retry ' } } as any);
    expect(component.dataSource.filter).toBe('retry');
    expect(component.dataSource.filteredData.length).toBe(1);
  });

  it('opens the dashboard of an active task and the retry dialog of a rejected one', () => {
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of('') } as any);
    component.goToDashBoard(component.tasksList[1]);
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard', 'j2']);

    component.goToDashBoard(component.tasksList[0]);
    expect(dialog.open).toHaveBeenCalledWith(TaskRetryDialogComponent, jasmine.objectContaining({
      data: jasmine.objectContaining({ taskId: 'j1', taskName: 'Retry me' }),
    }));
  });

  it('a retry that changed the status refreshes the list, a failure warns', () => {
    const task = component.tasksList[0];
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of('CORRECTED') } as any);
    component.retryJob(task);
    http.expectOne('/api/jobs').flush({ response: [] });
    expect(notification.showError).not.toHaveBeenCalled();

    (dialog.open as jasmine.Spy).and.returnValue({ afterClosed: () => of(false) } as any);
    component.retryJob(task);
    expect(notification.showError).toHaveBeenCalledWith(jasmine.any(String), 'Erreur!');
  });

  it('shows the stored error of a failed task', () => {
    spyOn(dialog, 'open');
    component.openErrorInfoDialog({ job_name: 'Failed', job_infos: 'Échec de la finalisation : pdflatex failed' });
    expect(dialog.open).toHaveBeenCalledWith(ErrorInfoDialogComponent, jasmine.objectContaining({
      data: { taskName: 'Failed', infos: 'Échec de la finalisation : pdflatex failed' },
    }));
  });

  it('deletes after confirmation, dropping the row before the server answers', () => {
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(true) } as any);
    component.openDeleteDialog('j1');
    expect(dialog.open).toHaveBeenCalledWith(WarningDialogComponent, jasmine.objectContaining({
      data: jasmine.stringContaining('Retry me'),
    }));
    expect(component.tasksList.map(t => t.job_id)).toEqual(['j2']);

    const del = http.expectOne('/api/jobs/delete');
    expect((del.request.body as FormData).get('job_id')).toBe('j1');
    del.flush({ response: 'OK' });
    http.expectOne('/api/jobs').flush({ response: [JOBS[1]] });
    http.match('/api/documents').forEach(req => req.flush({ response: [] }));
    expect(component.tasksList.length).toBe(1);
  });

  it('does not delete when the confirmation is refused', () => {
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(false) } as any);
    component.openDeleteDialog('j1');
    http.expectNone('/api/jobs/delete');
    expect(component.tasksList.length).toBe(2);
  });

  it('share opens the dialog for the whole task and relays the result', () => {
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of({ success: true, message: 'Le lien a été copié' }) } as any);
    component.shareJob('j2', 'Validate me');
    expect(dialog.open).toHaveBeenCalledWith(TaskShareDialogComponent, jasmine.objectContaining({
      data: { taskId: 'j2', taskName: 'Validate me', shareType: 'job', all: true },
    }));
    expect(notification.showSuccess).toHaveBeenCalledWith('Le lien a été copié', 'Succès!');
  });

  it('leaves the socket when destroyed', () => {
    fixture.destroy();
    expect(socket.socket.handlers['job_status']).toBeUndefined();
    expect(socket.leave).toHaveBeenCalled();
  });

  // /jobs is only read when the page loads, and a reading is over in seconds,
  // so the row has to learn about one from the events it already receives.
  // The handlers are instance properties, so a real component is needed.
  it('marks a task while its grades are being read, and clears it after', () => {
    const task: any = { job_id: 'j1', job_name: 'T', job_status: 'VALIDATION' };
    component.tasksList = [task] as any;

    (component as any).onJobStatus(JSON.stringify({
      job_id: 'j1', status: 'VALIDATION',
      job_infos: 'Lecture des notes de Q1 : 40/57 (70 %)',
    }));
    expect(task.auto_grade_running).toBeTrue();

    (component as any).onDocumentReady(JSON.stringify({ job_id: 'j1' }));
    expect(task.auto_grade_running).toBeFalse();
  });

  it('does not mark a task for progress that is not a reading', () => {
    const task: any = { job_id: 'j2', job_name: 'T', job_status: 'RETRY' };
    component.tasksList = [task] as any;

    (component as any).onJobStatus(JSON.stringify({
      job_id: 'j2', status: 'RETRY', job_infos: 'Erreur: a.pdf a 1 page manquante.',
    }));
    expect(task.auto_grade_running).toBeFalsy();

    // a percentage alone says "something is working", not "grades are being
    // read": any other long step could report one the same way
    (component as any).onJobStatus(JSON.stringify({
      job_id: 'j2', status: 'RETRY', job_infos: 'Découpage des copies : 3/8 (38 %)',
    }));
    expect(task.auto_grade_running).toBeFalsy();
  });

  describe('the size of a page of tasks', () => {
    // a fixture of its own: the size is read when the component is built
    async function reopenList(): Promise<TasksHistoryComponent> {
      const reopened = TestBed.createComponent(TasksHistoryComponent);
      reopened.detectChanges();
      http.expectOne('/api/jobs').flush({ response: [] });
      await settle();
      reopened.detectChanges();
      return reopened.componentInstance;
    }

    afterEach(() => localStorage.removeItem(PAGE_SIZE_KEY));

    it('offers 5, 10, 20 and 50, and opens on the smallest', async () => {
      localStorage.removeItem(PAGE_SIZE_KEY);
      const reopened = await reopenList();
      expect(PAGE_SIZE_OPTIONS).toEqual([5, 10, 20, 50]);
      expect(reopened.paginator.pageSizeOptions).toEqual([5, 10, 20, 50]);
      expect(reopened.paginator.pageSize).toBe(5);
    });

    it('reopens on the size the user picked', async () => {
      component.onPage({ pageIndex: 0, pageSize: 20, length: 2 });
      expect(component.pageSize).toBe(20);
      expect(localStorage.getItem(PAGE_SIZE_KEY)).toBe('20');

      const reopened = await reopenList();
      expect(reopened.paginator.pageSize).toBe(20);
    });

    it('opens on the smallest size when the stored one is not offered', async () => {
      localStorage.setItem(PAGE_SIZE_KEY, '8');  // a size of an older version
      expect((await reopenList()).paginator.pageSize).toBe(5);

      localStorage.setItem(PAGE_SIZE_KEY, 'toutes');
      expect((await reopenList()).paginator.pageSize).toBe(5);
    });
  });

});

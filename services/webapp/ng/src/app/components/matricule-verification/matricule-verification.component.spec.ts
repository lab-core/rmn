import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { NgSelectModule } from '@ng-select/ng-select';
import { of } from 'rxjs';

import { MatriculeVerificationComponent } from './matricule-verification.component';
import { WarningDialogComponent } from '../warning-dialog/warning-dialog.component';
import { DocumentsService } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { ValidationService } from 'src/app/services/validation.service';
import {
  MATERIAL_MODULES, PdfViewerStubComponent, notificationSpy, routeStub, settle, socketServiceStub, userServiceStub, waitUntil,
} from '../../testing/helpers';

const JOB = {
  job_id: 'job', job_status: 'VALIDATION', groups: ['A', 'B'],
  students_list: [
    { matricule: '1234567', 'Nom complet': 'Alice A' },
    { matricule: '2345678', 'Nom complet': 'Bob B' },
    { matricule: '3456789', 'Nom complet': 'Carol C' },
  ],
};
const EXAMS = [
  { document_index: 0, status: 'VALIDATED', matricule: '1234567', filename: 'a', group: 'A' },
  { document_index: 1, status: 'TO VALIDATE', matricule: '2345678', filename: 'b', group: 'B' },
  { document_index: 2, status: 'NOT_READY', matricule: '', filename: 'c', group: 'A' },
  { document_index: 3, status: 'HIGH ACCURACY', matricule: '3456789', filename: 'd', group: 'A' },
];

describe('MatriculeVerificationComponent', () => {
  let fixture: ComponentFixture<MatriculeVerificationComponent>;
  let component: MatriculeVerificationComponent;
  let http: HttpTestingController;
  let router: Router;
  let dialog: MatDialog;
  let notification: jasmine.SpyObj<NotificationService>;
  let socket: any;
  let docs: any;
  let validation: any;

  const create = async (job: any = JOB, queryParams: any = {}) => {
    localStorage.clear();
    notification = notificationSpy();
    socket = socketServiceStub();
    validation = { validateJob: jasmine.createSpy('validateJob').and.resolveTo('OK') };
    docs = {
      documentsList: [],
      getDocuments: jasmine.createSpy('getDocuments').and.callFake(async () => {
        docs.documentsList = docs.documentsList.length ? docs.documentsList : JSON.parse(JSON.stringify(EXAMS));
      }),
      getPdfSource: jasmine.createSpy('getPdfSource').and.callFake(async (jobId, index) => ({ url: `blob:${index}` })),
      clearPdfSources: jasmine.createSpy('clearPdfSources'),
    };
    const tasks = {
      setvalidatingTaskId: jasmine.createSpy('setvalidatingTaskId'),
      getvalidatingTaskId: () => 'job',
      getTask: jasmine.createSpy('getTask').and.resolveTo(job ? JSON.parse(JSON.stringify(job)) : null),
    };
    TestBed.configureTestingModule({
      declarations: [MatriculeVerificationComponent, PdfViewerStubComponent],
      imports: [...MATERIAL_MODULES, NgSelectModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub(queryParams) },
        { provide: NotificationService, useValue: notification },
        { provide: SocketService, useValue: socket },
        { provide: TasksService, useValue: tasks },
        { provide: DocumentsService, useValue: docs },
        { provide: ValidationService, useValue: validation },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    dialog = TestBed.inject(MatDialog);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(MatriculeVerificationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    // either the task was refused (navigation) or its first copy is open
    await waitUntil(() => (router.navigate as jasmine.Spy).calls.count() > 0 || component.currentCopy >= 0);
    await settle();
    fixture.detectChanges();
  };

  beforeEach(() => {
    spyOn(console, 'log');
    spyOn(console, 'error');
  });

  afterEach(() => http.verify());

  it('bounces back when the task is missing or no longer active', async () => {
    await create(null);
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Tâche indisponible');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);

    TestBed.resetTestingModule();
    await create({ ...JOB, job_status: 'ARCHIVED' });
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Tâche inactive');
    expect(docs.getDocuments).not.toHaveBeenCalled();
  });

  it('loads the copies, the students and opens the first available copy', async () => {
    await create();
    expect(component.groupsList).toEqual(['', 'A', 'B']);
    expect(component.matriculeList.map(m => m.identifiant)).toEqual(['1234567 - Alice A', '2345678 - Bob B', '3456789 - Carol C']);
    expect(component.currentCopy).toBe(0);
    expect(component.currentCopyName).toBe('a');
    expect(component.currentMatriculeSelection).toBe('1234567 - Alice A');
    expect(component.currentStatus).toBe('VALIDATED');
    expect(component.colorChosen).toBe('green');
    expect(component.pdfUrl).toBe('blob:0');
    expect(component.disabledValidationcontainer).toBeFalse();
    expect(component.disabledValidationButton).toBeFalse();
    expect(socket.join).toHaveBeenCalledWith('job');
    expect(socket.join).toHaveBeenCalledWith('alice');
    expect(fixture.nativeElement.querySelectorAll('.file-container').length).toBe(4);
    expect(fixture.nativeElement.querySelector('.page-count').textContent).toContain('a (1 / 4)');
    // the following copies are preloaded
    expect(docs.getPdfSource.calls.allArgs().map(a => a[1])).toContain(1);
  });

  it('navigation skips copies that are not ready', async () => {
    await create();
    expect(component.nextCopyIndex(1)).toBe(3);
    expect(component.nextCopyIndex(0, true)).toBe(1);  // skips validated copies when asked
    expect(component.previousCopyIndex(3)).toBe(1);
    expect(component.nextCopyIndex(3)).toBe(4);  // past the end

    component.nextCopy();
    await settle();
    expect(component.currentCopy).toBe(1);
    expect(component.colorChosen).toBe('red');
    component.previousCopy();
    await settle();
    expect(component.currentCopy).toBe(0);
  });

  it('the group filter narrows the list and moves to its first copy', async () => {
    await create();
    expect(component.showFilter()).toBeTrue();
    expect(component.filesListHeight()).toBe('90%');
    component.group = 'B';
    component.loadSubExamsList();
    await settle();
    expect(component.subExamsList.map(e => e.filename)).toEqual(['b']);
    expect(component.currentCopy).toBe(1);
    expect(component.nextCopyIndex()).toBe(4);
  });

  it('warns when the matricule is already used by other copies', async () => {
    await create();
    component.examsList[1].matricule = '1234567';
    component.examsList[3].matricule = '1234567';
    component.getCurrentMatricule();
    expect(component.currentMatriculeWarning).toBe('2, 4');
    component.examsList[1].matricule = '2345678';
    component.examsList[3].matricule = '3456789';
    component.getCurrentMatricule();
    expect(component.currentMatriculeWarning).toBeUndefined();
  });

  it('validating a matricule saves it and moves to the next unvalidated copy', async () => {
    await create();
    component.updateMatricule();
    await settle();  // the request follows the duplicate check
    const req = http.expectOne('/api/matricule/update');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('document_index')).toBe('0');
    expect(form.get('matricule')).toBe('1234567');
    expect(form.get('token')).toBe('tok');
    req.flush({ response: 'OK' });
    await settle();
    expect(component.examsList[0].status).toBe('VALIDATED');
    expect(component.currentCopy).toBe(1);

    component.currentMatriculeSelection = undefined;
    await component.updateMatricule();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Matricule manquante');
    http.expectNone('/api/matricule/update');
  });

  it('a failed update is reported and keeps the copy', async () => {
    await create();
    component.updateMatricule();
    await settle();
    http.expectOne('/api/matricule/update').flush('boom', { status: 500, statusText: 'Error' });
    await settle();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.any(String), 'Erreur de validation');
    expect(component.currentCopy).toBe(0);
    expect(component.pdfLoading).toBeFalse();
  });

  it('deleting and restoring a copy updates its status on the server', async () => {
    await create();
    component.deletePdf();
    let req = http.expectOne('/api/matricule/status/update');
    expect((req.request.body as FormData).get('status')).toBe('DELETED');
    req.flush({ response: 'OK' });
    await settle();
    expect(component.examsList[0].status).toBe('DELETED');
    expect(component.currentCopy).toBe(1);  // moved on

    component.restorePdf();
    req = http.expectOne('/api/matricule/status/update');
    expect((req.request.body as FormData).get('document_index')).toBe('1');
    expect((req.request.body as FormData).get('status')).toBe('TO VALIDATE');
    req.flush({ response: 'OK' });
    await settle();
    expect(component.pdfDeleted).toBeFalse();
  });

  it('finalising asks for confirmation while copies remain to validate', async () => {
    await create();
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(true) } as any);
    await component.validateMatricules();
    expect(dialog.open).toHaveBeenCalledWith(WarningDialogComponent, jasmine.any(Object));
    await settle();
    expect(validation.validateJob).toHaveBeenCalledWith('job', false);
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('finalisation'), 'Alerte!');
  });

  it('finalising goes straight through when every copy is validated', async () => {
    await create();
    component.examsList.forEach(e => { if (e.status === 'TO VALIDATE') { e.status = 'VALIDATED'; } });
    spyOn(dialog, 'open');
    await component.validateMatricules();
    expect(dialog.open).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('validés'), 'Alerte!');
  });

  it('the arrow keys move between copies', async () => {
    await create();
    spyOn(component, 'nextCopy');
    spyOn(component, 'previousCopy');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    expect(component.nextCopy).toHaveBeenCalled();
    expect(component.previousCopy).toHaveBeenCalled();
  });

  it('the back arrow returns to the dashboard, with the share token for visitors', async () => {
    await create();
    component.reroute();
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard', 'job']);
    component.shareAll = true;
    component.reroute();
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard'], { queryParams: { job_id: 'job', token: 'share-1' } });
  });

  it('releases the pdfs and the socket when destroyed', async () => {
    await create();
    fixture.destroy();
    expect(docs.clearPdfSources).toHaveBeenCalled();
    expect(socket.disconnectSocket).toHaveBeenCalled();
  });
});

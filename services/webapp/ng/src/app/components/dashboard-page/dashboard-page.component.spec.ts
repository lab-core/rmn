import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { NgSelectModule } from '@ng-select/ng-select';
import { of } from 'rxjs';

import { DashboardPageComponent } from './dashboard-page.component';
import { CsvUpdateDialogComponent } from '../csv-update/csv-update-dialog.component';
import { TaskRetryDialogComponent } from '../task-retry-dialog/task-retry-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { ValidationService } from 'src/app/services/validation.service';
import {
  MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, routeStub, settle, socketServiceStub, userServiceStub,
} from '../../testing/helpers';

const TASK = {
  job_id: 'job', job_name: 'Exam', job_status: 'VALIDATION', statistics_for_students: true,
  n_pages_per_question: [['Q1', 2], ['Q2', 0], ['Q3', 1]],
  n_max_points_per_question: [['Q1', 10], ['Q2', 0], ['Q3', 5]],
  bonus_enabled_map: [['Q1', false], ['Q2', false], ['Q3', true]],
  students_list: [
    { matricule: '1234567', 'Nom complet': 'Alice A' },
    { matricule: '2345678', 'Nom complet': 'Bob B' },
  ],
};
const EXAMS = [
  { document_index: 0, matricule: '1234567', status: 'VALIDATED', filename: 'a' },
  { document_index: 1, matricule: '2345678', status: 'TO VALIDATE', filename: 'b' },
];
const QUESTIONS = [
  { document_index: 0, question: 'Q1', status: 'VALIDATED', grade: 8, basename: 'a' },
  { document_index: 1, question: 'Q1', status: 'TO VALIDATE', basename: 'b' },
  { document_index: 0, question: 'Q3', status: 'VALIDATED', grade: 5, basename: 'a' },
  { document_index: 1, question: 'Q3', status: 'VALIDATED', grade: 3, basename: 'b' },
];

class DocumentsStub {
  documentsList: any[] = [];
  exams = JSON.parse(JSON.stringify(EXAMS));
  questions = JSON.parse(JSON.stringify(QUESTIONS));
  async getDocuments(jobId: string, questions: boolean, indices?: number[]) {
    const source = questions ? this.questions : this.exams;
    this.documentsList = indices ? source.filter(d => indices.includes(d.document_index)) : source;
  }
}

describe('DashboardPageComponent', () => {
  let fixture: ComponentFixture<DashboardPageComponent>;
  let component: DashboardPageComponent;
  let http: HttpTestingController;
  let router: Router;
  let dialog: MatDialog;
  let notification: jasmine.SpyObj<NotificationService>;
  let socket: any;
  let tasks: any;
  let docs: DocumentsStub;
  let validation: any;
  let user: any;

  const create = async (task: any = TASK, params: any = { taskId: 'job' }, queryParams: any = {}) => {
    localStorage.clear();
    notification = notificationSpy();
    socket = socketServiceStub();
    docs = new DocumentsStub();
    user = userServiceStub();
    validation = { validateJob: jasmine.createSpy('validateJob').and.resolveTo('OK') };
    tasks = {
      getTaskById: jasmine.createSpy('getTaskById').and.callFake(async () => JSON.parse(JSON.stringify(task))),
      updateTaskStats: jasmine.createSpy('updateTaskStats').and.resolveTo(undefined),
      updateTaskBonus: jasmine.createSpy('updateTaskBonus').and.resolveTo(undefined),
      updateTaskStatus: jasmine.createSpy('updateTaskStatus').and.resolveTo(undefined),
      setvalidatingTaskId: jasmine.createSpy('setvalidatingTaskId'),
      getvalidatingTaskId: () => 'job',
    };
    TestBed.configureTestingModule({
      declarations: [DashboardPageComponent, MainMenuStubComponent],
      imports: [...MATERIAL_MODULES, NgSelectModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub(queryParams, params) },
        { provide: NotificationService, useValue: notification },
        { provide: SocketService, useValue: socket },
        { provide: TasksService, useValue: tasks },
        { provide: DocumentsService, useValue: docs },
        { provide: ValidationService, useValue: validation },
        { provide: UserService, useValue: user },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    dialog = TestBed.inject(MatDialog);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(DashboardPageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await settle();
    fixture.detectChanges();
  };

  afterEach(() => http.verify());

  it('loads the task and computes the per-question statistics', async () => {
    await create();
    expect(component.taskName).toBe('Exam');
    expect(component.examsCount).toBe(2);
    expect(component.totalVerifiedMatricules).toBe(1);
    expect(socket.join).toHaveBeenCalledWith('job');

    // Q2 is ignored (0 page): not shown, but the bonus map keeps its slot
    expect(component.questions.map(q => q.name)).toEqual(['Q1', 'Q3', 'Total']);
    const [q1, q3, total] = component.questions;
    expect([q1.count, q1.validatedCount, q1.average, q1.max, q1.bonus]).toEqual([2, 1, 8, 10, false]);
    expect([q3.count, q3.validatedCount, q3.average, q3.stdDev, q3.bonus]).toEqual([2, 2, 4, 1, true]);
    expect(q3.histogram.map(b => b.count)).toEqual([0, 0, 0, 1, 0, 1]);
    expect(component.getMaxCount(q3)).toBe(1);
    // the total excludes the bonus question from its maximum and only counts fully corrected copies
    expect([total.max, total.validatedCount, total.grades, total.average]).toEqual([10, 1, [13], 13]);
    expect(component.ongoingTask).toBeTrue();

    const rows = Array.from(fixture.nativeElement.querySelectorAll('tbody tr')).map((r: HTMLElement) => r.querySelector('td').textContent.trim());
    expect(rows).toEqual(['Q1', 'Q3', 'Total', 'Matricules']);
    const finalize = fixture.nativeElement.querySelector('.validate-job-button') as HTMLButtonElement;
    expect(finalize.disabled).toBeTrue();
  });

  it('builds the copy picker from the student list and points the correction pages at the pick', async () => {
    await create();
    expect(component.copiesList).toEqual([
      { identifiant: '1234567 - Alice A', index: 0, basename: 'a', copy: 0 },
      { identifiant: '2345678 - Bob B', index: 1, basename: 'b', copy: 1 },
    ]);
    expect(component.copySelection).toBeNull();

    component.copySelection = component.copiesList[1];
    component.selectCopy();
    // the copy's identity, not a position: the pages order their lists differently
    expect(JSON.parse(localStorage.getItem('job_dashboard_copy'))).toEqual({ document_index: 1, basename: 'b' });
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('copie 2'), 'Copie sélectionnée');

    // the pick survives a reload of the dashboard
    component.getCopiesList();
    expect(component.copySelection).toBe(component.copiesList[1]);
  });

  it('a student without a recognised copy is N/A and cannot be selected', async () => {
    await create();
    component.task.students_list.push({ matricule: '3456789', 'Nom complet': 'Carl C' });
    component.getCopiesList();
    const carl = component.copiesList[2];
    expect(carl.copy).toBeUndefined();
    component.copySelection = carl;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.select-index-container p:last-of-type').textContent.trim()).toBe('N/A');
    expect((fixture.nativeElement.querySelector('.select-index-button') as HTMLButtonElement).disabled).toBeTrue();
    component.selectCopy();
    expect(localStorage.getItem('job_dashboard_copy')).toBeNull();
  });

  it('question helpers read the task definition', async () => {
    await create();
    expect(component.isQuestionIgnored('Q2')).toBeTrue();
    expect(component.isQuestionIgnored('Q1')).toBeFalse();
    expect(component.getQuestionMax('Q3')).toBe(5);
    expect(component.isQuestionBonus('Q3')).toBeTrue();
    expect(component.isQuestionBonus('Q1')).toBeFalse();
  });

  it('toggling a bonus moves its points out of the total and saves the map', async () => {
    await create();
    const q1 = component.questions[0];
    q1.bonus = true;
    component.questionBonusChange(q1);
    expect(component.getTotalQuestion().max).toBe(0);
    expect(component.task.bonus_enabled_map[0]).toEqual(['Q1', true]);
    expect(tasks.updateTaskBonus).toHaveBeenCalledWith('job', component.task.bonus_enabled_map);

    component.taskStats = false;
    component.taskStatsChange();
    expect(tasks.updateTaskStats).toHaveBeenCalledWith('job', false);
  });

  it('archived tasks are read-only and inaccessible ones bounce back', async () => {
    await create({ ...TASK, job_status: 'ARCHIVED' });
    expect(component.taskName).toBe('Exam (Archivée)');
    expect(component.disableButtons).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('Restaurer');

    await component.restore();
    expect(tasks.updateTaskStatus).toHaveBeenCalledWith('job', 'VALIDATION');
    expect(component.taskName).toBe('Exam');
    expect(component.disableButtons).toBeFalse();

    component.task.job_status = 'ERROR';
    component.updateViewOnStatus();
    expect(notification.showWarning).toHaveBeenCalledWith("La tâche n'est pas accessible.", 'Attention');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
  });

  it('without a task id it returns to the history', async () => {
    await create(TASK, {});
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    expect(tasks.getTaskById).not.toHaveBeenCalled();
  });

  it('refuses to finalise until every matricule and copy is validated', async () => {
    await create();
    await component.validateJob();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('matricules'), 'Erreur!');
    expect(validation.validateJob).not.toHaveBeenCalled();

    component.totalVerifiedMatricules = 2;
    await component.validateJob();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('corriger toutes les copies'), 'Erreur!');

    spyOn(PDFSource, 'clearAll');
    component.getTotalQuestion().validatedCount = 2;
    await component.validateJob();
    expect(validation.validateJob).toHaveBeenCalledWith('job', false);
    expect(component.disableButtons).toBeTrue();
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('finalisation'), 'Alerte!');
    expect(PDFSource.clearAll).toHaveBeenCalledWith('job', 4);
  });

  it('navigates to the correction of a question, of the whole task and of the matricules', async () => {
    await create();
    component.correctQuestion(component.questions[1]);  // Q3 keeps its own number
    expect(router.navigate).toHaveBeenCalledWith(['/task-validation', 'job', 3]);
    component.correctQuestion(component.getTotalQuestion());
    expect(router.navigate).toHaveBeenCalledWith(['/task-validation', 'job']);
    component.verifyMatricules();
    expect(router.navigate).toHaveBeenCalledWith(['/matricule-validation', 'job']);
    expect(tasks.setvalidatingTaskId).toHaveBeenCalledWith('job');
  });

  it('a share-link visitor navigates with the token in the query string', async () => {
    await create();
    user.shared = () => true;
    component.correctQuestion(component.questions[0]);
    expect(router.navigate).toHaveBeenCalledWith(['/task-validation'], {
      queryParams: { job_id: 'job', all: true, question_index: 1, token: 'share-1' },
    });
    component.verifyMatricules();
    expect(router.navigate).toHaveBeenCalledWith(['/matricule-validation'], {
      queryParams: { job_id: 'job', all: true, token: 'share-1' },
    });
  });

  it('opens the sharing, csv and extra-copies dialogs', async () => {
    await create();
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of({ success: true, message: 'Le lien a été copié' }) } as any);

    component.shareQuestion(2);
    expect(dialog.open).toHaveBeenCalledWith(TaskShareDialogComponent, jasmine.objectContaining({
      data: { taskId: 'job', taskName: 'Exam', shareType: 'job', questionIndex: 3 },
    }));
    expect(notification.showSuccess).toHaveBeenCalledWith('Le lien a été copié', 'Succès!');

    component.shareMatricule();
    expect(dialog.open).toHaveBeenCalledWith(TaskShareDialogComponent, jasmine.objectContaining({
      data: { taskId: 'job', taskName: 'Exam', shareType: 'matricule' },
    }));

    component.updateCsv();
    expect(dialog.open).toHaveBeenCalledWith(CsvUpdateDialogComponent, jasmine.objectContaining({ data: { jobId: 'job' } }));

    (dialog.open as jasmine.Spy).and.returnValue({ afterClosed: () => of(false) } as any);
    component.addCopies();
    expect(dialog.open).toHaveBeenCalledWith(TaskRetryDialogComponent, jasmine.any(Object));
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('nouvelles copies'), 'Erreur!');
  });

  it('a validated matricule pushed over the socket refreshes the counters', async () => {
    await create();
    docs.exams[1].status = 'VALIDATED';
    await socket.socket.fire('doc_validated', JSON.stringify({ matricule: true, questions: false, document_index: 1 }));
    await settle();
    expect(component.examsList[1].status).toBe('VALIDATED');
    expect(component.totalVerifiedMatricules).toBe(2);
  });

  it('a socket update lands on the row with that document index, wherever it sits', async () => {
    await create();
    // positions no longer equal document indices (the stub shares this array,
    // so look the fixture row up by index rather than by position)
    component.examsList.reverse();
    docs.exams.find((e: any) => e.document_index === 1).status = 'VALIDATED';
    await socket.socket.fire('doc_validated', JSON.stringify({ matricule: true, questions: false, document_index: 1 }));
    await settle();
    expect(component.examsList.length).toBe(2);
    expect(component.examsList.find(e => e.document_index === 1).status).toBe('VALIDATED');
    expect(component.examsList.find(e => e.document_index === 0).filename).toBe('a');
    expect(component.totalVerifiedMatricules).toBe(2);
  });

  it('a status change pushed over the socket notifies and reloads the task', async () => {
    await create();
    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'job', status: 'RUN', job_infos: '2 copies ajoutées' }));
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('RUN'), 'Alerte!');
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('2 copies ajoutées'), 'Infos');
    expect(tasks.getTaskById).toHaveBeenCalledTimes(2);
  });

  it('leaves the room and drops its listeners when destroyed', async () => {
    await create();
    fixture.destroy();
    expect(socket.socket.handlers['doc_validated']).toBeUndefined();
    expect(socket.leave).toHaveBeenCalledWith('job');
  });

  it('the histogram copes with a zero maximum and out-of-range grades', async () => {
    await create();
    const stats = (question: any): any => ({ name: 'Q1', index: 0, bonus: false, count: 0, validatedCount: 0,
      total: 0, average: 0, stdDev: 0, histogram: [], validatedFilenames: new Set<string>(), ...question });
    // max 0 gave NaN bins and threw inside the socket handler
    const zero = component['computeHistogram'](stats({ grades: [0, 0], max: 0 }));
    expect(zero.length).toBe(1);
    expect(zero[0]).toEqual({ value: 0, count: 2 });
    // a negative grade indexed bins[-1]
    // max grade 12 over 10 bins: a bin every 2 points, 7 bins from 0 to 12
    const bins = component['computeHistogram'](stats({ grades: [-1, 3, 12], max: 10 }));
    expect(bins.map(b => b.value)).toEqual([0, 2, 4, 6, 8, 10, 12]);
    expect(bins.map(b => b.count)).toEqual([1, 1, 0, 0, 0, 0, 1]);
  });

  it('toggling the bonus of a single-question task does not add its max to itself', async () => {
    await create({ ...TASK, n_max_points_per_question: [['Q1', 10]], bonus_enabled_map: [['Q1', false]], n_pages_per_question: [['Q1', 2]] });
    await settle();
    expect(component.questions.length).toBe(1);
    const q1 = component.questions[0];
    q1.bonus = true;
    component.questionBonusChange(q1);
    expect(q1.max).toBe(10);
    expect(component.task.bonus_enabled_map).toEqual([['Q1', true]]);
  });
});

describe('DashboardPageComponent reading progress', () => {
  // The executor reports every few copies while it reads the grades. That is
  // worth showing on the page and not worth a toast each time.
  let component: DashboardPageComponent;

  beforeEach(() => {
    component = Object.create(DashboardPageComponent.prototype) as DashboardPageComponent;
  });

  it('recognises a progress report by its percentage', () => {
    expect(component.isProgress('Lecture des notes de Q1 : 40/57 (70 %)')).toBeTrue();
  });

  it('does not mistake a real message for progress', () => {
    expect(component.isProgress('Échec de la finalisation : pdflatex failed')).toBeFalse();
    expect(component.isProgress('')).toBeFalse();
  });
});

describe('DashboardPageComponent per-question reading state', () => {
  let component: DashboardPageComponent;

  beforeEach(() => {
    component = Object.create(DashboardPageComponent.prototype) as DashboardPageComponent;
  });

  it('says a question is being read, and how far', () => {
    component.autoGradeProgress = {'3': {pending: 2, running: 1, done: 7, graded: 0, total: 10}};
    expect(component.readingState({name: 'Q3', index: 2})).toContain('en cours');
    expect(component.readingState({name: 'Q3', index: 2})).toContain('70 %');
    expect(component.readingClass({name: 'Q3', index: 2})).toBe('reading-running');
  });

  it('matches the row to its own question, not the one before it', () => {
    // the rows are 0-based and the reading is keyed by question number: Q1
    // showed nothing and every other row showed its predecessor's state
    component.autoGradeProgress = {
      '1': {pending: 0, running: 0, done: 4, graded: 0, total: 4},
      '2': {pending: 3, running: 0, done: 0, graded: 0, total: 3},
    };
    expect(component.readingState({name: 'Q1', index: 0})).toContain('4/4');
    expect(component.readingClass({name: 'Q1', index: 0})).toBe('reading-done');
    expect(component.readingState({name: 'Q2', index: 1})).toContain('à faire');
  });

  it('says nothing on the total row', () => {
    component.autoGradeProgress = {'1': {pending: 0, running: 0, done: 4, graded: 0, total: 4}};
    expect(component.readingState({name: 'Total', index: 5})).toBe('');
  });

  it('says a question is still waiting to be read', () => {
    component.autoGradeProgress = {'3': {pending: 4, running: 0, done: 0, graded: 0, total: 4}};
    expect(component.readingState({name: 'Q3', index: 2})).toContain('à faire');
    expect(component.readingClass({name: 'Q3', index: 2})).toBe('reading-waiting');
  });

  it('says a question has been read', () => {
    component.autoGradeProgress = {'3': {pending: 0, running: 0, done: 9, graded: 0, total: 9}};
    expect(component.readingState({name: 'Q3', index: 2})).toContain('9/9');
    expect(component.readingClass({name: 'Q3', index: 2})).toBe('reading-done');
  });

  it('says nothing about a question no reading has touched', () => {
    component.autoGradeProgress = {};
    expect(component.readingState({name: 'Q3', index: 2})).toBe('');
    expect(component.readingClass({name: 'Q3', index: 2})).toBe('');
  });
});

describe('DashboardPageComponent copies already graded', () => {
  let component: DashboardPageComponent;

  beforeEach(() => {
    component = Object.create(DashboardPageComponent.prototype) as DashboardPageComponent;
  });

  it('counts out the copies it was never given, rather than shrinking the total', () => {
    // 17 copies, one already graded by hand: reporting "16/16" read as if the
    // question only had sixteen
    component.autoGradeProgress = {
      '1': {pending: 0, running: 0, done: 16, graded: 1, total: 17},
    };
    const state = component.readingState({name: 'Q1', index: 0});
    expect(state).toContain('16/16');
    expect(state).toContain('1 déjà notée');
  });

  it('pluralises when several were graded by hand', () => {
    component.autoGradeProgress = {
      '2': {pending: 0, running: 0, done: 15, graded: 2, total: 17},
    };
    expect(component.readingState({name: 'Q2', index: 1})).toContain('2 déjà notées');
  });
});

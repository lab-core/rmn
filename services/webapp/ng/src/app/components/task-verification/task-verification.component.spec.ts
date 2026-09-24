import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { TaskVerificationComponent } from './task-verification.component';
import { DocumentStatus } from 'src/app/generated/rmn-contracts';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { db } from 'src/app/services/offline-db';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { ValidationService } from 'src/app/services/validation.service';
import {
  MATERIAL_MODULES, PdfViewerStubComponent, notificationSpy, routeStub, settle, socketServiceStub, userServiceStub, waitUntil,
} from '../../testing/helpers';

const JOB = {
  job_id: 'job', job_name: 'Exam', job_status: 'VALIDATION',
  n_pages_per_question: [['Q1', 2], ['Q2', 0], ['Q3', 1]],
  n_max_points_per_question: [['Q1', 10], ['Q2', 0], ['Q3', 5]],
  bonus_enabled_map: [['Q1', false], ['Q2', false], ['Q3', true]],
};
// as returned by the server: grouped by question, not by copy
const QUESTION_DOCS = [
  { document_index: 10, basename: 'a', question: 'Q1', status: 'TO VALIDATE', filename: 'a_Q1', grade: null },
  { document_index: 11, basename: 'b', question: 'Q1', status: 'VALIDATED', filename: 'b_Q1', grade: 7 },
  { document_index: 12, basename: 'a', question: 'Q3', status: 'TO VALIDATE', filename: 'a_Q3', grade: null },
  { document_index: 13, basename: 'b', question: 'Q3', status: 'TO VALIDATE', filename: 'b_Q3', grade: null, tag: '1' },
];

describe('TaskVerificationComponent', () => {
  let fixture: ComponentFixture<TaskVerificationComponent>;
  let component: TaskVerificationComponent;
  let http: HttpTestingController;
  let router: Router;
  let notification: jasmine.SpyObj<NotificationService>;
  let socket: any;
  let docs: any;
  let validation: any;
  let tasks: any;

  const create = async (job: any = JOB, queryParams: any = {}, params: any = {},
                        docList: any[] = QUESTION_DOCS, before: () => void = () => {}) => {
    localStorage.clear();
    notification = notificationSpy();
    socket = socketServiceStub();
    validation = {
      validateDocument: jasmine.createSpy('validateDocument').and.resolveTo('OK'),
      validateJob: jasmine.createSpy('validateJob').and.resolveTo('OK'),
    };
    docs = {
      documentsList: [],
      getDocuments: jasmine.createSpy('getDocuments').and.callFake(async () => {
        docs.documentsList = docs.documentsList.length ? docs.documentsList : JSON.parse(JSON.stringify(docList));
      }),
      getPdfSource: jasmine.createSpy('getPdfSource').and.callFake(async (jobId, index) => {
        const source = new PDFSource(index, `blob:${index}`, 0);
        source.setLastVersion(0);
        return source;
      }),
      getAvailablePdfSource: jasmine.createSpy('getAvailablePdfSource'),
      clearPdfSources: jasmine.createSpy('clearPdfSources'),
    };
    tasks = {
      setvalidatingTaskId: jasmine.createSpy('setvalidatingTaskId'),
      getvalidatingTaskId: () => 'job',
      getTask: jasmine.createSpy('getTask').and.resolveTo(JSON.parse(JSON.stringify(job))),
    };
    TestBed.configureTestingModule({
      declarations: [TaskVerificationComponent, PdfViewerStubComponent],
      imports: MATERIAL_MODULES,
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
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(console, 'log');
    spyOn(console, 'error');
    before();
    fixture = TestBed.createComponent(TaskVerificationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    // ngOnInit ends after an IndexedDB round trip and the first copy is opened,
    // or right after the redirect of an unusable task
    await waitUntil(() => component.currentQuestionIndex !== undefined || (router.navigate as jasmine.Spy).calls.count() > 0);
    await settle();
    fixture.detectChanges();
  };

  afterEach(() => http.verify());

  it('an inactive task sends the user back to the history', async () => {
    await create({ ...JOB, job_status: 'ARCHIVED' });
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Tâche inactive');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    // and the initialisation stops there (it used to go on and throw on the job)
    expect(component.examsList || []).toEqual([]);  // never loaded
    expect(console.error).not.toHaveBeenCalled();
    expect(socket.join).not.toHaveBeenCalled();
  });

  it('orders the copies by student, lists the corrected questions and opens the first copy', async () => {
    await create();
    expect(component.examsList.map(e => e.filename)).toEqual(['a_Q1', 'a_Q3', 'b_Q1', 'b_Q3']);
    expect(component.questionIndexes).toEqual(['Tout sélectionner', '1', '3']);  // Q2 is ignored
    // labels by document index, so a filtered tile list still shows its own copy's label
    expect(component.formattedIndexes).toEqual({ 10: '1|Q1', 11: '2|Q1', 12: '1|Q3', 13: '2|Q3' });
    expect(component.nMaxPointsPerQuestion.get('Q3')).toBe(5);
    expect(component.bonusEnabledMap.get('Q3')).toBeTrue();

    expect(component.currentCopy).toBe(0);
    expect(component.currentDocumentIndex).toBe(10);
    expect(component.currentQuestionIndex).toBe('Q1');
    expect(component.pdfUrl).toBe('blob:10');
    expect(component.currentVersion).toBe(0);
    expect(component.colorChosen).toBe('red');
    expect(component.disabledValidationButton).toBeTrue();  // some copies are not validated
    expect(socket.join).toHaveBeenCalledWith('job');
    expect(socket.join).toHaveBeenCalledWith('alice');
    expect(fixture.nativeElement.querySelectorAll('.file-container').length).toBe(4);
    expect(fixture.nativeElement.querySelector('.pdf-stub').textContent).toBe('blob:10');
  });

  it('opens on the copy picked on the dashboard and keeps that student across questions', async () => {
    await create();
    // the dashboard stores the copy's identity (whole-copy index + file name)
    localStorage.setItem('job_dashboard_copy', JSON.stringify({ document_index: 1, basename: 'b' }));
    localStorage.setItem('job_copy', '0');  // the resume pointer loses
    component.currentCopy = -1;
    await component.getDocuments();
    expect(component.currentCopy).toBe(2);  // b_Q1
    expect(component.currentDocumentIndex).toBe(11);

    component.onQuestionIndexChange({ value: '3' } as any);
    await settle();
    expect(component.currentDocumentIndex).toBe(13);  // b_Q3

    // a pick with no document in this task falls back to the resume pointer
    localStorage.setItem('job_dashboard_copy', JSON.stringify({ document_index: 99, basename: 'zzz' }));
    localStorage.setItem('job_copy', '1');
    component.currentCopy = -1;
    await component.getDocuments();
    expect(component.currentCopy).toBe(1);
  });

  it('picking a question narrows the list and follows the same student', async () => {
    await create();
    component.onQuestionIndexChange({ value: '3' } as any);
    await settle();
    expect(component.subExamsList.map(e => e.filename)).toEqual(['a_Q3', 'b_Q3']);
    expect(component.formattedIndexes).toEqual({ 12: '1', 13: '2' });
    expect(component.currentCopy).toBe(1);  // a's Q3
    expect(component.currentQuestionIndex).toBe('Q3');
    expect(component.nextCopyIndex()).toBe(3);
    expect(component.previousCopyIndex(3)).toBe(1);

    component.onQuestionIndexChange({ value: 'Tout sélectionner' } as any);
    await settle();
    expect(component.subExamsList.length).toBe(4);
    expect(component.currentSubCopy()).toBe(component.currentCopy);
  });

  it('a question given in the route selects it and locks the picker for visitors', async () => {
    await create(JOB, { question_index: '1' });
    expect(component.index).toBe('1');
    expect(component.subExamsList.map(e => e.filename)).toEqual(['a_Q1', 'b_Q1']);
    expect(component.disabledDropDown).toBeFalse();  // logged in
  });

  it('the validate button of a shared question counts that question only, not Q10 for Q1', async () => {
    await create(JOB, { question_index: '1' });
    component.disabledDropDown = true;  // a share-link visitor locked on Q1
    component.examsList.push({ document_index: 20, basename: 'a', question: 'Q10', status: 'TO VALIDATE', filename: 'a_Q10' });
    component.examsList.forEach(e => { if (e.question === 'Q1') { e.status = 'VALIDATED'; } });

    component.checkValidationButton();

    expect(component.disabledValidationButton).toBeFalse();
  });

  it('colours the copies by status and tag', async () => {
    await create();
    expect(component.getExamClass({ status: 'VALIDATED', document_index: 99 })).toBe('validated-copy');
    expect(component.getExamClass({ status: 'TO VALIDATE', tag: '1', document_index: 99 })).toBe('to-validate-copy tag-color-1');
    expect(component.getExamClass({ status: 'HIGH ACCURACY', document_index: 10 })).toBe('high-precision-copy chosen-copy');
    expect(component.getExamClass({ status: 'DELETED', document_index: 99 })).toBe('deleted-copy');
    component.setChosenColor('TO VALIDATE', '2');
    expect(component.colorChosen).toBe('tag-color-2');
    component.setChosenColor('VALIDATED', undefined);
    expect(component.colorChosen).toBe('green');
  });

  it('shades a copy read by the machine by its confidence, between the red and the blue', async () => {
    await create();
    const read = { status: 'HIGH ACCURACY', grade: null, auto_grade: 8, auto_grade_confidence: 1, document_index: 99 };
    expect(component.tileColour(read)).toBe('rgb(65, 65, 247)');
    expect(component.tileTitle(read)).toBe('confiance 100 %');
    expect(component.tileColour({ ...read, status: 'TO VALIDATE', auto_grade_confidence: 0 })).toBe('rgb(255, 0, 0)');
    // graded by the teacher, tagged by the teacher, or never read: the usual colours
    expect(component.tileColour({ ...read, grade: 8 })).toBeNull();
    expect(component.tileColour({ ...read, status: 'TO VALIDATE', tag: '1' })).toBeNull();
    expect(component.tileColour({ ...read, auto_grade_confidence: undefined })).toBeNull();
  });

  it('a copy the reader just read is patched in place, without refetching', async () => {
    await create();
    const current = component.currentExam();
    current.question_index = 1;
    docs.getDocuments.calls.reset();

    await socket.socket.fire('document_ready', JSON.stringify({
      job_id: 'job', questions: true, question_index: 1, document_index: current.document_index,
      auto_grade: 6, auto_grade_confidence: 0.95, auto_grade_reason: 'ok', auto_grade_source: 'ink',
      status: 'HIGH ACCURACY',
    }));

    expect(docs.getDocuments).not.toHaveBeenCalled();
    expect(current.status).toBe('HIGH ACCURACY');
    expect(current.auto_grade_confidence).toBe(0.95);
    // the open copy shows the suggestion at once, framed in its colour
    expect(component.currentGrade).toBe(6);
    expect(component.currentGradeIsAuto).toBeTrue();
    expect(component.scoreBorderColour()).toBe('rgb(75, 62, 235)');
  });

  it('a live reading never replaces a grade being typed, nor touches a validated copy', async () => {
    await create();
    const current = component.currentExam();
    current.question_index = 1;
    component.currentGrade = 4;  // typed, not saved yet
    component.currentGradeIsAuto = false;
    const validated = component.examsList.find(e => e.status === 'VALIDATED');
    validated.question_index = 1;

    for (const exam of [current, validated]) {
      await socket.socket.fire('document_ready', JSON.stringify({
        job_id: 'job', questions: true, question_index: 1, document_index: exam.document_index,
        auto_grade: 9, auto_grade_confidence: 0.5, auto_grade_reason: 'ok', auto_grade_source: 'ink',
      }));
    }

    expect(component.currentGrade).toBe(4);
    expect(current.auto_grade).toBe(9);
    expect(validated.auto_grade).toBeUndefined();
    expect(validated.grade).toBe(7);
  });

  it('the event that ends a reading pass still refetches every copy', async () => {
    await create();
    docs.getDocuments.calls.reset();
    await socket.socket.fire('document_ready', JSON.stringify({ job_id: 'job', questions: true }));
    expect(docs.getDocuments).toHaveBeenCalled();
  });

  it('the tag filter decides which copies the hidden-sidebar flow visits', async () => {
    await create();
    expect(component.isRespectingTagFilter({ status: 'VALIDATED' })).toBeTrue();
    component.tagFilter = '1';
    expect(component.isRespectingTagFilter({ status: 'TO VALIDATE', tag: '1' })).toBeTrue();
    expect(component.isRespectingTagFilter({ status: 'TO VALIDATE', tag: '2' })).toBeFalse();
    expect(component.isRespectingTagFilter({ status: 'VALIDATED' })).toBeFalse();
    component.tagFilter = '0';
    expect(component.isRespectingTagFilter({ status: 'TO VALIDATE' })).toBeTrue();
    component.tagFilter = 'VALIDATED';
    expect(component.isRespectingTagFilter({ status: 'VALIDATED' })).toBeTrue();
    component.tagFilter = '1';
    expect(component.nextCopyIndexTagFilter(-1)).toBe(3);  // b_Q3 carries tag 1
  });

  it('grades are checked before they are kept', async () => {
    await create();
    component.currentGrade = null;
    expect(component.addGradeToQuestion(false)).toBeFalse();
    expect(() => component.addGradeToQuestion(true)).toThrowError('Note invalide');

    component.currentGrade = -1;
    expect(() => component.addGradeToQuestion(true)).toThrowError('Note invalide');

    component.currentGrade = 12;  // above the 10 points of Q1
    expect(component.addGradeToQuestion(true)).toBeTrue();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('2 point(s) bonus'), 'Attention!');
    expect(component.currentExam().grade).toBe(12);
    expect(component.saveCurrentGrade()).toBeFalse();  // unchanged now
  });

  it('sums the per-question grades', async () => {
    await create();
    component.currentGrades = {} as any;
    component.updateTotal('Q1', 3);
    component.updateTotal('Q3', 4.5);
    expect(component.currentTotal).toBe(7.5);
  });

  it('validating a copy stores the grade and status and moves on', async () => {
    await create();
    component.currentGrade = 8;
    await component.validateCurrentCopy();
    await settle();
    expect(component.examsList[0].status).toBe('VALIDATED');
    expect(component.examsList[0].grade).toBe(8);
    expect(component.currentCopy).toBe(1);
    expect(component.currentQuestionIndex).toBe('Q3');
    // Q3 is a bonus question: its grade starts at 0
    expect(component.currentGrade).toBe(0);
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('bonus'), 'Information');
  });

  it('a refused grade leaves the copy to validate, not VALIDATED without a grade', async () => {
    await create();
    component.currentGrade = null;
    await component.validateCurrentCopy();
    await settle();
    expect(notification.showWarning).toHaveBeenCalledWith('Veuillez saisir une note.', 'Note invalide');
    // the status was set to VALIDATED before the grade check and stayed so:
    // clicking another copy then saved VALIDATED with grade undefined
    expect(component.currentStatus).toBe('TO VALIDATE');
    expect(component.examsList[0].status).toBe('TO VALIDATE');
    expect(component.currentGradeModified).toBeFalse();
    expect(component.currentCopy).toBe(0);
  });

  it('offline copies are matched by document index, not by position in the sorted list', async () => {
    await create();
    const saveCopy = spyOn(component, 'saveCopy').and.resolveTo(true);
    // document_index 12 is a_Q3, which sits at position 1 once the list is sorted by student
    const pdfSrc = new PDFSource(12, 'blob:12', 0);
    component.offlineCopies.set(12, {
      pdfSrc, file64: 'data:application/pdf;base64,JVBERi0xLjQ=', updated: false,
      grade: 3, status: 'VALIDATED', questionIndex: 'Q3',
    } as any);

    await component.uploadOffline(false);

    const file: File = saveCopy.calls.mostRecent().args[1];
    expect(file.name).toBe('a_Q3.pdf');
    expect(saveCopy.calls.mostRecent().args[0]).toBe(pdfSrc);
    expect(notification.showSuccess).toHaveBeenCalled();
  });

  it('skipping a copy tags it and keeps it to validate', async () => {
    await create();
    await component.skipCurrentCopy('2');
    await settle();
    expect(component.examsList[0].tag).toBe('2');
    expect(component.examsList[0].status).toBe('TO VALIDATE');
    expect(component.currentCopy).toBe(1);
  });

  it('the validation button opens once every copy is validated', async () => {
    await create();
    component.examsList.forEach(e => e.status = 'VALIDATED');
    component.checkValidationButton();
    expect(component.disabledValidationButton).toBeFalse();
    expect(component.showFilter()).toBeFalse();
    expect(component.filesListHeight()).toBe('100%');
  });

  it('a socket status change updates the task', async () => {
    await create();
    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'job', status: 'VALIDATED' }));
    expect(component.job.job_status).toBe('VALIDATED');
    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'other', status: 'ERROR' }));
    expect(component.job.job_status).toBe('VALIDATED');
  });

  it('leaving saves nothing when the pdf was not touched and returns to the dashboard', async () => {
    await create();
    await component.reroute();
    expect(validation.validateDocument).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard', 'job']);
    fixture.destroy();
    expect(docs.clearPdfSources).toHaveBeenCalled();
    expect(socket.leave).toHaveBeenCalled();
  });

  const viewer = () => component.pdfViewer as unknown as PdfViewerStubComponent;
  const key = (name: string) => document.dispatchEvent(new KeyboardEvent('keydown', { key: name }));
  const dialogClosingWith = (result: any) => ({ afterClosed: () => of(result) } as any);

  it('a task that cannot be loaded sends the user back to the history', async () => {
    await create(JOB, {}, {}, QUESTION_DOCS, () => tasks.getTask.and.rejectWith(new Error('404')));
    expect(console.error).toHaveBeenCalled();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Tâche indisponible');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    expect(docs.getDocuments).not.toHaveBeenCalled();
  });

  it('a task without any copy sends the user to its dashboard', async () => {
    await create(JOB, { job_id: 'job' }, {}, []);
    expect(tasks.setvalidatingTaskId).toHaveBeenCalledWith('job');
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard', 'job']);
    expect(component.currentCopy).toBe(-1);
  });

  it('a question given in the path selects it', async () => {
    await create(JOB, {}, { index: '3' });
    expect(component.index).toBe('3');
    expect(component.currentQuestionIndex).toBe('Q3');
    expect(component.subExamsList.map(e => e.filename)).toEqual(['a_Q3', 'b_Q3']);
  });

  it('a group in the link narrows the copies to that group, and the filter switches group', async () => {
    const grouped = QUESTION_DOCS.map(d => ({ ...d, group: d.basename === 'a' ? 'G1' : 'G2' }));
    await create(JOB, { group: 'G2' }, {}, grouped);
    expect(component.groupsList).toEqual(['G2']);
    expect(component.subExamsList.map(e => e.filename)).toEqual(['b_Q1', 'b_Q3']);

    component.loadSubExamsList();
    await settle();
    expect(component.currentDocumentIndex).toBe(11);

    component.group = 'G1';
    component.loadSubExamsList();
    await settle();
    expect(component.subExamsList.map(e => e.filename)).toEqual(['a_Q1', 'a_Q3']);
    expect(component.currentDocumentIndex).toBe(10);
  });

  it('a link shared for the whole task goes back to the shared dashboard', async () => {
    await create(JOB, { all: '1' });
    expect(component.shareAll).toBeTrue();
    await component.reroute();
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard'], { queryParams: { job_id: 'job', token: 'share-1' } });
  });

  it('warns before the page is left while correcting offline', async () => {
    await create();
    const event = { preventDefault: jasmine.createSpy('preventDefault'), returnValue: 'x' } as any;
    component.warnBeforeLeavingOffline(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    component.offline = true;
    component.warnBeforeLeavingOffline(event);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(event.returnValue).toBe('');
  });

  it('the arrow keys move between the copies, four at a time up and down', async () => {
    await create();
    key('ArrowRight');
    await waitUntil(() => component.currentCopy === 1);
    key('ArrowLeft');
    await waitUntil(() => component.currentCopy === 0);
    key('ArrowDown');
    await waitUntil(() => component.currentCopy === 3);  // clamped to the last copy
    key('ArrowUp');
    await waitUntil(() => component.currentCopy === 0);  // clamped to the first
    expect(component.currentDocumentIndex).toBe(10);
  });

  it('the arrow keys leave the copy alone while the score is being typed', async () => {
    await create();
    const score = fixture.nativeElement.querySelector('#score') as HTMLInputElement;
    score.focus();
    const change = spyOn(component, 'changeCurrentExam').and.callThrough();
    key('ArrowRight');
    key('ArrowLeft');
    key('ArrowUp');
    key('ArrowDown');
    await settle();
    expect(change).not.toHaveBeenCalled();
    expect(component.currentCopy).toBe(0);
  });

  it('Enter validates the copy and puts the cursor back in the score', async () => {
    await create();
    component.currentGrade = 9;
    key('Enter');
    await waitUntil(() => component.currentCopy === 1);
    fixture.detectChanges();
    await settle();
    expect(component.examsList[0].grade).toBe(9);
    expect(component.examsList[0].status).toBe('VALIDATED');
    expect(document.activeElement.id).toBe('score');
  });

  it('sends the annotated pdf, grade and status of the copy it leaves', async () => {
    await create();
    const file = new File(['%PDF-1.4'], 'a_Q1.pdf', { type: 'application/pdf' });
    viewer().getRenderedPdfFile.and.resolveTo(file);
    viewer().getAnnotations.and.returnValue([{ annotationType: 3 }]);
    const left = component.currentPdfSrc;
    component.currentGrade = 8;

    await component.validateCurrentCopy();

    expect(viewer().getRenderedPdfFile).toHaveBeenCalledWith('a_Q1.pdf', false);
    expect(validation.validateDocument).toHaveBeenCalledWith(
      'job', 10, file, '1', 8, component.nMaxPointsPerQuestion, 'VALIDATED', 0, [{ annotationType: 3 }], undefined);
    expect(left.lastVersion).toBe(1);
    expect(left.version).toBe(1);
    expect(component.currentCopy).toBe(1);
  });

  it('stays on a copy the server did not accept', async () => {
    await create();
    viewer().getRenderedPdfFile.and.resolveTo(new File(['%PDF'], 'a_Q1.pdf'));
    validation.validateDocument.and.resolveTo('ERROR');
    component.currentGrade = 8;

    await component.validateCurrentCopy();

    expect(notification.showError).toHaveBeenCalledWith('Échec de la sauvegarde du document PDF modifié.', 'Erreur de validation');
    expect(component.currentCopy).toBe(0);
    expect(component.pdfLoading).toBeFalse();
  });

  it('highlights the restore button when the annotated pdf cannot be rendered', async () => {
    await create();
    viewer().getRenderedPdfFile.and.rejectWith(new Error('corrupt'));
    await component.nextCopy();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('corrompu'), 'PDF corrompu');
    expect(component.isRestoreHiglighted).toBe(1);
    expect(component.currentCopy).toBe(0);
  });

  it('restores the latest version of the pdf, dropping the local annotations', async () => {
    await create();
    component.currentPdfSrc.lastVersion = 4;
    component.isRestoreHiglighted = 2;
    docs.getPdfSource.and.resolveTo(new PDFSource(10, 'blob:latest', 4));

    await component.restoreLatestPdf();

    expect(docs.getPdfSource).toHaveBeenCalledWith('job', 10, false, undefined, -1);
    expect(component.pdfUrl).toBe('blob:latest');
    expect(component.currentVersion).toBe(4);
    expect(component.currentPdfSrc.lastVersion).toBe(4);
    expect(component.isRestoreHiglighted).toBe(0);

    docs.getPdfSource.and.resolveTo(undefined);
    await component.restoreLatestPdf();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('dernière version'), 'Erreur de restoration');
    expect(component.pdfLoading).toBeFalse();
  });

  it('opens an older version of the copy and enables the arrows that lead somewhere', async () => {
    await create();
    docs.getPdfSource.and.callFake(async (jobId, index, annotations, version) => {
      const source = new PDFSource(index, `blob:${index}v${version}`, version);
      source.setLastVersion(3);
      return source;
    });

    await component.setNewVersion({ target: { value: 2 } });

    expect(docs.getPdfSource).toHaveBeenCalledWith('job', 10, true, 2);
    expect(component.pdfUrl).toBe('blob:10v2');
    expect(component.currentVersion).toBe(2);
    expect(viewer().renderAnnotations).toHaveBeenCalled();
    component.checkNavigationArrows(true);
    expect([component.disablePrevious, component.disableNext]).toEqual([false, false]);

    await component.loadPdf(3);
    component.checkNavigationArrows(true);
    expect([component.disablePrevious, component.disableNext]).toEqual([false, true]);
    component.offline = true;
    component.checkNavigationArrows(true);
    expect([component.disablePrevious, component.disableNext]).toEqual([true, true]);
  });

  it('shows no pdf when the copy cannot be downloaded', async () => {
    await create();
    docs.getPdfSource.and.resolveTo(undefined);
    expect(await component.loadPdf()).toBeFalse();
    expect(component.pdfUrl).toBeUndefined();
    expect(component.currentPdfSrc).toBeUndefined();
    expect(component.disableNext).toBeTrue();
  });

  it('the hidden sidebar flow jumps to the next copy of the chosen tag', async () => {
    await create();
    component.onTagChange({ value: '1' } as any);
    await settle();
    expect(component.currentCopy).toBe(3);

    component.tagFilter = '';
    component.changeCurrentExam(0);
    await settle();
    component.tagFilter = '1';
    component.toggleSidebar();
    await settle();
    expect(component.isSidebarHidden).toBeTrue();
    expect(component.currentCopy).toBe(3);

    // validating the last copy of the tag shows the sidebar again
    component.currentGrade = 2;
    await component.validateCurrentCopy();
    expect(component.isSidebarHidden).toBeFalse();
    component.toggleSidebar();
    component.toggleSidebar();
    expect(component.isSidebarHidden).toBeFalse();
  });

  it('reminds to send the zip back when the last copy is reached after a download', async () => {
    await create();
    component.hasDownloadedZip = true;
    await component.changeCurrentExam(3);
    component.currentGrade = 1;
    await component.validateCurrentCopy();
    expect(notification.showWarning).toHaveBeenCalledWith("Vous n'avez téléversé aucun nouveaux fichiers.", 'Attention!');
  });

  it('keeps a grade without a check when the question maximum is unknown', async () => {
    await create();
    component.currentQuestionIndex = 'Q9';
    component.currentGrade = 3;
    expect(component.addGradeToQuestion(true)).toBeTrue();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('Maximum de la question inconnu'), 'Attention!');
  });

  it('offline, an unchanged grade is saved again only when the local copy has one', async () => {
    await create();
    component.offline = true;
    component.currentGrade = component.currentExam().grade;
    expect(component.saveCurrentGrade()).toBeFalse();
    component.offlineCopies.set(10, { pdfSrc: component.currentPdfSrc, grade: 4 } as any);
    expect(component.saveCurrentGrade()).toBeTrue();
  });

  it('scrolls the tile list to keep the open copy in the middle', async () => {
    await create();
    const list = fixture.nativeElement.querySelector('#files-list-container') as HTMLElement;
    // a list of 2 tiles per row, 2 rows of 200px, showing 100px
    const size = (el: Element, props: Record<string, number>) => {
      for (const [name, value] of Object.entries(props)) {
        Object.defineProperty(el, name, { value, writable: true, configurable: true });
      }
    };
    size(list, { clientWidth: 200, clientHeight: 100, scrollHeight: 400, scrollTop: 0 });
    size(list.firstElementChild, { clientWidth: 100 });

    component.currentDocumentIndex = 13;  // the last tile, second row
    component.updateScrollPosition();
    expect(list.scrollTop).toBe(350);

    component.currentDocumentIndex = 10;  // first row
    component.updateScrollPosition();
    expect(list.scrollTop).toBe(150);
  });

  it('a reading pass that ends on a validated copy moves on to the next one', async () => {
    await create();
    await component.changeCurrentExam(2);  // b_Q1, validated
    await socket.socket.fire('document_ready', { job_id: 'job' });
    await settle();
    expect(component.currentCopy).toBe(3);
  });

  it('shows what the reader is doing, then its progress on the question', async () => {
    await create();
    await socket.socket.fire('job_status', JSON.stringify({ job_id: 'job', status: 'VALIDATION', job_infos: 'Lecture Q1' }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#reading-info').textContent).toBe('Lecture Q1');

    component.readingInfo = '';
    component.autoGradeProgress = { Q1: { pending: 3, running: 0, done: 2, graded: 0, total: 5 } };
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#reading-state').textContent).toBe('Lecture des notes à faire : 2/5');
    component.autoGradeProgress = { Q1: { pending: 0, running: 1, done: 0, graded: 4, total: 4 } };
    expect(component.readingStateForQuestion()).toBe('Lecture des notes en cours : 100 %');
  });

  it('says a read grade has no confidence when the reader gave none', async () => {
    await create();
    component.currentGradeIsAuto = true;
    component.currentGradeConfidence = null;
    expect(component.autoGradeHint()).toBe('Note lue automatiquement, à confirmer.');
  });

  describe('offline management', () => {
    it('opens the pdf dialog on the copies shown and on every copy of the task', async () => {
      await create();
      const open = spyOn(component.dialog, 'open').and.returnValue(dialogClosingWith({ hasDownloadedZip: true }));
      component.managePdfs();
      const data: any = open.calls.mostRecent().args[1].data;
      expect(data.jobId).toBe('job');
      expect(data.jobName).toBe('Exam');
      expect(data.examsList).toBe(component.subExamsList);
      expect(data.allExamsList).toBe(component.examsList);
      expect(data.nPagesPerQuestion).toEqual(JOB.n_pages_per_question);
      expect(component.hasDownloadedZip).toBeTrue();
      expect(component.hasUploadedZip).toBeFalse();
    });

    it('reloads the open copy once the zip was sent back', async () => {
      await create();
      spyOn(component.dialog, 'open').and.returnValue(dialogClosingWith({ hasUploadedZip: true }));
      docs.getPdfSource.calls.reset();
      component.managePdfs();
      await settle();
      expect(component.hasUploadedZip).toBeTrue();
      expect(docs.clearPdfSources).toHaveBeenCalled();
      expect(docs.getPdfSource).toHaveBeenCalledWith('job', 10, true, undefined);

      // closed without doing anything
      (component.dialog.open as jasmine.Spy).and.returnValue(dialogClosingWith(undefined));
      component.hasUploadedZip = false;
      component.managePdfs();
      expect(component.hasUploadedZip).toBeFalse();
    });

    it('downloads every copy shown for an offline correction', async () => {
      await create();
      const save = spyOn(db, 'saveAllCopies').and.resolveTo();
      await component.correctOffline();
      expect(Array.from(component.offlineCopies.keys()).sort()).toEqual([10, 11, 12, 13]);
      expect(component.subExamsList.every(e => e.offline)).toBeTrue();
      expect(save).toHaveBeenCalledWith(component.offlineCopies);
      expect(notification.showSuccess).toHaveBeenCalledWith('Téléchargement terminé!', 'Success');
      expect(component.downloadingOffline).toBeFalse();
      expect(component.offline).toBeTrue();
    });

    it('a download cancelled half way leaves nothing offline', async () => {
      await create();
      spyOn(db, 'saveAllCopies').and.resolveTo();
      const remove = spyOn(db, 'deleteAllCopies').and.resolveTo();
      const online = spyOn(db, 'markOnline').and.resolveTo();
      let n = 0;
      docs.getPdfSource.and.callFake(async (jobId, index) => {
        if (++n === 2) {
          component.offline = false;  // cancelled while this copy downloads
        }
        return new PDFSource(index, `blob:${index}`, 0);
      });

      await component.correctOffline();

      expect(component.offlineCopies.size).toBe(1);
      expect(remove).toHaveBeenCalled();
      expect(online).toHaveBeenCalled();
      expect(component.subExamsList.some(e => e.offline)).toBeFalse();
      expect(notification.showSuccess).not.toHaveBeenCalled();
    });

    it('saves an offline copy locally instead of sending it', async () => {
      await create();
      const update = spyOn(db, 'updateCopy').and.resolveTo();
      const copy: any = { pdfSrc: component.currentPdfSrc, status: 'TO VALIDATE' };
      component.offline = true;
      component.offlineCopies.set(10, copy);
      docs.getAvailablePdfSource.and.callFake((jobId, index) => new PDFSource(index, `blob:off${index}`, 0));
      viewer().getRenderedPdfFile.and.resolveTo(new File(['%PDF-1.4'], 'a_Q1.pdf', { type: 'application/pdf' }));
      component.currentGrade = 6;
      await component.skipCurrentCopy('1');

      expect(validation.validateDocument).not.toHaveBeenCalled();
      expect(update).toHaveBeenCalledWith(copy);
      expect(copy.file64).toMatch(/^data:application\/pdf;base64,/);
      expect(copy.grade).toBe(6);
      expect(copy.tag).toBe('1');
      expect(copy.status).toBe('TO VALIDATE');
      expect(copy.updated).toBeFalse();
      // the next copy comes from the local store, nothing is prefetched
      expect(component.pdfUrl).toBe('blob:off12');
      expect(docs.getPdfSource).not.toHaveBeenCalledWith('job', 11);
    });

    it('sends the offline work back and finalises it', async () => {
      await create();
      const remove = spyOn(db, 'deleteAllCopies').and.resolveTo();
      spyOn(db, 'markOnline').and.resolveTo();
      component.offline = true;
      const edited: any = { pdfSrc: new PDFSource(12, 'blob:12', 0), file64: 'data:application/pdf;base64,JVBERi0xLjQ=',
                            updated: false, grade: 3, status: 'VALIDATED', questionIndex: '3' };
      const untouched: any = { pdfSrc: new PDFSource(13, 'blob:13', 0), status: 'TO VALIDATE' };
      const gone: any = { pdfSrc: new PDFSource(99, 'blob:99', 0), file64: 'data:,', updated: false };
      component.offlineCopies = new Map([[12, edited], [13, untouched], [99, gone]]);
      component.examsList.forEach(e => e.offline = true);

      await component.uploadOffline(true);

      expect(validation.validateDocument).toHaveBeenCalledTimes(1);
      const args = validation.validateDocument.calls.mostRecent().args;
      expect([args[0], args[1], args[3], args[4], args[6]]).toEqual(['job', 12, '3', 3, 'VALIDATED']);
      expect((args[2] as File).name).toBe('a_Q3.pdf');
      expect(edited.updated).toBeTrue();
      expect(notification.showError).toHaveBeenCalledWith('La copie 99 ne fait plus partie de la tâche.', 'Error');
      expect(notification.showSuccess).toHaveBeenCalledWith('Téléversement terminé!', 'Success');
      expect(remove).toHaveBeenCalled();
      expect(component.offline).toBeFalse();
      expect(component.examsList.some(e => e.offline)).toBeFalse();
    });

    it('stops sending the offline work at the first copy the server refuses', async () => {
      await create();
      validation.validateDocument.and.resolveTo('ERROR');
      const copy: any = { pdfSrc: new PDFSource(12, 'blob:12', 0), file64: 'data:application/pdf;base64,JVBERi0xLjQ=',
                          updated: false, grade: 3, status: 'VALIDATED', questionIndex: '3' };
      component.offlineCopies = new Map([[12, copy]]);

      await component.uploadOffline(true);

      expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining("n'a pu être sauvegardée"), 'Error');
      expect(copy.updated).toBeFalse();
      expect(notification.showSuccess).not.toHaveBeenCalled();
    });

    it('cancelling the offline correction asks first', async () => {
      await create();
      const remove = spyOn(db, 'deleteAllCopies').and.resolveTo();
      spyOn(db, 'markOnline').and.resolveTo();
      component.offline = true;
      const open = spyOn(component.dialog, 'open').and.returnValue(dialogClosingWith(false));
      component.cancelOffline();
      await settle();
      expect(remove).not.toHaveBeenCalled();
      expect(component.offline).toBeTrue();

      open.and.returnValue(dialogClosingWith(true));
      component.cancelOffline();
      await settle();
      expect(notification.showSuccess).toHaveBeenCalledWith('Correction annulée!', 'Success');
      expect(remove).toHaveBeenCalled();
      expect(component.offline).toBeFalse();
    });

    it('resumes an offline correction with the grades and statuses stored locally', async () => {
      await create(JOB, {}, {}, QUESTION_DOCS, () => {
        spyOn(db, 'isOffline').and.resolveTo(true);
        spyOn(db, 'getAllCopies').and.resolveTo([
          { pdfSrc: { index: 10 }, grade: 4, status: 'VALIDATED' },
          { pdfSrc: { index: 12 }, status: 'TO VALIDATE' },
          { pdfSrc: { index: 77 }, grade: 1, status: 'VALIDATED' },  // no longer in the task
        ] as any);
        docs.loadPDFSource = jasmine.createSpy('loadPDFSource').and.callFake(async (dict) => new PDFSource(dict.index, `blob:off${dict.index}`, 0));
        docs.getAvailablePdfSource.and.callFake((jobId, index) => new PDFSource(index, `blob:off${index}`, 0));
      });

      expect(component.offline).toBeTrue();
      expect(Array.from(component.offlineCopies.keys())).toEqual([10, 12]);
      const first = component.examByDocumentIndex(10);
      expect(first.grade).toBe(4);
      expect(first.status).toBe('VALIDATED');
      expect(first.offline).toBeTrue();
      expect(component.pdfUrl).toBe('blob:off10');
      expect(docs.getPdfSource).not.toHaveBeenCalled();
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('.bottom-right-icon').length).toBe(2);
    });
  });
});

describe('TaskVerificationComponent grade reading', () => {
  // The reader fills the score field so the teacher confirms instead of
  // typing, but a read value is a suggestion: it must never look confirmed,
  // and a grade a human already set always wins.
  let component: TaskVerificationComponent;

  beforeEach(() => {
    component = Object.create(TaskVerificationComponent.prototype) as TaskVerificationComponent;
  });

  const withExam = (exam: any) => {
    (component as any).currentExam = () => exam;
    return component;
  };

  it('offers what the reader found when nobody has graded the copy', () => {
    withExam({ grade: null, auto_grade: 8.5, auto_grade_confidence: 0.97 }).loadScore();

    expect(component.currentGrade).toBe(8.5);
    expect(component.currentGradeIsAuto).toBeTrue();
    // the score box is 80px wide, so the confidence is a tooltip, not a caption
    expect(component.autoGradeHint()).toContain('97');
  });

  it('colours the score box like the tiles and the validate button', () => {
    component.currentStatus = DocumentStatus.VALIDATED;
    expect(component.gradeColor()).toBe('note-green');

    component.currentStatus = DocumentStatus.HIGH_ACCURACY;
    expect(component.gradeColor()).toBe('note-blue');

    component.currentStatus = DocumentStatus.TO_VALIDATE;
    expect(component.gradeColor()).toBe('note-red');
  });

  it('prefers a grade a human has already set', () => {
    withExam({ grade: 6, auto_grade: 8.5, auto_grade_confidence: 0.99 }).loadScore();

    expect(component.currentGrade).toBe(6);
    expect(component.currentGradeIsAuto).toBeFalse();
    expect(component.autoGradeHint()).toBe('');
  });

  it('leaves the field empty when the page could not be read', () => {
    withExam({ grade: null, auto_grade: null, auto_grade_reason: 'not_found' }).loadScore();

    expect(component.currentGrade).toBeNull();
    expect(component.currentGradeIsAuto).toBeFalse();
  });

  it('works on copies stored before the reader existed', () => {
    withExam({ grade: null }).loadScore();

    expect(component.currentGrade).toBeNull();
    expect(component.currentGradeIsAuto).toBeFalse();
  });

  it('saves a suggested grade when the teacher confirms it', () => {
    // the stored grade is still null, so the value has to be persisted rather
    // than treated as unchanged
    const exam: any = { grade: null, auto_grade: 8.5, auto_grade_confidence: 0.97 };
    withExam(exam).loadScore();

    expect(component.saveCurrentGrade()).toBeTrue();
    expect(exam.grade).toBe(8.5);
  });
});

describe('TaskVerificationComponent question reading state', () => {
  let component: TaskVerificationComponent;

  beforeEach(() => {
    component = Object.create(TaskVerificationComponent.prototype) as TaskVerificationComponent;
    component.currentQuestionIndex = '3';
  });

  it('reports on the question being corrected', () => {
    component.autoGradeProgress = {'3': {pending: 0, running: 2, done: 8, graded: 0, total: 10}};
    expect(component.readingStateForQuestion()).toContain('80 %');
  });

  it('leaves out the copies already graded by hand', () => {
    component.autoGradeProgress = {'3': {pending: 0, running: 0, done: 15, graded: 2, total: 17}};
    expect(component.readingStateForQuestion()).toContain('15/15');
  });

  it('says nothing when no reading has touched it', () => {
    component.autoGradeProgress = {};
    expect(component.readingStateForQuestion()).toBe('');
  });
});

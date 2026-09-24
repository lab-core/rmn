import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';

import { TaskVerificationComponent } from './task-verification.component';
import { DocumentStatus } from 'src/app/generated/rmn-contracts';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
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

  const create = async (job: any = JOB, queryParams: any = {}, params: any = {}) => {
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
        docs.documentsList = docs.documentsList.length ? docs.documentsList : JSON.parse(JSON.stringify(QUESTION_DOCS));
      }),
      getPdfSource: jasmine.createSpy('getPdfSource').and.callFake(async (jobId, index) => {
        const source = new PDFSource(index, `blob:${index}`, 0);
        source.setLastVersion(0);
        return source;
      }),
      getAvailablePdfSource: jasmine.createSpy('getAvailablePdfSource'),
      clearPdfSources: jasmine.createSpy('clearPdfSources'),
    };
    const tasks = {
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
    component.autoGradeProgress = {'3': {pending: 0, running: 2, done: 8, total: 10}};
    expect(component.readingStateForQuestion()).toContain('80 %');
  });

  it('says nothing when no reading has touched it', () => {
    component.autoGradeProgress = {};
    expect(component.readingStateForQuestion()).toBe('');
  });
});

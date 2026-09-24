import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { NewExamCorrectionComponent } from './new-exam-correction.component';
import { NotificationService } from 'src/app/services/notification.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, settle, userServiceStub } from '../../testing/helpers';

const TEMPLATES = [
  { template_id: 't1', template_name: 'Front', n_questions: 3, locked: false },
  { template_id: 't2', template_name: 'Regular', n_questions: 0, locked: false },
  { template_id: 'd1', template_name: 'Example: Exam', n_questions: 4, locked: true },
];

describe('NewExamCorrectionComponent', () => {
  let fixture: ComponentFixture<NewExamCorrectionComponent>;
  let component: NewExamCorrectionComponent;
  let http: HttpTestingController;
  let router: Router;
  let notification: jasmine.SpyObj<NotificationService>;
  let tasks: any;

  const create = async (templates: any[] = TEMPLATES) => {
    notification = notificationSpy();
    tasks = {
      addTask: jasmine.createSpy('addTask').and.resolveTo(undefined),
      getUploadPart1State: () => true,
      getUploadPart2State: () => false,
    };
    TestBed.configureTestingModule({
      declarations: [NewExamCorrectionComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: NotificationService, useValue: notification },
        { provide: TasksService, useValue: tasks },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(NewExamCorrectionComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/templates/user').flush({ response: templates });
    await settle();
    fixture.detectChanges();
  };

  beforeEach(() => {
    localStorage.clear();
    spyOn(console, 'log');
    spyOn(console, 'error');
  });
  afterEach(() => {
    component.doNotSaveTask = true;  // ngOnDestroy would otherwise write localStorage
    http.verify();
  });

  // what the cover template <mat-select> does: sets the value, then fires selectionChange
  const selectFront = () => {
    component.selectedFrontTemplate = 't1';
    component.onQuestionIndexChange({ value: 't1', source: { id: 'mat-select-0' } } as any);
  };
  const change = (value: string) => ({ target: { value } } as unknown as Event);

  it('offers only the user templates and warns when there is none', async () => {
    await create();
    expect(component.templates.map(t => t['template_id'])).toEqual(['t1', 't2']);
    expect(component.disabled).toBeFalse();

    TestBed.resetTestingModule();
    await create([TEMPLATES[2]]);
    expect(component.templates).toEqual([]);
    expect(component.disabled).toBeTrue();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('template'), 'Avertissement');
  });

  it('the cover template fixes the number of questions', async () => {
    await create();
    selectFront();
    expect(component.nQuestions).toBe(3);
    expect(component.questionKeys).toEqual(['Q1', 'Q2', 'Q3']);
    expect(component.incompleteQuestions()).toEqual(['Q1', 'Q2', 'Q3']);
    fixture.detectChanges();
    const rows = Array.from(fixture.nativeElement.querySelectorAll('.questions-table tbody tr')) as HTMLElement[];
    expect(rows.slice(0, 3).map(r => r.querySelector('td').textContent.trim())).toEqual(['Q1', 'Q2', 'Q3']);
  });

  it('validates pages and points and keeps the totals up to date', async () => {
    await create();
    selectFront();

    component.updatePageCount('Q1', change('2'));
    component.updateMaxPoints('Q1', change('7.5'));
    component.updatePageCount('Q2', change('1'));
    component.updateMaxPoints('Q2', change('2.5'));
    expect(component.totalPages).toBe(3);
    expect(component.totalPoints).toBe(10);
    expect(component.incompleteQuestions()).toEqual(['Q3']);

    const bad = change('0');
    component.updatePageCount('Q3', bad);
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('entière positive'), 'ERREUR');
    expect((bad.target as HTMLInputElement).value).toBe('');
    component.updateMaxPoints('Q3', change('-1'));
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('valeur positive'), 'ERREUR');
    component.updatePageCount('Q3', change('1.5'));
    expect(component.nPagesPerQuestion.get('Q3')).toBe(0);  // untouched

    component.updatePageCount('Q1', change(''));
    expect(component.nPagesPerQuestion.has('Q1')).toBeFalse();
  });

  it('a bonus question does not count in the total points', async () => {
    await create();
    selectFront();
    component.updateMaxPoints('Q1', change('10'));
    component.updateMaxPoints('Q2', change('5'));
    component.toggleBonus('Q2');
    expect(component.bonusEnabledMap.get('Q2')).toBeTrue();
    expect(component.totalPoints).toBe(10);
    component.toggleBonus('Q2');
    expect(component.totalPoints).toBe(15);
  });

  it('an ignored question is zeroed and no longer required', async () => {
    await create();
    selectFront();
    component.updatePageCount('Q2', change('2'));
    component.updateMaxPoints('Q2', change('4'));
    component.toggleBonus('Q2');

    component.toggleIgnored('Q2');
    expect(component.isIgnored('Q2')).toBeTrue();
    expect(component.nPagesPerQuestion.get('Q2')).toBe(0);
    expect(component.nMaxPointsPerQuestion.get('Q2')).toBe(0);
    expect(component.bonusEnabledMap.get('Q2')).toBeFalse();
    expect(component.incompleteQuestions()).toEqual(['Q1', 'Q3']);

    component.toggleIgnored('Q2');
    expect(component.isIgnored('Q2')).toBeFalse();
    expect(component.nPagesPerQuestion.has('Q2')).toBeFalse();
  });

  it('remembers the draft task across visits', async () => {
    await create();
    component.taskName = 'Final H26';
    selectFront();
    component.selectedRegularTemplate = 't2';
    component.statisticsForStudents = false;
    component.saveTask();

    const saved = JSON.parse(localStorage.getItem('newTask'));
    expect(saved.name).toBe('Final H26');
    expect(saved.frontTemplate).toBe('t1');
    expect(saved.nQuestions).toBe(3);

    component.doNotSaveTask = true;
    TestBed.resetTestingModule();
    await create();
    expect(component.taskName).toBe('Final H26');
    expect(component.selectedFrontTemplate).toBe('t1');
    expect(component.selectedRegularTemplate).toBe('t2');
    expect(component.statisticsForStudents).toBeFalse();
    expect(component.questionKeys).toEqual(['Q1', 'Q2', 'Q3']);
  });

  it('accepts a csv only when every line has the same separators', async () => {
    await create();
    const valid = new File(['Matricule,Nom complet,Groupe,Note\n1234567,Alice A,A,\n'], 'notes.csv', { type: 'text/csv' });
    component.CsvFileEvent({ target: { files: [valid] } } as unknown as Event);
    for (let i = 0; i < 50 && component.csvName === ''; i++) { await settle(1); }
    expect(component.csvName).toBe('notes.csv');
    expect(component.csv).toBe(valid);
    expect(fixture.nativeElement.querySelector('#csv-upload-label').textContent).toBe('notes.csv');

    const invalid = new File(['Matricule,Nom complet,Groupe,Note\n1234567,Alice A\n'], 'bad.csv', { type: 'text/csv' });
    component.CsvFileEvent({ target: { files: [invalid] } } as unknown as Event);
    for (let i = 0; i < 50 && !notification.showError.calls.count(); i++) { await settle(1); }
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('ligne est invalide'), 'ERREUR');
    expect(notification.showError).toHaveBeenCalledWith('Veuillez fournir un csv valide', 'ERREUR');
    expect(component.csvName).toBe('');
  });

  it('builds a valid empty zip when no copy is uploaded', async () => {
    await create();
    component.taskName = 'Quiz';
    const zip = component.createEmptyZipFile();
    expect(zip.name).toBe('Quiz.zip');
    expect(zip.type).toBe('application/zip');
    expect(zip.size).toBe(22);
  });

  it('refuses to create a task without csv or with incomplete questions', async () => {
    await create();
    await component.createTask();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('toutes les étapes'), 'ERREUR');

    component.csvName = 'notes.csv';
    component.csv = new File([''], 'notes.csv');
    selectFront();
    await component.createTask();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('Q1, Q2, Q3'), 'ERREUR');
    expect(tasks.addTask).not.toHaveBeenCalled();
  });

  it('creates the task with the maps and an empty zip, then leaves', async () => {
    await create();
    component.taskName = 'Quiz';
    component.csvName = 'notes.csv';
    component.csv = new File([''], 'notes.csv');
    component.selectedRegularTemplate = 't2';
    selectFront();
    component.updatePageCount('Q1', change('2'));
    component.updateMaxPoints('Q1', change('10'));
    component.toggleIgnored('Q2');
    component.updatePageCount('Q3', change('1'));
    component.updateMaxPoints('Q3', change('5'));
    component.validateMatricule = true;
    localStorage.setItem('newTask', '{}');

    await component.createTask();

    expect(tasks.addTask).toHaveBeenCalledTimes(1);
    const args = tasks.addTask.calls.mostRecent().args;
    expect((args[0] as File).size).toBe(22);
    expect(args[1]).toBe(component.csv);
    expect([args[2], args[3]]).toEqual(['t1', 't2']);
    expect(Array.from(args[4].entries())).toEqual([['Q1', 2], ['Q2', 0], ['Q3', 1]]);
    expect(Array.from(args[5].entries())).toEqual([['Q1', 10], ['Q2', 0], ['Q3', 5]]);
    expect(Array.from(args[6].entries())).toEqual([['Q1', false], ['Q2', false], ['Q3', false]]);
    expect(args.slice(7)).toEqual(['Quiz', 'Front', 'Regular', true, true]);
    expect(localStorage.getItem('newTask')).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });

  it('a task without correction sends empty maps', async () => {
    await create();
    component.csvName = 'notes.csv';
    component.csv = new File([''], 'notes.csv');
    selectFront();
    component.selectedRegularTemplate = 't2';
    component.correct = false;
    await component.createTask();
    const args = tasks.addTask.calls.mostRecent().args;
    expect(args[4].size).toBe(0);
    expect(args[10]).toBeFalse();
  });

  it('a failed upload clears the spinner and warns', async () => {
    await create();
    tasks.addTask.and.rejectWith(new Error('413'));
    component.csvName = 'notes.csv';
    component.csv = new File([''], 'notes.csv');
    selectFront();
    component.selectedRegularTemplate = 't2';
    component.correct = false;
    await component.createTask();
    expect(component.uploading).toBeFalse();
    expect(notification.showError).toHaveBeenCalledWith('Échec de la création de la tâche.', 'ERREUR');
    expect(router.navigate).not.toHaveBeenCalled();
  });
});

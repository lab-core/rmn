import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { NewExamCorrectionComponent } from './new-exam-correction.component';
import { NotificationService } from 'src/app/services/notification.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import {
  MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, settle, userServiceStub, waitUntil,
} from '../../testing/helpers';

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

  const create = async (templates: any[] = TEMPLATES, before: (c: NewExamCorrectionComponent) => void = () => {}) => {
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
    before(component);
    fixture.detectChanges();
    await settle();
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

  it('marks a cover template without question boxes and blocks the start without templates', async () => {
    await create([{ template_id: 't0', template_name: 'Empty', n_questions: 0, locked: false }]);
    component.onQuestionIndexChange({ value: undefined, source: { id: 'mat-select-0' } } as any);
    expect(component.nQuestions).toBeUndefined();  // clearing the select changes nothing
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.q-alert').textContent).toContain('sélectionner en premier');

    // the id comes from Material's global counter: any other page with a mat-select shifts it
    component.onQuestionIndexChange({ value: 't0', source: { id: 'mat-select-7' } } as any);
    fixture.detectChanges();
    expect(component.questionKeys).toEqual([]);
    expect(fixture.nativeElement.querySelector('.q-alert').textContent).toContain('sélectionner un rectangle');
    expect(fixture.nativeElement.querySelector('.q-alert').textContent).toContain('pour le template Empty.');
  });

  it('shows the start button disabled when the user has no template', async () => {
    await create([]);
    const start = Array.from(fixture.nativeElement.querySelectorAll('button'))
      .find((b: HTMLButtonElement) => b.textContent.includes('Commencer')) as HTMLButtonElement;
    expect(start.disabled).toBeTrue();
  });

  it('saves the draft on changes, on leaving and before the page unloads', async () => {
    await create();
    component.taskName = 'A';
    await component.ngOnChanges({});
    expect(JSON.parse(localStorage.getItem('newTask')).name).toBe('A');
    component.taskName = 'B';
    // not dispatched on window: karma takes a beforeunload for a page reload
    component.beforeUnloadHandler(new Event('beforeunload'));
    expect(JSON.parse(localStorage.getItem('newTask')).name).toBe('B');
    component.taskName = 'C';
    await component.ngOnDestroy();
    expect(JSON.parse(localStorage.getItem('newTask')).name).toBe('C');

    component.doNotSaveTask = true;
    component.taskName = 'D';
    component.saveTask();
    expect(JSON.parse(localStorage.getItem('newTask')).name).toBe('C');
  });

  it('keeps the form usable when the draft does not fit in localStorage', async () => {
    await create();
    spyOn(localStorage, 'setItem').and.throwError('QuotaExceededError');
    const warn = spyOn(console, 'warn');
    expect(() => component.saveTask()).not.toThrow();
    expect(warn).toHaveBeenCalledWith('draft task not saved', jasmine.any(Error));
  });

  it('restores the pages, points, bonus and ignored questions of a draft', async () => {
    localStorage.setItem('newTask', JSON.stringify({
      name: 'Draft', frontTemplate: 't1', regularTemplate: 't2', nQuestions: 2,
      nPages: { Q1: 2, Q2: 0 }, maxPoints: { Q1: 5, Q2: 0 }, bonus: { Q1: true }, ignored: { Q2: true }, stats: true,
    }));
    await create();
    expect(component.questionKeys).toEqual(['Q1', 'Q2']);
    expect(component.nPagesPerQuestion.get('Q1')).toBe(2);
    expect(component.bonusEnabledMap.get('Q1')).toBeTrue();
    expect(component.isIgnored('Q2')).toBeTrue();
    expect(component.totalPages).toBe(2);
    expect(component.totalPoints).toBe(0);  // Q1 is a bonus
    expect(component.incompleteQuestions()).toEqual([]);
  });

  it('lets only letters, digits, dashes and spaces into the suffix', async () => {
    await create();
    const key = (charCode: number) => ({ charCode, which: charCode, preventDefault: jasmine.createSpy('p') } as any);
    const letter = key('a'.charCodeAt(0));
    component.updateSuffix(letter);
    expect(letter.preventDefault).not.toHaveBeenCalled();
    const bang = key('!'.charCodeAt(0));
    component.updateSuffix(bang);
    expect(bang.preventDefault).toHaveBeenCalled();
    const byWhich = { charCode: 0, which: '/'.charCodeAt(0), preventDefault: jasmine.createSpy('p') } as any;
    component.updateSuffix(byWhich);
    expect(byWhich.preventDefault).toHaveBeenCalled();
  });

  it('selects the whole field on click and reports the upload steps', async () => {
    await create();
    const target = { select: jasmine.createSpy('select') };
    component.selectText({ target });
    expect(target.select).toHaveBeenCalled();

    expect(component.getUploadState1()).toBeFalse();
    component.uploading = true;
    expect(component.getUploadState1()).toBeTrue();
    expect(component.getUploadState2()).toBeFalse();
    tasks.getUploadPart2State = () => true;
    expect(component.getUploadState2()).toBeTrue();
  });

  it('cancel keeps the draft, forgets the files and goes back to the menu', async () => {
    await create();
    component.taskName = 'Kept';
    component.copiesName = 'copies.zip';
    component.csvName = 'notes.csv';
    component.cancel();
    expect(component.copiesName).toBe('');
    expect(component.csvName).toBe('');
    expect(JSON.parse(localStorage.getItem('newTask')).name).toBe('Kept');
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });

  it('shows the name of the zip of copies picked locally', async () => {
    await create();
    const zip = new File(['zip'], 'copies.zip');
    component.CopiesFileEvent({ target: { files: [zip] } } as unknown as Event);
    const label = fixture.nativeElement.querySelector('#files-upload-label') as HTMLElement;
    expect(label.textContent).toBe('copies.zip');
    expect(component.copies).toBe(zip);

    // picking another one replaces the label
    component.CopiesFileEvent({ target: { files: [new File(['z'], '<b>x</b>.zip')] } } as unknown as Event);
    expect(label.textContent).toBe('<b>x</b>.zip');
    expect(label.querySelector('b')).toBeNull();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.info small')).toBeNull();
  });

  it('rejects an empty csv', async () => {
    await create();
    component.CsvFileEvent({ target: { files: [new File([''], 'empty.csv')] } } as unknown as Event);
    for (let i = 0; i < 50 && !notification.showError.calls.count(); i++) { await settle(1); }
    expect(notification.showError).toHaveBeenCalledWith('Veuillez fournir un csv valide', 'ERREUR');
    expect(component.csv).toBeUndefined();
  });

  describe('front pages', () => {
    let downloads: string[];

    beforeEach(() => {
      downloads = [];
      spyOn(HTMLAnchorElement.prototype, 'dispatchEvent').and.callFake(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
        return true;
      });
    });

    it('needs both the moodle zip and the latex front page', async () => {
      await create();
      expect(component.checkDisabledPresentation()).toBeTrue();
      component.createPresentation();
      expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('toutes les étapes'), 'ERREUR');

      component.presentationCopiesFileEvent({ target: { files: [new File(['z'], 'moodle.zip')] } } as unknown as Event);
      component.latexFrontPageEvent({ target: { files: [new File(['t'], 'front.tex')] } } as unknown as Event);
      expect(component.checkDisabledPresentation()).toBeFalse();

      component.suffix = 'x';
      component.cancelPresentation();
      expect([component.presentationCopiesName, component.latexFrontPageName, component.suffix]).toEqual(['', '', '']);
      expect(component.checkDisabledPresentation()).toBeTrue();
    });

    it('downloads the zip with the front pages the server built', async () => {
      await create();
      const moodle = new File(['z'], 'moodle.zip');
      const front = new File(['t'], 'front.tex');
      component.presentationCopiesFileEvent({ target: { files: [moodle] } } as unknown as Event);
      component.latexFrontPageEvent({ target: { files: [front] } } as unknown as Event);
      component.suffix = 'H26';

      component.createPresentation();
      expect(component.disabled).toBeTrue();
      const req = http.expectOne('/api/frontpage');
      const form = req.request.body as FormData;
      expect(form.get('suffix')).toBe('H26');
      expect(form.get('moodle_zip')).toEqual(moodle);
      expect(form.get('latex_front_page')).toEqual(front);
      expect(form.get('user_id')).toBe('alice');
      req.flush(new Blob(['zip']));

      await waitUntil(() => downloads.length > 0);
      expect(downloads).toEqual(['moodle.zip']);
      expect(component.disabled).toBeFalse();
    });

    it('shows the server error when the front pages fail', async () => {
      await create();
      component.presentationCopiesFileEvent({ target: { files: [new File(['z'], 'moodle.zip')] } } as unknown as Event);
      component.latexFrontPageEvent({ target: { files: [new File(['t'], 'front.tex')] } } as unknown as Event);
      component.createPresentation();
      http.expectOne('/api/frontpage').flush(new Blob(['no']), { status: 500, statusText: 'Server Error' });
      expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('500'), 'ERREUR');
      expect(component.disabled).toBeFalse();
      expect(downloads).toEqual([]);
    });
  });

  describe('with Dropbox and OneDrive', () => {
    let appended: HTMLScriptElement[];

    beforeEach(() => {
      appended = [];
      // the pickers are global functions of the vendor scripts
      for (const name of ['dropboxFiles', 'dropboxCSV', 'onedrivePicker', 'onedrivePickerCSV']) {
        (window as any)[name] = jasmine.createSpy(name);
      }
      const append = document.body.appendChild.bind(document.body);
      spyOn(document.body, 'appendChild').and.callFake((node: any) => {
        if (node instanceof HTMLScriptElement) {
          appended.push(node);  // never fetch the vendor script
          setTimeout(() => node.onload?.(new Event('load')));
          return node;
        }
        return append(node);
      });
    });

    afterEach(() => {
      for (const name of ['dropboxFiles', 'dropboxCSV', 'onedrivePicker', 'onedrivePickerCSV']) {
        delete (window as any)[name];
      }
    });

    const both = (c: NewExamCorrectionComponent) => { c.showDropbox = true; c.showOneDrive = true; };
    const el = (id: string) => fixture.nativeElement.querySelector('#' + id) as HTMLElement;

    it('loads both vendor scripts before the templates', async () => {
      await create(TEMPLATES, both);
      expect(appended.map(s => s.id)).toEqual(['dropboxjs', 'onedrivejs']);
      expect(appended[0].src).toBe('https://www.dropbox.com/static/api/2/dropins.js');
      expect(appended[1].src).toBe('https://js.live.net/v7.2/OneDrive.js');
      expect(el('files-dropbox-input')).not.toBeNull();
      expect(el('csv-onedrive-input')).not.toBeNull();
    });

    it('rejects when a vendor script fails to load', async () => {
      await create();
      (document.body.appendChild as jasmine.Spy).and.callFake((node: any) => {
        setTimeout(() => node.onerror(new Event('error')));
        return node;
      });
      await expectAsync(component.loadDropbox()).toBeRejected();
      await expectAsync(component.loadOnedrive()).toBeRejected();
    });

    it('a pick with one provider forgets the file picked with the other', async () => {
      await create(TEMPLATES, both);
      component.copiesName = 'local.zip';
      el('files-onedrive-input').setAttribute('value', 'https://onedrive/copies');
      el('files-upload-label').setAttribute('value', 'od.zip');
      component.getDropBoxUpload();
      expect(component.copiesName).toBe('');
      expect(component.copies).toBeNull();
      expect(el('files-onedrive-input').getAttribute('value')).toBeNull();
      expect(el('files-upload-label').getAttribute('value')).toBeNull();
      expect((window as any).dropboxFiles).toHaveBeenCalled();

      component.copiesName = 'local.zip';
      el('files-dropbox-input').setAttribute('value', 'https://dropbox/copies');
      component.getOneDriveUpload();
      expect(component.copiesName).toBe('');
      expect(el('files-dropbox-input').getAttribute('value')).toBeNull();
      expect((window as any).onedrivePicker).toHaveBeenCalled();

      component.csvName = 'local.csv';
      el('csv-onedrive-input').setAttribute('value', 'https://onedrive/csv');
      el('csv-upload-label').setAttribute('value', 'od.csv');
      component.getDropBoxUploadCSV();
      expect(component.csvName).toBe('');
      expect(component.csv).toBeNull();
      expect(el('csv-onedrive-input').getAttribute('value')).toBeNull();
      expect((window as any).dropboxCSV).toHaveBeenCalled();

      component.csvName = 'local.csv';
      el('csv-dropbox-input').setAttribute('value', 'https://dropbox/csv');
      component.getOneDriveUploadCSV();
      expect(component.csvName).toBe('');
      expect(el('csv-dropbox-input').getAttribute('value')).toBeNull();
      expect((window as any).onedrivePickerCSV).toHaveBeenCalled();
    });

    it('a local pick forgets the files picked with a provider', async () => {
      await create(TEMPLATES, both);
      el('files-dropbox-input').setAttribute('value', 'https://dropbox/copies');
      el('files-onedrive-input').setAttribute('value', 'https://onedrive/copies');
      el('files-upload-label').setAttribute('value', 'remote.zip');
      component.CopiesFileEvent({ target: { files: [new File(['z'], 'local.zip')] } } as unknown as Event);
      expect(el('files-dropbox-input').getAttribute('value')).toBeNull();
      expect(el('files-onedrive-input').getAttribute('value')).toBeNull();
      expect(el('files-upload-label').getAttribute('value')).toBe('local.zip');

      el('csv-dropbox-input').setAttribute('value', 'https://dropbox/csv');
      el('csv-onedrive-input').setAttribute('value', 'https://onedrive/csv');
      el('csv-upload-label').setAttribute('value', 'remote.csv');
      component.CsvFileEvent({ target: { files: [new File(['a,b\n1,2\n'], 'local.csv')] } } as unknown as Event);
      expect(el('csv-dropbox-input').getAttribute('value')).toBeNull();
      expect(el('csv-onedrive-input').getAttribute('value')).toBeNull();
      await waitUntil(() => component.csvName === 'local.csv');
      expect(el('csv-upload-label').getAttribute('value')).toBe('local.csv');
    });

    it('creates the task with the copies and the csv picked from Dropbox', async () => {
      await create(TEMPLATES, both);
      const copiesUrl = URL.createObjectURL(new Blob(['copies-zip']));
      const csvUrl = URL.createObjectURL(new Blob(['a,b\n1,2\n']));
      el('files-dropbox-input').setAttribute('value', copiesUrl);
      el('files-upload-label').setAttribute('value', 'dropbox.zip');
      el('csv-dropbox-input').setAttribute('value', csvUrl);
      el('csv-upload-label').setAttribute('value', 'dropbox.csv');
      expect(component.checkDisabled()).toBeFalse();  // no local csv, but one from Dropbox
      component.taskName = '';
      expect(component.checkDisabled()).toBeTrue();
      component.taskName = 'Remote';
      selectFront();
      component.selectedRegularTemplate = 't2';
      component.correct = false;

      await component.createTask();

      const [copies, csv] = tasks.addTask.calls.mostRecent().args;
      expect(copies.name).toBe('dropbox.zip');
      expect(await copies.text()).toBe('copies-zip');
      expect(csv.name).toBe('dropbox.csv');
      expect(await csv.text()).toBe('a,b\n1,2\n');
    });

    it('creates the task with the copies and the csv picked from OneDrive', async () => {
      await create(TEMPLATES, both);
      el('files-onedrive-input').setAttribute('value', URL.createObjectURL(new Blob(['od-zip'])));
      el('files-upload-label').setAttribute('value', 'onedrive.zip');
      el('csv-onedrive-input').setAttribute('value', URL.createObjectURL(new Blob(['x,y\n'])));
      el('csv-upload-label').setAttribute('value', 'onedrive.csv');
      selectFront();
      component.selectedRegularTemplate = 't2';
      component.correct = false;

      await component.createTask();

      const [copies, csv] = tasks.addTask.calls.mostRecent().args;
      expect(copies.name).toBe('onedrive.zip');
      expect(await copies.text()).toBe('od-zip');
      expect(csv.name).toBe('onedrive.csv');
    });
  });
});

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { TemplatesPageComponent } from './templates-page.component';
import { NewTemplateDialogComponent } from '../new-template-dialog/new-template-dialog.component';
import { WarningDialogComponent } from '../warning-dialog/warning-dialog.component';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { TemplateService } from 'src/app/services/template.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, MainMenuStubComponent, settle, userServiceStub } from '../../testing/helpers';

const TEMPLATES = [
  { template_name: 'Example: Exam', template_id: 'd1', n_questions: 4, locked: true, src_name: 'exam.tex' },
  { template_name: 'Mine', template_id: 't1', n_questions: 3, locked: false },
  { template_name: 'Midterm', template_id: 't2', n_questions: 2, locked: false },
];

describe('TemplatesPageComponent', () => {
  let fixture: ComponentFixture<TemplatesPageComponent>;
  let component: TemplatesPageComponent;
  let http: HttpTestingController;
  let router: Router;
  let dialog: MatDialog;
  let templates: TemplateService;
  let rectangles: RectangleService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      declarations: [TemplatesPageComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    dialog = TestBed.inject(MatDialog);
    templates = TestBed.inject(TemplateService);
    rectangles = TestBed.inject(RectangleService);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(console, 'log');
  });

  afterEach(() => http.verify());

  const init = () => {
    fixture = TestBed.createComponent(TemplatesPageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/user/template').flush({ response: TEMPLATES });
    fixture.detectChanges();
  };

  const rows = () => Array.from(fixture.nativeElement.querySelectorAll('.template-container')) as HTMLElement[];

  it('lists the templates with edit for all, download for defaults and delete for own', () => {
    init();
    expect(rows().map(r => r.querySelector('.template-title').textContent.trim())).toEqual(['Example: Exam', 'Mine', 'Midterm']);
    expect(rows()[0].querySelector('.download-icon')).not.toBeNull();
    expect(rows()[0].querySelector('.delete-icon')).toBeNull();
    expect(rows()[1].querySelector('.download-icon')).toBeNull();
    expect(rows()[1].querySelector('.delete-icon')).not.toBeNull();
  });

  it('filters by name and restores the list on backspace', () => {
    init();
    component.filterSearch = 'mi';
    component.updateAvailableTemplates(new KeyboardEvent('keyup', { key: 'i' }));
    expect(component.templatesList.map(t => t['template_name'])).toEqual(['Mine', 'Midterm']);
    component.filterSearch = '';
    component.updateAvailableTemplates(new KeyboardEvent('keyup', { key: 'Backspace' }));
    expect(component.templatesList.length).toBe(3);
  });

  it('opens the creation dialog with fresh boxes', () => {
    init();
    rectangles.setIdentificationRectCoords({ x1: 1, x2: 2, y1: 3, y2: 4 });
    spyOn(dialog, 'open').and.returnValue({} as any);
    (fixture.nativeElement.querySelector('.create-new-button') as HTMLButtonElement).click();
    expect(dialog.open).toHaveBeenCalledWith(NewTemplateDialogComponent, jasmine.any(Object));
    expect(rectangles.getIdentificationRectCoords()).toEqual({ x1: null, x2: null, y1: null, y2: null });
  });

  it('deletes after confirmation and refreshes the list', () => {
    init();
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(true) } as any);
    (rows()[1].querySelector('.delete-icon') as HTMLElement).click();
    expect(dialog.open).toHaveBeenCalledWith(WarningDialogComponent, jasmine.any(Object));
    const del = http.expectOne('/api/template/delete');
    expect((del.request.body as FormData).get('template_id')).toBe('t1');
    del.flush({ response: 'OK' });
    http.expectOne('/api/user/template').flush({ response: TEMPLATES.slice(0, 1) });
    fixture.detectChanges();
    expect(rows().length).toBe(1);
  });

  it('does nothing when the deletion is cancelled', () => {
    init();
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(false) } as any);
    component.openDeleteDialog(TEMPLATES[1] as any);
    http.expectNone('/api/template/delete');
    expect(component.templatesList.length).toBe(3);
  });

  it('editing loads the boxes, the template file and opens the editor', async () => {
    init();
    spyOn(URL, 'createObjectURL').and.returnValue('blob:tpl');
    (rows()[1].querySelector('.edit-icon') as HTMLElement).click();

    const info = http.expectOne('/api/template/info');
    expect((info.request.body as FormData).get('template_id')).toBe('t1');
    info.flush({ response: {
      template_name: 'Mine', template_id: 't1', locked: false, n_questions: 3,
      matricule_box: { x1: 5, x2: 85, y1: 15, y2: 35 }, grade_box: { x1: 82, x2: 96, y1: 15, y2: 55 },
    } });
    const download = http.expectOne('/api/template/download');
    expect(download.request.responseType).toBe('blob');
    download.flush(new Blob(['%PDF']));
    await settle();

    expect(rectangles.getIdentificationRectCoords()).toEqual({ x1: 5, x2: 85, y1: 15, y2: 35 });
    expect(rectangles.getQuestionsRectCoords()).toEqual({ x1: 82, x2: 96, y1: 15, y2: 55 });
    expect(templates.getId()).toBe('t1');
    expect(templates.getName()).toBe('Mine');
    expect(templates.getNQuestions()).toBe(3);
    expect(templates.getLocked()).toBeFalse();
    expect(templates.getUrl()).toBe('blob:tpl');
    expect(router.navigate).toHaveBeenCalledWith(['/template-editor']);
  });

  it('reopens the template remembered from a previous visit', () => {
    templates.setId('t2');
    init();
    const info = http.expectOne('/api/template/info');
    expect((info.request.body as FormData).get('template_id')).toBe('t2');
    info.flush({ response: { template_name: 'Midterm', template_id: 't2', locked: false, n_questions: 2 } });
    http.expectOne('/api/template/download').flush(new Blob());
  });
});

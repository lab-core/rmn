import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { TemplateEditorComponent } from './template-editor.component';
import { EraserService } from 'src/app/services/drawing/eraser.service';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { SelectionService } from 'src/app/services/drawing/selection.service';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { TemplateService } from 'src/app/services/template.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, notificationSpy, settle, socketServiceStub, userServiceStub } from '../../testing/helpers';

describe('TemplateEditorComponent', () => {
  let fixture: ComponentFixture<TemplateEditorComponent>;
  let component: TemplateEditorComponent;
  let http: HttpTestingController;
  let router: Router;
  let notification: jasmine.SpyObj<NotificationService>;
  let socket: any;
  let templates: TemplateService;
  let rectangles: RectangleService;

  const create = (withTemplate = true) => {
    localStorage.clear();
    notification = notificationSpy();
    socket = socketServiceStub();
    TestBed.configureTestingModule({
      declarations: [TemplateEditorComponent],
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
    templates = TestBed.inject(TemplateService);
    rectangles = TestBed.inject(RectangleService);
    rectangles.resetRects();
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(console, 'log');
    if (withTemplate) {
      templates.url = 'blob:tpl';
      templates.setName('Exam');
      templates.setId('t1');
      templates.setLocked(false);
      templates.setNQuestions(3);
      rectangles.setIdentificationRectCoords({ x1: 5, x2: 85, y1: 15, y2: 35 });
    }
    fixture = TestBed.createComponent(TemplateEditorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  };

  afterEach(() => http.verify());

  it('goes back to the templates page when no template is loaded', () => {
    create(false);
    expect(router.navigate).toHaveBeenCalledWith(['/templates']);
    expect(socket.join).not.toHaveBeenCalled();
  });

  it('shows the template, draws the stored boxes and joins its socket room', () => {
    create();
    expect(component.templateName).toBe('Exam');
    expect(component.nQuestions).toBe(3);
    expect(component.disabled).toBeFalse();
    expect(fixture.nativeElement.textContent).toContain('Nombre de questions: 3');
    expect(fixture.nativeElement.querySelector('#svg #identification')).not.toBeNull();
    expect(socket.join).toHaveBeenCalledWith('t1');
    expect(socket.socket.handlers['template_rendered']).toBeDefined();
  });

  it('a locked template cannot be confirmed', () => {
    create();
    templates.setLocked(true);
    fixture = TestBed.createComponent(TemplateEditorComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement.querySelector('.confirmation-button') as HTMLButtonElement).disabled).toBeTrue();
  });

  it('routes the mouse to the active tool', () => {
    create();
    const selection = TestBed.inject(SelectionService);
    const eraser = TestBed.inject(EraserService);
    spyOn(rectangles, 'init');
    spyOn(rectangles, 'mouseDown');
    spyOn(selection, 'init');
    spyOn(selection, 'deleteControlPoints');
    spyOn(selection, 'mouseDown');
    spyOn(eraser, 'init');
    spyOn(eraser, 'mouseDown');
    const event = new MouseEvent('mousedown');

    component.onToolChange('rectangle');
    expect(rectangles.init).toHaveBeenCalled();
    component.setQuestionsRect();
    component.mouseDown(event);
    expect(rectangles.mouseDown).toHaveBeenCalledWith(event, false);

    component.toolType = 'selection';
    component.onToolChange('selection');
    component.mouseDown(event);
    expect(selection.init).toHaveBeenCalled();
    expect(selection.mouseDown).toHaveBeenCalledWith(event);

    component.toolType = 'delete';
    component.onToolChange('delete');
    component.mouseDown(event);
    expect(eraser.init).toHaveBeenCalled();
    expect(eraser.mouseDown).toHaveBeenCalledWith(event);
  });

  it('confirm refuses an empty name', () => {
    create();
    component.templateName = '   ';
    component.confirm();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('nom'), 'Erreur');
    http.expectNone('/api/template/modify');
  });

  it('confirm sends the name and boxes, the grade box only when drawn', () => {
    create();
    component.templateName = 'Exam v2';
    component.confirm();

    let req = http.expectOne('/api/template/modify');
    let form = req.request.body as FormData;
    expect(form.get('template_id')).toBe('t1');
    expect(form.get('template_name')).toBe('Exam v2');
    expect(JSON.parse(form.get('matricule_box') as string)).toEqual({ x1: 5, x2: 85, y1: 15, y2: 35 });
    expect(form.has('grade_box')).toBeFalse();
    req.flush({ response: 'OK' });
    expect(component.disabled).toBeTrue();
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('rendu'), 'Sauvegardé');

    rectangles.setquestionsRectCoords({ x1: 82, x2: 96, y1: 15, y2: 55 });
    component.confirm();
    req = http.expectOne('/api/template/modify');
    form = req.request.body as FormData;
    expect(JSON.parse(form.get('grade_box') as string)).toEqual({ x1: 82, x2: 96, y1: 15, y2: 55 });
    req.flush({ response: 'OK' });
  });

  it('a rendered template is downloaded again and re-enables the editor', async () => {
    create();
    spyOn(URL, 'createObjectURL').and.returnValue('blob:tpl2');
    component.disabled = true;

    socket.socket.fire('template_rendered', JSON.stringify({ template_id: 't1', n_questions: 5 }));
    const req = http.expectOne('/api/template/download');
    expect((req.request.body as FormData).get('template_id')).toBe('t1');
    req.flush(new Blob(['%PDF']));
    await settle();

    expect(component.nQuestions).toBe(5);
    expect(templates.getUrl()).toBe('blob:tpl2');
    expect(component.disabled).toBeFalse();
    expect(notification.showSuccess).toHaveBeenCalledWith(jasmine.stringContaining('mis à jour'), 'Rendu');
  });

  it('leaving clears the boxes and, with the back arrow, the template', () => {
    create();
    component.reroute(true);
    expect(rectangles.getIdentificationRectCoords()).toEqual({ x1: null, x2: null, y1: null, y2: null });
    expect(templates.getId()).toBeUndefined();
    expect(router.navigate).toHaveBeenCalledWith(['/templates']);
  });
});

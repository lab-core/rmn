import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';

import { NewTemplateDialogComponent } from './new-template-dialog.component';
import { TemplateService } from 'src/app/services/template.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, settle, userServiceStub } from '../../testing/helpers';

describe('NewTemplateDialogComponent', () => {
  let fixture: ComponentFixture<NewTemplateDialogComponent>;
  let component: NewTemplateDialogComponent;
  let http: HttpTestingController;
  let router: Router;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let templates: TemplateService;
  const pdf = new File(['%PDF'], 'exam.pdf', { type: 'application/pdf' });

  beforeEach(() => {
    localStorage.clear();
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [NewTemplateDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    fixture = TestBed.createComponent(NewTemplateDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    templates = TestBed.inject(TemplateService);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('enables confirmation only with a file and a positive page', () => {
    const confirm = () => fixture.nativeElement.querySelector('.confirm-document-button') as HTMLButtonElement;
    expect(component.disabled).toBeTrue();
    expect(confirm().disabled).toBeTrue();

    component.onFileSelected({ target: { files: [pdf] } });
    fixture.detectChanges();
    expect(component.copyName).toBe('exam.pdf');
    expect(component.disabled).toBeFalse();
    expect(confirm().disabled).toBeFalse();
    expect(fixture.nativeElement.querySelector('.label-box h4').textContent).toContain('exam.pdf');

    component.page = 0;
    component.setPage();
    expect(component.hideWarning).toBeFalse();
    expect(component.disabled).toBeTrue();

    component.page = 2;
    component.setPage();
    expect(component.disabled).toBeFalse();

    component.deleteFile();
    expect(component.copy).toBeUndefined();
    expect(component.disabled).toBeTrue();
  });

  it('accepts a dropped pdf', () => {
    const drop = new DragEvent('drop', { cancelable: true });
    const clearData = jasmine.createSpy('clearData');
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [pdf], clearData } });
    component.onDrop(drop);
    expect(drop.defaultPrevented).toBeTrue();
    expect(component.copy).toBe(pdf);
    expect(clearData).toHaveBeenCalled();
  });

  it('creates the template, downloads its rendering and opens the editor', async () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:tpl');
    component.setCopy(pdf);
    component.page = 2;

    component.confirm();

    const create = http.expectOne('/api/template');
    const form = create.request.body as FormData;
    expect(form.get('user_id')).toBe('alice');
    expect((form.get('template_file') as File).name).toBe('exam.pdf');
    expect(form.get('template_page')).toBe('1');  // zero-based on the server
    expect(form.get('template_name')).toBe('New template');
    create.flush({ response: { template_name: 'New template', template_id: 't1' } });

    const download = http.expectOne('/api/template/download');
    expect((download.request.body as FormData).get('template_id')).toBe('t1');
    expect(download.request.responseType).toBe('blob');
    download.flush(new Blob(['%PDF']));
    await settle();

    expect(templates.getId()).toBe('t1');
    expect(templates.getName()).toBe('New template');
    expect(templates.getFile().name).toBe('New template');
    expect(templates.getUrl()).toBe('blob:tpl');
    expect(dialogRef.close).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/template-editor']);
  });
});

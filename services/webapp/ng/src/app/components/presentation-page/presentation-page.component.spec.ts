import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { PresentationPageComponent } from './presentation-page.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('PresentationPageComponent', () => {
  let fixture: ComponentFixture<PresentationPageComponent>;
  let component: PresentationPageComponent;
  let http: HttpTestingController;
  let router: Router;
  let notification: jasmine.SpyObj<NotificationService>;
  const zip = new File(['PK'], 'moodle.zip');
  const tex = new File(['\\documentclass{article}'], 'front.tex');

  beforeEach(() => {
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [PresentationPageComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: NotificationService, useValue: notification },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    fixture = TestBed.createComponent(PresentationPageComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  const pick = (file: File) => ({ target: { files: [file] } } as unknown as Event);

  it('needs both files before it can start', () => {
    expect(component.checkDisabled()).toBeTrue();
    component.CopiesFileEvent(pick(zip));
    expect(component.copiesName).toBe('moodle.zip');
    expect(component.checkDisabled()).toBeTrue();
    component.latexFrontPageEvent(pick(tex));
    expect(component.latexFrontPageName).toBe('front.tex');
    expect(component.checkDisabled()).toBeFalse();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('moodle.zip');
  });

  it('refuses to start with a missing file', () => {
    component.createPresentation();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('toutes les étapes'), 'ERREUR');
    http.expectNone('/api/front_page');
  });

  it('posts the files and suffix, and recovers from a server error', () => {
    component.CopiesFileEvent(pick(zip));
    component.latexFrontPageEvent(pick(tex));
    component.suffix = 'H26';

    component.createPresentation();
    expect(component.disabled).toBeTrue();

    const req = http.expectOne('/api/front_page');
    const form = req.request.body as FormData;
    expect(form.get('suffix')).toBe('H26');
    expect((form.get('moodle_zip') as File).name).toBe('moodle.zip');
    expect((form.get('latex_front_page') as File).name).toBe('front.tex');
    expect(form.get('token')).toBe('tok');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(), { status: 500, statusText: 'LaTeX failed' });

    expect(notification.showError).toHaveBeenCalledWith(jasmine.any(String), 'ERREUR');
    expect(component.disabled).toBeFalse();
  });

  it('only lets letters, digits, dashes, underscores and spaces into the suffix', () => {
    const ok = new KeyboardEvent('keypress', { charCode: 'a'.charCodeAt(0), cancelable: true } as any);
    const bad = new KeyboardEvent('keypress', { charCode: '/'.charCodeAt(0), cancelable: true } as any);
    component.updateSuffix(ok);
    component.updateSuffix(bad);
    expect(ok.defaultPrevented).toBeFalse();
    expect(bad.defaultPrevented).toBeTrue();
  });

  it('cancel clears the form and goes back to the menu', () => {
    component.CopiesFileEvent(pick(zip));
    component.suffix = 'x';
    component.cancel();
    expect(component.copiesName).toBe('');
    expect(component.suffix).toBe('');
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });
});

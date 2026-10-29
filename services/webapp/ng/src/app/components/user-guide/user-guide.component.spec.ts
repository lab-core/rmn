import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, ParamMap, Router, RouterModule, convertToParamMap } from '@angular/router';
import { BehaviorSubject } from 'rxjs';

import { UserGuideComponent, renderGuide } from './user-guide.component';
import { GUIDE_CHAPTERS } from '../../help/guide';
import { MATERIAL_MODULES, MainMenuStubComponent, settle, waitUntil } from '../../testing/helpers';

describe('renderGuide', () => {
  it('serves the images from assets/guide', () => {
    expect(renderGuide('![Assistant](img/wizard.png)')).toContain('src="assets/guide/img/wizard.png"');
    expect(renderGuide('![x](https://example.org/x.png)')).toContain('src="https://example.org/x.png"');
  });

  it('opens the links between chapters in the app', () => {
    expect(renderGuide('[suite](05-nouvelle-tache.md#étape-1)')).toContain('href="user-guide/05-nouvelle-tache#%C3%A9tape-1"');
    expect(renderGuide('[moodle](https://moodle.org)')).toContain('href="https://moodle.org"');
  });

  it('renders the tables of GitHub markdown', () => {
    expect(renderGuide('| a | b |\n|---|---|\n| 1 | 2 |')).toContain('<table>');
  });
});

describe('UserGuideComponent', () => {
  let fixture: ComponentFixture<UserGuideComponent>;
  let http: HttpTestingController;
  let params: BehaviorSubject<ParamMap>;
  let fragment: BehaviorSubject<string | null>;

  beforeEach(() => {
    params = new BehaviorSubject(convertToParamMap({chapter: '05-nouvelle-tache'}));
    fragment = new BehaviorSubject<string | null>(null);
    TestBed.configureTestingModule({
      declarations: [UserGuideComponent, MainMenuStubComponent],
      imports: [...MATERIAL_MODULES, RouterModule.forRoot([])],
      providers: [
        provideHttpClient(), provideHttpClientTesting(),
        {provide: ActivatedRoute, useValue: {paramMap: params, fragment}},
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(UserGuideComponent);
    fixture.detectChanges();
  });

  async function answer(file: string, markdown: string): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve));
    http.expectOne(`assets/guide/${file}.md`).flush(markdown);
    await waitUntil(() => {
      fixture.detectChanges();
      return fixture.nativeElement.querySelector('.guide-content h1') !== null;
    });
    await new Promise((resolve) => setTimeout(resolve));
  }

  it('lists every chapter and highlights the open one', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche');
    const links = fixture.nativeElement.querySelectorAll('.guide-toc a');
    expect(links.length).toBe(GUIDE_CHAPTERS.length);
    expect(fixture.nativeElement.querySelector('.guide-toc a.active').textContent).toContain('Créer la tâche');
  });

  it('gives the headings the ids of GitHub', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche\n\n## Étape 1 : Nommer la tâche');
    expect(fixture.nativeElement.querySelector('.guide-content h2').id).toBe('étape-1--nommer-la-tâche');
  });

  it('scrolls to the section of the fragment', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche\n\n## Le tableau des questions');
    const scroll = spyOn(Element.prototype, 'scrollIntoView');
    fragment.next('le-tableau-des-questions');  // same chapter: nothing to load
    await settle();
    fixture.detectChanges();
    http.expectNone('assets/guide/05-nouvelle-tache.md');
    expect(scroll).toHaveBeenCalled();
    expect((scroll.calls.mostRecent().object as unknown as HTMLElement).id).toBe('le-tableau-des-questions');
  });

  it('opens the overview for an unknown chapter', async () => {
    params.next(convertToParamMap({chapter: 'nope'}));
    await new Promise((resolve) => setTimeout(resolve));
    http.match('assets/guide/05-nouvelle-tache.md').forEach((request) => request.flush('# x'));
    await answer('README', '# Vue d\'ensemble');
    expect(fixture.componentInstance.current.file).toBe('README');
  });

  it('says so when a chapter cannot be loaded', async () => {
    await new Promise((resolve) => setTimeout(resolve));
    http.expectOne('assets/guide/05-nouvelle-tache.md').flush('', {status: 404, statusText: 'Not Found'});
    await waitUntil(() => {
      fixture.detectChanges();
      return fixture.componentInstance.error !== '';
    });
    expect(fixture.nativeElement.querySelector('.guide-error')).not.toBeNull();
  });

  it('keeps the links between chapters in the app', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche\n\n[matricules](07-matricules.md#matricule-utilisé)');
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.nativeElement.querySelector('.guide-content p a').click();
    expect(router.navigate).toHaveBeenCalledWith(['/user-guide/07-matricules'], {fragment: 'matricule-utilisé'});
  });

  it('follows an anchor of the same chapter', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche\n\n[plus bas](#le-tableau)');
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.nativeElement.querySelector('.guide-content p a').click();
    expect(router.navigate).toHaveBeenCalledWith(['/user-guide/05-nouvelle-tache'], {fragment: 'le-tableau'});
  });

  it('opens the other links in a new tab', async () => {
    await answer('05-nouvelle-tache', '# Créer la tâche\n\n[moodle](https://moodle.org)');
    spyOn(window, 'open');
    fixture.nativeElement.querySelector('.guide-content p a').click();
    expect(window.open).toHaveBeenCalledWith('https://moodle.org', '_blank', 'noopener');
  });
});

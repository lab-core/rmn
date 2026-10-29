import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { MainMenuComponent } from './main-menu.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('MainMenuComponent', () => {
  let fixture: ComponentFixture<MainMenuComponent>;
  let router: Router;
  let user: any;
  let notification: jasmine.SpyObj<NotificationService>;

  beforeEach(() => {
    user = userServiceStub();
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [MainMenuComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideRouter([]),
        { provide: UserService, useValue: user },
        { provide: NotificationService, useValue: notification },
      ],
    });
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(MainMenuComponent);
    fixture.detectChanges();
  });

  const entries = () => Array.from(fixture.nativeElement.querySelectorAll('.buttons-container > div')) as HTMLElement[];

  it('shows the menu entries', () => {
    expect(entries().map(e => e.textContent.replace(/\s+/g, ' ').trim())).toEqual([
      'list_alt Tâches', 'post_add Nouvelle tâche', 'manage_search Template', 'library_books Guide',
      'person Profil', 'exit_to_app Déconnexion',
    ]);
  });

  it('navigates from each entry', () => {
    const [tasks, newTask, templates, guide, profile] = entries();
    tasks.click();
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    newTask.click();
    expect(router.navigate).toHaveBeenCalledWith(['/new-exam-correction']);
    templates.click();
    expect(router.navigate).toHaveBeenCalledWith(['/templates']);
    guide.click();
    expect(router.navigate).toHaveBeenCalledWith(['/user-guide']);
    profile.click();
    expect(router.navigate).toHaveBeenCalledWith(['/user-profile']);
  });

  it('logs out, goes to the login page and says so', () => {
    (fixture.nativeElement.querySelector('.disconnect-button') as HTMLElement).click();
    expect(user.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(notification.showInfo).toHaveBeenCalledWith('', 'Déconnecté!');
  });

  it('offers the way back to the admin of a borrowed session', () => {
    expect(fixture.nativeElement.querySelector('.stop-impersonating')).toBeNull();
    user.impersonatedBy = 'root';
    fixture.detectChanges();
    const back = fixture.nativeElement.querySelector('.stop-impersonating') as HTMLElement;
    expect(back.textContent).toContain('Revenir à root');
    const navigateByUrl = spyOn(router, 'navigateByUrl').and.resolveTo(true);
    back.click();
    expect(user.stopImpersonating).toHaveBeenCalled();
    // back to the page the role was taken from
    expect(navigateByUrl).toHaveBeenCalledWith('/admin');
    expect(notification.showInfo).toHaveBeenCalledWith('', 'De retour en tant que root');
  });

  it('offers the admin page to Gestionnaires and Administrateurs', () => {
    expect(fixture.nativeElement.querySelector('.admin-entry')).toBeNull();
    user.role = 'Gestionnaire';
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('.admin-entry') as HTMLElement).click();
    expect(router.navigate).toHaveBeenCalledWith(['/admin']);
  });
});

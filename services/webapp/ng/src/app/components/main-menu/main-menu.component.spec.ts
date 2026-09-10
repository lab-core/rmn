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

  it('shows the four menu entries', () => {
    expect(entries().map(e => e.textContent.replace(/\s+/g, ' ').trim())).toEqual([
      'list_alt Tâches', 'post_add Nouvelle tâche', 'manage_search Template', 'person Profil', 'exit_to_app Déconnexion',
    ]);
  });

  it('navigates from each entry', () => {
    const [tasks, newTask, templates, profile] = entries();
    tasks.click();
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    newTask.click();
    expect(router.navigate).toHaveBeenCalledWith(['/new-exam-correction']);
    templates.click();
    expect(router.navigate).toHaveBeenCalledWith(['/templates']);
    profile.click();
    expect(router.navigate).toHaveBeenCalledWith(['/user-profile']);
  });

  it('logs out, goes to the login page and says so', () => {
    (fixture.nativeElement.querySelector('.disconnect-button') as HTMLElement).click();
    expect(user.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(notification.showInfo).toHaveBeenCalledWith('', 'Déconnecté!');
  });
});

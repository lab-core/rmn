import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { LoginPageComponent } from './login-page.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('LoginPageComponent', () => {
  let fixture: ComponentFixture<LoginPageComponent>;
  let component: LoginPageComponent;
  let router: Router;
  let user: any;
  let notification: jasmine.SpyObj<NotificationService>;

  const create = (loggedIn: boolean) => {
    user = userServiceStub({ loggued: () => loggedIn });
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [LoginPageComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideRouter([]),
        { provide: UserService, useValue: user },
        { provide: NotificationService, useValue: notification },
      ],
    });
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(LoginPageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  };

  it('sends an already logged-in visitor to the home page', () => {
    create(true);
    expect(router.navigate).toHaveBeenCalledWith(['/']);
  });

  it('renders the form and logs in with the typed credentials', async () => {
    create(false);
    expect(router.navigate).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelectorAll('input').length).toBe(2);

    component.username = 'alice';
    component.password = 'pw';
    await component.attemptLogin();

    expect(user.login).toHaveBeenCalledWith('alice', 'pw');
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });

  it('shows the server message when the login fails', async () => {
    create(false);
    user.login.and.rejectWith({ error: { response: "Nom d'utilisateur/Mot de passe invalide" } });
    await component.attemptLogin();
    expect(notification.showError).toHaveBeenCalledWith("Nom d'utilisateur/Mot de passe invalide", 'Erreur de connexion');
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('the Enter key submits from anywhere on the page', () => {
    create(false);
    spyOn(component, 'attemptLogin');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(component.attemptLogin).toHaveBeenCalled();
  });

  it('toggles the password visibility', () => {
    create(false);
    const password = fixture.nativeElement.querySelectorAll('input')[1] as HTMLInputElement;
    expect(password.type).toBe('password');
    (fixture.nativeElement.querySelector('#input mat-icon') as HTMLElement).click();
    fixture.detectChanges();
    expect(password.type).toBe('text');
  });
});

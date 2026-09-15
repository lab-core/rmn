import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialogRef } from '@angular/material/dialog';

import { ChangePasswordDialogComponent } from './change-password-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('ChangePasswordDialogComponent', () => {
  let fixture: ComponentFixture<ChangePasswordDialogComponent>;
  let component: ChangePasswordDialogComponent;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;

  beforeEach(() => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [ChangePasswordDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: userServiceStub() },
      ],
    });
    fixture = TestBed.createComponent(ChangePasswordDialogComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  const fill = (current: string, next: string, repeat: string) => {
    component.currentPass = current;
    component.newPass = next;
    component.newPassRepeat = repeat;
  };

  it('refuses empty, short and mismatched passwords without calling the server', () => {
    fill('', 'longenough1', 'longenough1');
    component.attemptSave();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('champ'), 'Champ Vide');

    fill('old', 'x'.repeat(33), 'x'.repeat(33));
    component.attemptSave();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('maximum 32'), 'Avertissement!');

    fill('old', 'has a space', 'has a space');
    component.attemptSave();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('Caractères permis'), 'Avertissement!');

    fill('old', 'short', 'short');
    component.attemptSave();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.stringContaining('8 caractères'), 'Avertissement!');

    fill('old', 'longenough1', 'longenough2');
    component.attemptSave();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.stringContaining('concordre'), 'Champs Non Égaux');

    http.expectNone('/api/password');
  });

  it('posts the change with the credentials and closes on success', () => {
    fill('old-pass', 'longenough1', 'longenough1');
    component.attemptSave();

    const req = http.expectOne('/api/password');
    const form = req.request.body as FormData;
    expect(form.get('username')).toBe('alice');
    expect(form.get('token')).toBe('tok');
    expect(form.get('old_password')).toBe('old-pass');
    expect(form.get('new_password')).toBe('longenough1');
    req.flush({ response: 'ok' });

    expect(notification.showSuccess).toHaveBeenCalled();
    expect(dialogRef.close).toHaveBeenCalled();
  });

  it('shows the server message when the old password is wrong', () => {
    fill('wrong', 'longenough1', 'longenough1');
    component.attemptSave();
    http.expectOne('/api/password').flush(
      { response: 'Le mot de passe entré est incorrect!' }, { status: 500, statusText: 'Error' });
    expect(notification.showError).toHaveBeenCalledWith('Le mot de passe entré est incorrect!', 'Erreur');
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('blocks characters the server would refuse', () => {
    const allowed = new KeyboardEvent('keypress', { key: 'é', cancelable: true });
    const refused = new KeyboardEvent('keypress', { key: ' ', cancelable: true });
    component.updateCharacters(allowed);
    component.updateCharacters(refused);
    expect(allowed.defaultPrevented).toBeFalse();
    expect(refused.defaultPrevented).toBeTrue();
    // the classical special characters (Bitwarden's set) all pass
    for (const key of '!@#$%^&*.?_-') {
      const event = new KeyboardEvent('keypress', { key, cancelable: true });
      component.updateCharacters(event);
      expect(event.defaultPrevented).withContext(key).toBeFalse();
    }
  });

  it('toggles the password visibility from the icons', () => {
    const icons = fixture.nativeElement.querySelectorAll('mat-icon[matSuffix]') as NodeListOf<HTMLElement>;
    expect(fixture.nativeElement.querySelector('input').type).toBe('password');
    icons[0].click();
    fixture.detectChanges();
    expect(component.hideCurrentPass).toBeFalse();
    expect(fixture.nativeElement.querySelector('input').type).toBe('text');
  });
});

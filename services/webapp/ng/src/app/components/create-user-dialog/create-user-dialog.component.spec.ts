import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';

import { CreateUserDialogComponent } from './create-user-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('CreateUserDialogComponent', () => {
  let fixture: ComponentFixture<CreateUserDialogComponent>;
  let component: CreateUserDialogComponent;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let user: any;

  beforeEach(() => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    user = userServiceStub();
    TestBed.configureTestingModule({
      declarations: [CreateUserDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: user },
      ],
    });
    fixture = TestBed.createComponent(CreateUserDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  const fill = (username: string, pass: string, repeat: string, role: string) => {
    component.username = username;
    component.pass = pass;
    component.passRepeat = repeat;
    component.selected = role;
  };

  it('validates the form before creating the account', () => {
    fill('', 'pw', 'pw', 'Utilisateur');
    component.attemptCreate();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Champ Vide');

    fill('bob', 'S3cret!', 'S3cret!', 'Utilisateur');
    component.attemptCreate();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Avertissement!');

    fill('bob', 'S3cret!!', 'other!!!', 'Utilisateur');
    component.attemptCreate();
    expect(notification.showError).toHaveBeenCalledWith(jasmine.any(String), 'Champs Non Égaux');

    fill('bob', 'S3cret!!', 'S3cret!!', '');
    component.attemptCreate();
    expect(notification.showWarning).toHaveBeenCalledWith(jasmine.any(String), 'Type de Compte');

    expect(user.signup).not.toHaveBeenCalled();
  });

  it('creates the account through the user service and closes', () => {
    fill('bob', 'S3cret!!', 'S3cret!!', 'Administrateur');
    component.attemptCreate();
    expect(user.signup).toHaveBeenCalledWith('bob', 'S3cret!!', 'Administrateur');
    expect(notification.showSuccess).toHaveBeenCalledWith('', 'Compte Créé');
    expect(dialogRef.close).toHaveBeenCalled();
  });

  it('reports the server error and stays open', () => {
    user.signup.and.returnValue(throwError(() => ({ error: { response: "Nom d'utilisateur existant" } })));
    fill('bob', 'S3cret!!', 'S3cret!!', 'Utilisateur');
    component.attemptCreate();
    expect(notification.showError).toHaveBeenCalledWith("Nom d'utilisateur existant", 'Erreur à la création du compte');
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('offers exactly the two roles', () => {
    expect(fixture.nativeElement.querySelector('mat-select')).not.toBeNull();
    expect(component.selected).toBe('');
    user.signup.and.returnValue(of({}));
  });
});

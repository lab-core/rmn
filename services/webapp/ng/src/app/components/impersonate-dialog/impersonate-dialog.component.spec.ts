import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ImpersonateDialogComponent } from './impersonate-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, userServiceStub } from '../../testing/helpers';

describe('ImpersonateDialogComponent', () => {
  let fixture: ComponentFixture<ImpersonateDialogComponent>;
  let component: ImpersonateDialogComponent;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let router: Router;
  let user: any;

  const create = (users: any) => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    user = userServiceStub({
      currentUsername: 'root',
      listUsers: jasmine.createSpy('listUsers').and.returnValue(users),
    });
    TestBed.configureTestingModule({
      declarations: [ImpersonateDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideRouter([]),
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: UserService, useValue: user },
      ],
    });
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(ImpersonateDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  };

  const listed = of({ response: [
    { username: 'alice', role: 'Utilisateur' },
    { username: 'boss', role: 'Administrateur' },
    { username: 'root', role: 'Administrateur' },
  ] });

  it('lists every other user, admins included', () => {
    create(listed);
    expect(component.users.map(u => u.username)).toEqual(['alice', 'boss']);
  });

  it('asks for a user before anything else', async () => {
    create(listed);
    await component.impersonate();
    expect(notification.showWarning).toHaveBeenCalled();
    expect(user.impersonate).not.toHaveBeenCalled();
  });

  it('takes the role, closes and opens the tasks', async () => {
    create(listed);
    component.selected = 'boss';
    await component.impersonate();
    expect(user.impersonate).toHaveBeenCalledWith('boss', jasmine.any(String));
    expect(dialogRef.close).toHaveBeenCalledWith('boss');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
    expect(notification.showInfo).toHaveBeenCalled();
  });

  it('stays open and says why when the server refuses', async () => {
    create(listed);
    user.impersonate.and.rejectWith({ error: { response: 'Error: user alice does not exist.' } });
    component.selected = 'alice';
    await component.impersonate();
    expect(notification.showError).toHaveBeenCalledWith('Error: user alice does not exist.', jasmine.any(String));
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('reports a list it could not load', () => {
    create(throwError(() => ({ error: { response: 'Error: token not valid.' } })));
    expect(component.users).toEqual([]);
    expect(notification.showError).toHaveBeenCalled();
  });
});

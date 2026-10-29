import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AdminPageComponent } from './admin-page.component';
import { AdminService, ManagedUser } from 'src/app/services/admin.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { TemporaryPasswordDialogComponent } from '../temporary-password-dialog/temporary-password-dialog.component';
import { ConfirmDialogComponent } from '../confirm-dialog/confirm-dialog.component';
import { MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, userServiceStub } from '../../testing/helpers';

const row = (username: string, role = 'Utilisateur', extra: Partial<ManagedUser> = {}): ManagedUser => ({
  username, role, managers: [], mustChangePassword: false, lastLogin: null, tasks: 0, ...extra,
});

describe('AdminPageComponent', () => {
  let fixture: ComponentFixture<AdminPageComponent>;
  let component: AdminPageComponent;
  let user: any;
  let admin: jasmine.SpyObj<AdminService>;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialog: MatDialog;
  let router: Router;
  let confirmed: boolean;

  const rows = [
    row('alice', 'Utilisateur', { managers: ['chef'], tasks: 3, lastLogin: '2026-10-28T12:00:00+00:00' }),
    row('chef', 'Gestionnaire'),
    row('new', 'Utilisateur', { mustChangePassword: true }),
    row('root', 'Administrateur'),
  ];

  const create = (role: string, currentUsername = 'root') => {
    user = userServiceStub({
      role, currentUsername,
      listUsers: jasmine.createSpy('listUsers').and.returnValue(of({ response: rows })),
    });
    admin = jasmine.createSpyObj<AdminService>('AdminService', [
      'resetPassword', 'setRole', 'setManagers', 'closeSessions', 'deleteUser',
      'status', 'storageSweep', 'deleteJobs', 'deleteTokens',
    ]);
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [AdminPageComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [
        provideRouter([]),
        { provide: UserService, useValue: user },
        { provide: AdminService, useValue: admin },
        { provide: NotificationService, useValue: notification },
      ],
    });
    dialog = TestBed.inject(MatDialog);
    confirmed = true;
    spyOn(dialog, 'open').and.callFake(((component: any) => ({
      afterClosed: () => of(component === ConfirmDialogComponent ? confirmed : undefined),
    })) as any);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(AdminPageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  };

  const cells = (column: string) =>
    Array.from(fixture.nativeElement.querySelectorAll(`td.mat-column-${column}`)).map((c: any) => c.textContent.trim());

  it('lists the accounts with their logins, tasks and temporary passwords', () => {
    create('Administrateur');
    expect(cells('username').map(c => c.split(' ')[0])).toEqual(['alice', 'chef', 'new', 'root']);
    expect(cells('tasks')).toEqual(['3', '0', '0', '0']);
    expect(cells('lastLogin')[1]).toBe('jamais');
    expect(cells('username')[2]).toContain('mot de passe temporaire');
    expect(component.managers).toEqual(['chef']);
  });

  it('gives an admin every column and every action but on their own row', () => {
    create('Administrateur');
    expect(component.displayedColumns).toContain('managers');
    expect(fixture.nativeElement.querySelector('.views')).not.toBeNull();
    const actionRows = Array.from(fixture.nativeElement.querySelectorAll('td.mat-column-actions')) as HTMLElement[];
    expect(actionRows[0].querySelectorAll('button').length).toBe(4);
    expect(actionRows[3].querySelectorAll('button').length).toBe(0);  // root itself
    // and no role select on their own row
    expect(fixture.nativeElement.querySelectorAll('.role-select').length).toBe(3);
  });

  it('gives a Gestionnaire the reset only, without managers nor system view', () => {
    create('Gestionnaire', 'chef');
    expect(component.displayedColumns).not.toContain('managers');
    expect(fixture.nativeElement.querySelector('.views')).toBeNull();
    expect(fixture.nativeElement.querySelector('.role-select')).toBeNull();
    const first = fixture.nativeElement.querySelector('td.mat-column-actions') as HTMLElement;
    expect(Array.from(first.querySelectorAll('button')).map(b => b.className)).toEqual([jasmine.stringContaining('reset')]);
  });

  it('filters by username', () => {
    create('Administrateur');
    component.applyFilter({ target: { value: ' ALI ' } } as any);
    fixture.detectChanges();
    expect(cells('username').length).toBe(1);
  });

  it('shows the temporary password once the reset is confirmed', async () => {
    create('Administrateur');
    admin.resetPassword.and.returnValue(of({ response: { username: 'alice', password: 'Tmp4x!yZ9qWe' } }));
    await component.resetPassword(rows[0]);
    expect(admin.resetPassword).toHaveBeenCalledWith('alice');
    expect(dialog.open).toHaveBeenCalledWith(TemporaryPasswordDialogComponent, jasmine.objectContaining({
      data: { username: 'alice', password: 'Tmp4x!yZ9qWe' },
    }));
  });

  it('does nothing when the confirmation is declined', async () => {
    create('Administrateur');
    confirmed = false;
    await component.resetPassword(rows[0]);
    await component.deleteUser(rows[0]);
    await component.closeSessions(rows[0]);
    await component.changeRole(rows[0], 'Gestionnaire');
    expect(admin.resetPassword).not.toHaveBeenCalled();
    expect(admin.deleteUser).not.toHaveBeenCalled();
    expect(admin.closeSessions).not.toHaveBeenCalled();
    expect(admin.setRole).not.toHaveBeenCalled();
    // the role select goes back to what the server has
    expect(user.listUsers).toHaveBeenCalledTimes(2);
  });

  it('changes roles and managers, deletes and reloads', async () => {
    create('Administrateur');
    admin.setRole.and.returnValue(of({}));
    admin.setManagers.and.returnValue(of({}));
    admin.deleteUser.and.returnValue(of({}));
    admin.closeSessions.and.returnValue(of({}));
    await component.changeRole(rows[0], 'Gestionnaire');
    expect(admin.setRole).toHaveBeenCalledWith('alice', 'Gestionnaire');
    await component.changeManagers(rows[0], []);
    expect(admin.setManagers).toHaveBeenCalledWith('alice', []);
    await component.closeSessions(rows[0]);
    expect(admin.closeSessions).toHaveBeenCalledWith('alice');
    await component.deleteUser(rows[0]);
    expect(admin.deleteUser).toHaveBeenCalledWith('alice');
    expect(notification.showSuccess).toHaveBeenCalledWith('', 'Compte supprimé');
  });

  it('reports what the server refused', async () => {
    create('Administrateur');
    admin.setRole.and.returnValue(throwError(() => ({ error: { response: 'Error: you cannot change your own role.' } })));
    await component.changeRole(rows[0], 'Gestionnaire');
    expect(notification.showError).toHaveBeenCalledWith('Error: you cannot change your own role.', 'Action refusée');
  });

  it('takes the role of an account and opens its tasks', async () => {
    create('Administrateur');
    await component.impersonate(rows[0]);
    expect(user.impersonate).toHaveBeenCalledWith('alice');
    expect(router.navigate).toHaveBeenCalledWith(['/tasks-history']);
  });

  it('runs the operator commands of the system view', async () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 2 } }));
    admin.storageSweep.and.returnValue(of({
      orphans: [{}], strays: [], empty_jobs: [], bytes: 2048,
      usage: { older_than_days: { '30': { bytes: 10, files: 1 }, '0': { bytes: 20, files: 2 } }, disk: { used: 1, total: 2 } },
    }));
    admin.deleteJobs.and.returnValue(of({ n_deleted_jobs: 4 }));
    admin.deleteTokens.and.returnValue(of({}));

    component.showView('system');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.queue').textContent).toBe('2');

    await component.scanStorage();
    expect(admin.storageSweep).toHaveBeenCalledWith(false);
    expect(component.usageRows().map(r => r.days)).toEqual(['0', '30']);
    await component.cleanStorage();
    expect(admin.storageSweep).toHaveBeenCalledWith(true, false, false);
    expect(notification.showSuccess).toHaveBeenCalledWith('1 élément(s), 2.0 Ko libérés.', 'Stockage nettoyé');

    component.jobDays = 0;
    await component.deleteJobs();
    expect(admin.deleteJobs).not.toHaveBeenCalled();
    component.jobDays = 365;
    await component.deleteJobs();
    expect(admin.deleteJobs).toHaveBeenCalledWith(365);
    await component.deleteTokens();
    expect(admin.deleteTokens).toHaveBeenCalledWith(30);
  });

  it('asks before deleting, in red', async () => {
    create('Administrateur');
    admin.deleteUser.and.returnValue(of({}));
    await component.deleteUser(rows[0]);
    expect(dialog.open).toHaveBeenCalledWith(ConfirmDialogComponent, jasmine.objectContaining({
      data: jasmine.objectContaining({ title: 'Supprimer le compte', danger: true }),
    }));
  });

  it('shows the disk usage as a share', async () => {
    create('Administrateur');
    admin.storageSweep.and.returnValue(of({
      orphans: [], strays: [], empty_jobs: [], bytes: 0,
      usage: { older_than_days: {}, disk: { used: 95, total: 100 } },
    }));
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    component.showView('system');
    await component.scanStorage();
    fixture.detectChanges();
    expect(component.diskPercent()).toBe(95);
    expect(fixture.nativeElement.querySelector('.fill.full')).not.toBeNull();
  });

  it('formats sizes', () => {
    create('Administrateur');
    expect(component.formatBytes(0)).toBe('0 o');
    expect(component.formatBytes(512)).toBe('512 o');
    expect(component.formatBytes(1536 * 1024)).toBe('1.5 Mo');
  });
});

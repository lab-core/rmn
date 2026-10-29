import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AdminPageComponent } from './admin-page.component';
import { AdminService, DigitBankOverview, DigitScores, ManagedUser } from 'src/app/services/admin.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { TemporaryPasswordDialogComponent } from '../temporary-password-dialog/temporary-password-dialog.component';
import { ConfirmDialogComponent } from '../confirm-dialog/confirm-dialog.component';
import { MATERIAL_MODULES, MainMenuStubComponent, notificationSpy, userServiceStub } from '../../testing/helpers';

const scores = (correct: number, n: number): DigitScores => ({
  n, correct, accuracy: n ? correct / n : null,
  per_digit: Array.from({ length: 10 }, (_, d) => ({ n: n / 10, correct: d == 7 ? n / 10 - 2 : n / 10 })),
  per_kind: {}, confusion: [],
});

const overview = (extra: Partial<DigitBankOverview> = {}): DigitBankOverview => ({
  bank: {
    samples: 100, bytes: 2048,
    per_digit: Array.from({ length: 10 }, (_, d) => ({ n: d + 1, read: d + 1, correct: d })),
    per_kind: { matricule: { n: 70, read: 70, correct: 63 }, ink_grade: { n: 30, read: 20, correct: 20 } },
    reading: { n: 100, read: 90, correct: 83 },
    jobs: 3, copies: 12, first: '2026-09-01T10:00:00+00:00', last: '2026-10-01T10:00:00+00:00',
    staged: { jobs: 2, readings: 40 },
  },
  active: null,
  runs: [],
  ...extra,
});

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
      'status', 'settings', 'setSaveVerifiedImages', 'storageSweep', 'deleteJobs', 'deleteTokens',
      'digitBank', 'runDigitModel', 'activateDigitModel',
    ]);
    admin.digitBank.and.returnValue(of({ response: overview() }));
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

  it('takes the role of a user from their row', async () => {
    create('Administrateur');
    const button = fixture.nativeElement.querySelector('td.mat-column-actions .impersonate') as HTMLButtonElement;
    expect(button.textContent).toContain('Prendre le rôle');
    button.click();
    await new Promise(r => setTimeout(r));
    expect(user.impersonate).toHaveBeenCalledWith('alice');
  });

  it('gives a Gestionnaire the reset only, without managers nor system view', () => {
    create('Gestionnaire', 'chef');
    expect(fixture.nativeElement.querySelector('.impersonate')).toBeNull();
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
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
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
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    component.showView('system');
    await component.scanStorage();
    fixture.detectChanges();
    expect(component.diskPercent()).toBe(95);
    expect(fixture.nativeElement.querySelector('.fill.full')).not.toBeNull();
  });

  it('turns the digit bank on and off for everyone', async () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    component.showView('system');
    fixture.detectChanges();
    expect(component.saveVerifiedImages).toBeTrue();
    const toggle = fixture.nativeElement.querySelector('.save-verified-images button[role="switch"]') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-checked')).toBe('true');

    admin.setSaveVerifiedImages.and.returnValue(of({ response: { saveVerifiedImages: false } }));
    await component.setSaveVerifiedImages(false);
    expect(admin.setSaveVerifiedImages).toHaveBeenCalledWith(false);
    expect(component.saveVerifiedImages).toBeFalse();

    // refused: the switch goes back to what the server holds
    admin.setSaveVerifiedImages.and.returnValue(throwError(() => ({ error: { response: 'Error' } })));
    await component.setSaveVerifiedImages(true);
    expect(component.saveVerifiedImages).toBeFalse();
  });

  it('shows what the digit bank holds and how the model in use reads it', () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    admin.digitBank.and.returnValue(of({ response: overview({
      runs: [{
        run_id: 'e1', action: 'evaluate', status: 'DONE', requested_by: 'root', model: null,
        created: '2026-10-29T10:00:00+00:00', finished: '2026-10-29T10:05:00+00:00',
        results: { model: { test: scores(18, 20), bank: scores(95, 100), mnist: scores(990, 1000), model: null } },
      }],
    }) }));
    component.showView('system');
    fixture.detectChanges();

    const page: HTMLElement = fixture.nativeElement;
    const bankTiles = Array.from(page.querySelectorAll('.bank-tiles .value')).map(e => e.textContent);
    expect(bankTiles).toEqual(['100', '12', '40']);
    expect(page.querySelectorAll('.digit-bar').length).toBe(10);
    expect(component.digitBar(9)).toBe(100);
    expect(component.digitBar(0)).toBe(10);
    const kinds = Array.from(page.querySelectorAll('.kinds tr')).map(r =>
      Array.from(r.children).map(c => c.textContent!.trim()).join(' '));
    expect(kinds).toContain('Matricules 70 90,0 %');
    expect(kinds).toContain('Total 100 92,2 %');

    const modelTiles = Array.from(page.querySelectorAll('.model-card .tiles .value')).map(e => e.textContent);
    expect(modelTiles).toEqual(['90,0 %', '95,0 %', '99,0 %']);
    // the shipped model never saw the bank: its digits are scored on all of it
    expect(Array.from(page.querySelectorAll('.per-digit td.weak')).map(c => c.textContent)).toEqual(['80,0 %']);
    expect(page.querySelector('.model-card')!.textContent).toContain('modèle d\'origine');
    expect(page.querySelector('.activate')).toBeNull();
  });

  it('retrains after a confirmation and follows the run until it ends', async () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    jasmine.clock().install();
    try {
      component.showView('system');
      admin.runDigitModel.and.returnValue(of({ response: {} }));
      const running = overview({ runs: [{
        run_id: 't1', action: 'train', status: 'RUNNING', requested_by: 'root',
        created: '2026-10-29T10:00:00+00:00', progress: { epoch: 3, epochs: 10 },
      }] });
      admin.digitBank.and.returnValue(of({ response: running }));

      confirmed = false;
      await component.runDigitModel('train');
      expect(admin.runDigitModel).not.toHaveBeenCalled();

      confirmed = true;
      await component.runDigitModel('train');
      expect(admin.runDigitModel).toHaveBeenCalledWith('train', undefined);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.pending').textContent).toContain('passe 3 sur 10');
      expect(fixture.nativeElement.querySelector('.train').disabled).toBeTrue();

      const calls = admin.digitBank.calls.count();
      jasmine.clock().tick(5001);
      expect(admin.digitBank.calls.count()).toBe(calls + 1);

      // over: no more polling
      admin.digitBank.and.returnValue(of({ response: overview() }));
      jasmine.clock().tick(5001);
      jasmine.clock().tick(5001);
      expect(admin.digitBank.calls.count()).toBe(calls + 2);
      expect(component.pendingRun).toBeUndefined();
    } finally {
      jasmine.clock().uninstall();
    }
  });

  it('activates a trained model and goes back to the shipped one', async () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    const trained = {
      run_id: 't1', action: 'train' as const, status: 'DONE', requested_by: 'root',
      created: '2026-10-29T10:00:00+00:00', finished: '2026-10-29T10:20:00+00:00',
      results: {
        candidate: { test: scores(19, 20), bank: scores(99, 100), mnist: scores(985, 1000) },
        current: { test: scores(17, 20), bank: scores(95, 100), mnist: scores(990, 1000), model: null },
      },
    };
    admin.digitBank.and.returnValue(of({ response: overview({ runs: [trained] }) }));
    component.showView('system');
    fixture.detectChanges();
    const runRow = fixture.nativeElement.querySelector('.runs tr:nth-child(2)').textContent;
    expect(runRow).toContain('95,0 %');
    expect(runRow).toContain('contre 85,0 %');
    expect(fixture.nativeElement.querySelector('.runs .better')).not.toBeNull();

    const active = { run_id: 't1', activated_at: '2026-10-29T10:30:00+00:00', activated_by: 'root' };
    admin.activateDigitModel.and.returnValue(of({ response: overview({ runs: [trained], active }) }));
    await component.activateDigitModel(trained);
    expect(admin.activateDigitModel).toHaveBeenCalledWith('t1');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.in-service')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.activate')).toBeNull();

    admin.activateDigitModel.and.returnValue(of({ response: overview({ runs: [trained] }) }));
    await component.activateDigitModel(null);
    expect(admin.activateDigitModel).toHaveBeenCalledWith('');
    expect(component.digitBank!.active).toBeNull();
  });

  it('opens the details of a run on a click and re-evaluates its model', async () => {
    create('Administrateur');
    admin.status.and.returnValue(of({ response: { queue: 0 } }));
    admin.settings.and.returnValue(of({ response: { saveVerifiedImages: true } }));
    const confusion: number[][] = Array.from({ length: 10 }, (_, d) => Array.from({ length: 10 }, (_, r) => r == d ? 2 : 0));
    confusion[7][1] = 3;
    confusion[4][9] = 1;
    const candidate = { ...scores(19, 20), confusion, per_kind: { matricule: { n: 20, correct: 19 } } };
    const trained = {
      run_id: 't1', action: 'train' as const, status: 'DONE', requested_by: 'root',
      created: '2026-10-29T10:00:00+00:00', finished: '2026-10-29T10:20:00+00:00',
      bank: { samples: 100, train: 80, test: 20 },
      results: {
        candidate: { test: candidate, bank: scores(99, 100), mnist: scores(985, 1000), model: 't1' },
        current: { test: scores(17, 20), bank: scores(95, 100), mnist: scores(990, 1000), model: null },
      },
    };
    const evaluation = {
      run_id: 'e1', action: 'evaluate' as const, status: 'DONE', requested_by: 'root', target: 't1', model: 't1',
      created: '2026-10-29T11:00:00+00:00', finished: '2026-10-29T11:01:00+00:00',
      results: { model: { test: scores(19, 20), bank: scores(99, 100), mnist: scores(985, 1000), model: 't1' } },
    };
    admin.digitBank.and.returnValue(of({ response: overview({ runs: [evaluation, trained] }) }));
    component.showView('system');
    fixture.detectChanges();
    const page: HTMLElement = fixture.nativeElement;
    expect(page.querySelector('.run-details')).toBeNull();
    // an evaluation of a trained model says which one
    expect(page.querySelector('.run-row')!.textContent).toContain('Évaluation, entraînement du');

    (page.querySelectorAll('.run-row')[1] as HTMLElement).click();
    fixture.detectChanges();
    const details = page.querySelector('.run-details') as HTMLElement;
    const header = Array.from(details.querySelectorAll('.compare th')).map(c => c.textContent!.trim());
    expect(header).toEqual(['Bien reconnus', 'Nouveau modèle', 'En service (modèle d\'origine)']);
    expect(details.querySelector('.compare')!.textContent).toContain('(19/20)');
    expect(Array.from(details.querySelectorAll('.confusion')).map(c => c.textContent)).toEqual(['7 lu 1 × 3', '4 lu 9 × 1']);
    expect(details.textContent).toContain('80 d\'entraînement et 20 de test');

    admin.runDigitModel.and.returnValue(of({ response: {} }));
    (details.querySelector('.reevaluate') as HTMLButtonElement).click();
    await fixture.whenStable();
    expect(admin.runDigitModel).toHaveBeenCalledWith('evaluate', 't1');
    expect(dialog.open).not.toHaveBeenCalled();

    // the activate button of the row does not toggle the details
    (page.querySelector('.runs .activate') as HTMLButtonElement).click();
    expect(component.selectedRunId).toBe('t1');
    (page.querySelector('.close-details') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(page.querySelector('.run-details')).toBeNull();
  });

  it('formats sizes', () => {
    create('Administrateur');
    expect(component.formatBytes(0)).toBe('0 o');
    expect(component.formatBytes(512)).toBe('512 o');
    expect(component.formatBytes(1536 * 1024)).toBe('1.5 Mo');
  });
});

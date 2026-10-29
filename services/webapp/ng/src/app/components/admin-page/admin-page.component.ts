import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatTableDataSource } from '@angular/material/table';
import { Router } from '@angular/router';
import { firstValueFrom, Observable } from 'rxjs';
import { AdminService, ManagedUser } from 'src/app/services/admin.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { UserRole } from '../../generated/rmn-contracts';
import { CreateUserDialogComponent } from '../create-user-dialog/create-user-dialog.component';
import { TemporaryPasswordDialogComponent } from '../temporary-password-dialog/temporary-password-dialog.component';
import { WarningDialogComponent } from '../warning-dialog/warning-dialog.component';

/** The admin page: the accounts a Gestionnaire manages (every account for an
 *  Administrateur) and, for an Administrateur, the operator commands. */
@Component({
    selector: 'app-admin-page',
    templateUrl: './admin-page.component.html',
    styleUrls: ['./admin-page.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class AdminPageComponent implements OnInit {
  readonly UserRole = UserRole;
  readonly roles = [UserRole.USER, UserRole.MANAGER, UserRole.ADMIN];
  readonly dataSource = new MatTableDataSource<ManagedUser>([]);
  /** The Gestionnaires an admin can put in charge of an account. */
  managers: string[] = [];
  view: 'users' | 'system' = 'users';

  queue: number | undefined;
  storageReport: any;
  sweeping = false;
  includeStrays = false;
  includeEmptyJobs = false;
  jobDays = 365;
  tokenDays = 30;

  constructor(public userService: UserService,
              private adminService: AdminService,
              private notification: NotificationService,
              private dialog: MatDialog,
              private router: Router) { }

  ngOnInit(): void {
    this.dataSource.filterPredicate = (row, filter) => row.username.toLowerCase().includes(filter);
    this.loadUsers();
  }

  get isAdmin(): boolean {
    return this.userService.isAdmin();
  }

  get displayedColumns(): string[] {
    return this.isAdmin
      ? ['username', 'role', 'managers', 'lastLogin', 'tasks', 'actions']
      : ['username', 'role', 'lastLogin', 'tasks', 'actions'];
  }

  isSelf(row: ManagedUser): boolean {
    return row.username == this.userService.currentUsername;
  }

  applyFilter(event: Event) {
    this.dataSource.filter = (event.target as HTMLInputElement).value.trim().toLowerCase();
  }

  showView(view: 'users' | 'system') {
    this.view = view;
    if (view == 'system' && this.queue === undefined) {
      this.loadStatus();
    }
  }

  loadUsers() {
    this.userService.listUsers().subscribe({
      next: (resp) => {
        const rows: ManagedUser[] = resp['response'];
        this.dataSource.data = rows;
        this.managers = rows.filter(u => u.role == UserRole.MANAGER).map(u => u.username);
      },
      error: (err) => this.fail(err, 'Erreur au chargement des comptes'),
    });
  }

  private confirm(message: string): Promise<boolean> {
    const dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '80%',
      maxWidth: '500px',
      data: message,
    });
    return firstValueFrom(dialogRef.afterClosed()).then(result => !!result);
  }

  private fail(err: any, title: string) {
    this.notification.showError(err?.error?.response, title);
  }

  /** Run an action, say it worked and reload the accounts; say why it failed otherwise. */
  private async run(action: Observable<any>, success: string, reload = true): Promise<any> {
    try {
      const resp = await firstValueFrom(action);
      if (success) {
        this.notification.showSuccess('', success);
      }
      return resp;
    } catch (err) {
      this.fail(err, 'Action refusée');
      return undefined;
    } finally {
      if (reload) {
        this.loadUsers();
      }
    }
  }

  createUser() {
    const dialogRef = this.dialog.open(CreateUserDialogComponent, {
      width: '80%',
      maxWidth: '600px',
    });
    dialogRef.afterClosed().subscribe(() => this.loadUsers());
  }

  async resetPassword(row: ManagedUser) {
    if (!await this.confirm(`Réinitialiser le mot de passe de ${row.username} ? Ses sessions seront fermées.`)) {
      return;
    }
    const resp = await this.run(this.adminService.resetPassword(row.username), '');
    if (resp) {
      this.dialog.open(TemporaryPasswordDialogComponent, {
        width: '80%',
        maxWidth: '500px',
        data: resp['response'],
      });
    }
  }

  async changeRole(row: ManagedUser, role: string) {
    if (!await this.confirm(`Donner le rôle ${role} à ${row.username} ? Ses sessions seront fermées.`)) {
      this.loadUsers();  // put the select back
      return;
    }
    await this.run(this.adminService.setRole(row.username, role), 'Rôle modifié');
  }

  async changeManagers(row: ManagedUser, managers: string[]) {
    await this.run(this.adminService.setManagers(row.username, managers), 'Gestionnaires modifiés');
  }

  async closeSessions(row: ManagedUser) {
    if (await this.confirm(`Déconnecter ${row.username} de toutes ses sessions ?`)) {
      await this.run(this.adminService.closeSessions(row.username), 'Sessions fermées', false);
    }
  }

  async deleteUser(row: ManagedUser) {
    const tasks = row.tasks ? ` et ses ${row.tasks} tâche(s)` : '';
    if (await this.confirm(`Supprimer définitivement le compte ${row.username}${tasks} ?`)) {
      await this.run(this.adminService.deleteUser(row.username), 'Compte supprimé');
    }
  }

  async impersonate(row: ManagedUser) {
    try {
      await this.userService.impersonate(row.username);
    } catch (err) {
      this.fail(err, 'Impossible de prendre le rôle');
      return;
    }
    this.notification.showInfo(`Vous agissez maintenant en tant que ${row.username}.`, 'Rôle pris');
    this.router.navigate(['/tasks-history']);
  }

  loadStatus() {
    this.adminService.status().subscribe({
      next: (resp) => this.queue = resp['response']['queue'],
      error: (err) => this.fail(err, 'État indisponible'),
    });
  }

  async wakeExecutor() {
    await this.run(this.adminService.wakeExecutor(), 'Executor relancé', false);
    this.loadStatus();
  }

  async scanStorage() {
    this.sweeping = true;
    this.storageReport = await this.run(this.adminService.storageSweep(false), '', false);
    this.sweeping = false;
  }

  async cleanStorage() {
    if (!await this.confirm('Supprimer les fichiers que plus aucune tâche ni template ne possède ?')) {
      return;
    }
    this.sweeping = true;
    const resp = await this.run(
      this.adminService.storageSweep(true, this.includeStrays, this.includeEmptyJobs), '', false);
    this.sweeping = false;
    if (resp) {
      this.notification.showSuccess(
        `${resp['orphans'].length} élément(s), ${this.formatBytes(resp['bytes'])} libérés.`, 'Stockage nettoyé');
      this.storageReport = undefined;
    }
  }

  async deleteJobs() {
    if (!this.jobDays || this.jobDays < 1) {
      this.notification.showWarning('Indiquez un âge d\'au moins 1 jour.', 'Âge');
      return;
    }
    if (!await this.confirm(`Supprimer les tâches de TOUS les utilisateurs ajoutées il y a ${this.jobDays} jours ou plus ?`)) {
      return;
    }
    const resp = await this.run(this.adminService.deleteJobs(this.jobDays), '');
    if (resp) {
      this.notification.showSuccess(`${resp['n_deleted_jobs']} tâche(s) supprimée(s).`, 'Tâches supprimées');
    }
  }

  async deleteTokens() {
    if (!this.tokenDays || this.tokenDays < 1) {
      this.notification.showWarning('Indiquez un âge d\'au moins 1 jour.', 'Âge');
      return;
    }
    if (await this.confirm(`Fermer les sessions ouvertes il y a ${this.tokenDays} jours ou plus ?`)) {
      await this.run(this.adminService.deleteTokens(this.tokenDays), 'Sessions fermées', false);
    }
  }

  /** The usage buckets of the storage report, oldest threshold last. */
  usageRows(): { days: string, bytes: number, files: number }[] {
    const buckets = this.storageReport?.usage?.older_than_days ?? {};
    return Object.keys(buckets)
      .sort((a, b) => Number(a) - Number(b))
      .map(days => ({ days, ...buckets[days] }));
  }

  formatBytes(bytes: number): string {
    if (!bytes) {
      return '0 o';
    }
    const units = ['o', 'Ko', 'Mo', 'Go', 'To'];
    const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
  }
}

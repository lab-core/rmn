import { Component, OnInit, OnDestroy, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatTableDataSource } from '@angular/material/table';
import { Router } from '@angular/router';
import { firstValueFrom, Observable } from 'rxjs';
import {
  AdminService, DigitBankOverview, DigitCount, DigitModelRun, DigitScores, ManagedUser, ModelScores,
} from 'src/app/services/admin.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { DigitModelStatus, UserRole } from '../../generated/rmn-contracts';
import { CreateUserDialogComponent } from '../create-user-dialog/create-user-dialog.component';
import { TemporaryPasswordDialogComponent } from '../temporary-password-dialog/temporary-password-dialog.component';
import { ConfirmData, ConfirmDialogComponent } from '../confirm-dialog/confirm-dialog.component';

/** The admin page: the accounts a Gestionnaire manages (every account for an
 *  Administrateur) and, for an Administrateur, the operator commands. */
@Component({
    selector: 'app-admin-page',
    templateUrl: './admin-page.component.html',
    styleUrls: ['./admin-page.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class AdminPageComponent implements OnInit, OnDestroy {
  readonly UserRole = UserRole;
  readonly roles = [UserRole.USER, UserRole.MANAGER, UserRole.ADMIN];
  readonly dataSource = new MatTableDataSource<ManagedUser>([]);
  /** The Gestionnaires an admin can put in charge of an account. */
  managers: string[] = [];
  view: 'users' | 'system' = 'users';

  queue: number | undefined;
  /** The digit bank switch, undefined until the server answered. */
  saveVerifiedImages: boolean | undefined;
  /** The digit bank, the model in use and the trainer's runs. */
  digitBank: DigitBankOverview | undefined;
  readonly digits = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  /** The kinds of numbers the bank's digits are cut from, as the page names them. */
  readonly kinds: { key: string, label: string }[] = [
    { key: 'matricule', label: 'Matricules' },
    { key: 'grade_box', label: 'Cases de note' },
    { key: 'ink_grade', label: 'Notes manuscrites' },
  ];
  private digitBankTimer: ReturnType<typeof setTimeout> | undefined;
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

  ngOnDestroy(): void {
    clearTimeout(this.digitBankTimer);
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
    if (view != 'system') {
      clearTimeout(this.digitBankTimer);
    } else if (this.pendingRun) {
      this.loadDigitBank();
    }
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

  private confirm(data: ConfirmData): Promise<boolean> {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      width: '80%',
      maxWidth: '480px',
      data,
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
    if (!await this.confirm({
      title: 'Réinitialiser le mot de passe',
      message: `${row.username} recevra un mot de passe temporaire à changer à sa prochaine connexion. Ses sessions ouvertes seront fermées.`,
      confirm: 'Réinitialiser',
    })) {
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
    if (!await this.confirm({
      title: 'Changer le rôle',
      message: `${row.username} deviendra ${role}. Ses sessions ouvertes seront fermées.`,
      confirm: 'Changer',
    })) {
      this.loadUsers();  // put the select back
      return;
    }
    await this.run(this.adminService.setRole(row.username, role), 'Rôle modifié');
  }

  async changeManagers(row: ManagedUser, managers: string[]) {
    await this.run(this.adminService.setManagers(row.username, managers), 'Gestionnaires modifiés');
  }

  async closeSessions(row: ManagedUser) {
    if (await this.confirm({
      title: 'Fermer les sessions',
      message: `${row.username} sera déconnecté de tous ses appareils.`,
      confirm: 'Déconnecter',
    })) {
      await this.run(this.adminService.closeSessions(row.username), 'Sessions fermées', false);
    }
  }

  async deleteUser(row: ManagedUser) {
    const tasks = row.tasks ? `, ses ${row.tasks} tâche(s)` : '';
    if (await this.confirm({
      title: 'Supprimer le compte',
      message: `Le compte ${row.username}${tasks} et ses templates seront supprimés définitivement.`,
      confirm: 'Supprimer',
      danger: true,
    })) {
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
    this.adminService.settings().subscribe({
      next: (resp) => this.saveVerifiedImages = resp['response']['saveVerifiedImages'],
      error: (err) => this.fail(err, 'Réglages indisponibles'),
    });
    this.loadDigitBank();
  }

  /** The bank and the runs; again in a few seconds while a run is not over. */
  loadDigitBank() {
    clearTimeout(this.digitBankTimer);
    this.adminService.digitBank().subscribe({
      next: (resp) => this.showDigitBank(resp.response),
      error: (err) => this.fail(err, 'Banque de chiffres indisponible'),
    });
  }

  private showDigitBank(overview: DigitBankOverview) {
    this.digitBank = overview;
    clearTimeout(this.digitBankTimer);
    if (this.pendingRun && this.view == 'system') {
      this.digitBankTimer = setTimeout(() => this.loadDigitBank(), 5000);
    }
  }

  /** The run the trainer has not finished, if any: one at a time. */
  get pendingRun(): DigitModelRun | undefined {
    return this.digitBank?.runs.find(r =>
      r.status == DigitModelStatus.QUEUED || r.status == DigitModelStatus.RUNNING);
  }

  /** The latest finished evaluation of the model in use. */
  get currentEvaluation(): DigitModelRun | undefined {
    const active = this.digitBank?.active?.run_id ?? null;
    return this.digitBank?.runs.find(r =>
      r.action == 'evaluate' && r.status == DigitModelStatus.DONE && (r.model ?? null) == active);
  }

  /** The digits a model's per-digit scores are given on: the whole bank for the
   *  shipped model, which never saw it, the test part for a retrained one. */
  fairScores(scores: ModelScores | undefined): DigitScores | undefined {
    if (!scores) {
      return undefined;
    }
    return scores.model ? scores.test : scores.bank;
  }

  isActive(run: DigitModelRun): boolean {
    return this.digitBank?.active?.run_id == run.run_id;
  }

  async runDigitModel(action: 'train' | 'evaluate') {
    if (action == 'train' && !await this.confirm({
      title: 'Réentraîner la lecture des chiffres',
      message: 'Le modèle d\'origine est réentraîné sur la banque, ce qui prend quelques minutes. '
        + 'Le nouveau modèle n\'est pas mis en service : comparez ses scores, puis activez-le.',
      confirm: 'Réentraîner',
    })) {
      return;
    }
    const resp = await this.run(this.adminService.runDigitModel(action),
      action == 'train' ? 'Entraînement demandé' : 'Évaluation demandée', false);
    if (resp) {
      this.loadDigitBank();
    }
  }

  async activateDigitModel(run: DigitModelRun | null) {
    if (!await this.confirm({
      title: run ? 'Mettre ce modèle en service' : 'Revenir au modèle d\'origine',
      message: (run
        ? `Les prochaines lectures de matricules et de notes utiliseront le modèle entraîné le ${this.formatDate(run.finished)}.`
        : 'Les prochaines lectures de matricules et de notes utiliseront le modèle livré avec rmn.')
        + ' Les lectures déjà faites ne changent pas.',
      confirm: 'Activer',
    })) {
      return;
    }
    const resp = await this.run(this.adminService.activateDigitModel(run?.run_id ?? ''),
      'Modèle de lecture changé', false);
    if (resp) {
      this.showDigitBank(resp.response);
    }
  }

  /** A share as a percentage, '—' when there is nothing to divide. */
  percent(part: number | undefined | null, whole: number | undefined | null): string {
    if (!whole || part == null) {
      return '—';
    }
    return `${(100 * part / whole).toFixed(1).replace('.', ',')} %`;
  }

  score(scores: DigitScores | undefined): string {
    return scores ? this.percent(scores.correct, scores.n) : '—';
  }

  readingShare(count: DigitCount | undefined): string {
    return count ? this.percent(count.correct, count.read) : '—';
  }

  /** Height of a digit's bar, against the digit the bank holds most of. */
  digitBar(digit: number): number {
    const counts = this.digitBank?.bank.per_digit.map(d => d.n) ?? [];
    const most = Math.max(...counts, 1);
    return Math.round(100 * (counts[digit] ?? 0) / most);
  }

  formatDate(iso: string | null | undefined): string {
    if (!iso) {
      return '—';
    }
    return new Date(iso).toLocaleString('fr-CA', {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  }

  async setSaveVerifiedImages(on: boolean) {
    const resp = await this.run(this.adminService.setSaveVerifiedImages(on),
      on ? 'Les chiffres validés sont conservés' : 'Les chiffres validés ne sont plus conservés', false);
    // what the server holds, also when it refused
    this.saveVerifiedImages = resp ? resp['response']['saveVerifiedImages'] : !on;
  }

  async scanStorage() {
    this.sweeping = true;
    this.storageReport = await this.run(this.adminService.storageSweep(false), '', false);
    this.sweeping = false;
  }

  async cleanStorage() {
    if (!await this.confirm({
      title: 'Nettoyer le stockage',
      message: 'Les fichiers que plus aucune tâche ni aucun template ne possède seront supprimés'
        + (this.includeStrays ? ', ainsi que les fichiers inconnus' : '')
        + (this.includeEmptyJobs ? ', ainsi que les tâches sans fichier' : '') + '.',
      confirm: 'Nettoyer',
      danger: true,
    })) {
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
    if (!await this.confirm({
      title: 'Supprimer les anciennes tâches',
      message: `Les tâches de tous les utilisateurs ajoutées il y a ${this.jobDays} jours ou plus seront supprimées définitivement, avec leurs copies.`,
      confirm: 'Supprimer',
      danger: true,
    })) {
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
    if (await this.confirm({
      title: 'Fermer les anciennes sessions',
      message: `Les sessions ouvertes il y a ${this.tokenDays} jours ou plus seront fermées : leurs utilisateurs devront se reconnecter.`,
      confirm: 'Fermer',
    })) {
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

  /** The share of the disk in use, in percent. */
  diskPercent(): number {
    const disk = this.storageReport?.usage?.disk;
    return disk?.total ? Math.round(100 * disk.used / disk.total) : 0;
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

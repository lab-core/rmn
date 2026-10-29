import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { Router } from '@angular/router';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { NotificationService } from 'src/app/services/notification.service';

@Component({
    selector: 'app-main-menu',
    templateUrl: './main-menu.component.html',
    styleUrls: ['./main-menu.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class MainMenuComponent implements OnInit {

  constructor(
    private router: Router,
    private userService: UserService,
    private notificationService: NotificationService
  ) { }


  async ngOnInit(): Promise<void> {}

  /** The admin behind this session, when it was opened in a user's place. */
  get impersonatedBy(): string | undefined {
    return this.userService.impersonatedBy;
  }

  get currentUsername(): string {
    return this.userService.currentUsername;
  }

  stopImpersonating(): void {
    const admin = this.userService.impersonatedBy;
    this.userService.stopImpersonating();
    // a role is only taken from the admin page
    this.router.navigate(['/admin']);
    this.notificationService.showInfo("", `De retour en tant que ${admin}`)
  }

  disconnect(): void {
    this.userService.logout()
    this.router.navigate(['/login']);
    this.notificationService.showInfo("", "Déconnecté!")
  }

  newCorrection(): void {
    this.router.navigate(['/new-correction']);
  }

  newExamCorrection(): void {
    this.router.navigate(['/new-exam-correction']);
  }

  goToTasksHistory(): void {
    this.router.navigate(['/tasks-history']);
  }

  goToTemplatesPage(): void {
    this.router.navigate(['/templates']);
  }

  goToPresentationPage(): void {
    this.router.navigate(['/presentation-page']);
  }

  /** Gestionnaires and Administrateurs get the admin page. */
  get canManage(): boolean {
    return this.userService.canCreateUsers();
  }

  goToAdminPage(): void {
    this.router.navigate(['/admin']);
  }

  goToProfilePage(): void {
    this.router.navigate(['/user-profile']);
  }

  goToUserGuide(): void {
    this.router.navigate(['/user-guide']);
  }

}

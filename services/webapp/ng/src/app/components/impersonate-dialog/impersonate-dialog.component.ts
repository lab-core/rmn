import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { first } from 'rxjs/operators';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';

/** An admin picks a user (admins included) and continues as them, with all their rights. */
@Component({
    selector: 'app-impersonate-dialog',
    templateUrl: './impersonate-dialog.component.html',
    styleUrls: ['./impersonate-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ImpersonateDialogComponent implements OnInit {
  users: { username: string, role: string }[] = [];
  selected: string = '';

  constructor(
    public notification: NotificationService,
    public dialogRef: MatDialogRef<ImpersonateDialogComponent>,
    private userService: UserService,
    private router: Router
  ) {
  }

  ngOnInit(): void {
    this.userService.listUsers().pipe(first()).subscribe((resp) => {
      // the current user is the one place there is no point going
      this.users = resp['response'].filter(u => u.username != this.userService.currentUsername);
    }, (err) => {
      this.notification.showError(err.error?.response, "Erreur au chargement des utilisateurs");
    });
  }

  async impersonate() {
    if (this.selected == '') {
      this.notification.showWarning("Veuillez choisir un utilisateur!", "Utilisateur");
      return;
    }
    try {
      await this.userService.impersonate(this.selected);
    } catch (err) {
      this.notification.showError(err.error?.response, "Impossible de prendre le rôle");
      return;
    }
    this.dialogRef.close(this.selected);
    this.notification.showInfo(`Vous agissez maintenant en tant que ${this.selected}.`, "Rôle pris");
    this.router.navigate(['/tasks-history']);
  }
}

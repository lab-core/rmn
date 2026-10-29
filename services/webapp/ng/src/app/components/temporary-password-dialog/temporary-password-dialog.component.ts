import { Component, ChangeDetectionStrategy, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';

/** Shows the temporary password of a reset: the only time anyone sees it. */
@Component({
    selector: 'app-temporary-password-dialog',
    templateUrl: './temporary-password-dialog.component.html',
    styleUrls: ['./temporary-password-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TemporaryPasswordDialogComponent {

  constructor(public dialogRef: MatDialogRef<TemporaryPasswordDialogComponent>,
              private notification: NotificationService,
              @Inject(MAT_DIALOG_DATA) public data: { username: string, password: string }) { }

  async copy() {
    try {
      await navigator.clipboard.writeText(this.data.password);
      this.notification.showSuccess('', 'Mot de passe copié');
    } catch {
      this.notification.showWarning('Sélectionnez-le et copiez-le à la main.', 'Copie impossible');
    }
  }
}

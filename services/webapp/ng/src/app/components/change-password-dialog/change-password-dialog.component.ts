import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL, PASSWORD_CHARACTER_REGEX, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, passwordError } from 'src/app/utils';
import { first } from 'rxjs/operators';

@Component({
    selector: 'app-change-password-dialog',
    templateUrl: './change-password-dialog.component.html',
    styleUrls: ['./change-password-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ChangePasswordDialogComponent implements OnInit {
  readonly passwordMinLength = PASSWORD_MIN_LENGTH;
  readonly passwordMaxLength = PASSWORD_MAX_LENGTH;
  newPass: string = '';
  newPassRepeat: string = '';
  currentPass: string = '';
  hideCurrentPass: boolean = true;
  hideNewPass: boolean = true;
  hideNewPass2: boolean = true;


  constructor(public notification: NotificationService, public dialogRef: MatDialogRef<ChangePasswordDialogComponent>, public userService: UserService, private http: HttpClient,) {
   }

  ngOnInit(): void {
  }

  updateCharacters(event: KeyboardEvent) {
    if (!PASSWORD_CHARACTER_REGEX.test(event.key)) {
      event.preventDefault();
   }
  }

  attemptSave() {
    if(this.newPass.length == 0 || this.newPassRepeat.length == 0 || this.currentPass.length == 0) {
      this.notification.showWarning("Veuillez remplir le(s) champ(s) vide(s)!", "Champ Vide");
    } else if (passwordError(this.newPass)) {
      // length and characters: the server's rules, checked before sending
      this.notification.showWarning(passwordError(this.newPass), "Avertissement!");
    }
    else if (this.newPass != this.newPassRepeat) {
      this.notification.showError("Votre nouveau mot de passe ne concordre pas à celui répété!", "Champs Non Égaux");
    } else {

      const formdata: FormData = new FormData();
      formdata.append('username', this.userService.currentUsername);
      this.userService.addTokens(formdata);
      formdata.append('new_password', this.newPass);
      formdata.append('old_password', this.currentPass)
      const url = SERVER_URL + 'users/password';

      this.http.post<any>(url, formdata).pipe(first()).subscribe(
        (data) => {
          this.notification.showSuccess('Le mot de passe entré a été changé!', 'Succès');

          this.dialogRef.close('');
        },
        (error) => {
          const errorResponse = error['error']['response']

          this.notification.showError(errorResponse != null? errorResponse : "Erreur lors du changement de mot de passe", 'Erreur')
        });

    }
  }

}

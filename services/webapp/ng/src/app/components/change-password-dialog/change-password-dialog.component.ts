import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { first } from 'rxjs/operators';

@Component({
  selector: 'app-change-password-dialog',
  templateUrl: './change-password-dialog.component.html',
  styleUrls: ['./change-password-dialog.component.css']
})
export class ChangePasswordDialogComponent implements OnInit {
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
    const regex = new RegExp("^[a-zA-ZÀ-ÿ0-9.@!#%$?_-]+$");
    if (!regex.test(event.key)) {
      event.preventDefault();
   }
  }

  attemptSave() {
    if(this.newPass.length == 0 || this.newPassRepeat.length == 0 || this.currentPass.length == 0) {
      this.notification.showWarning("Veuillez remplir le(s) champ(s) vide(s)!", "Champ Vide");
    } else if(this.newPass.length < 8 || this.newPassRepeat.length < 8 ) {
      this.notification.showWarning("Veuillez entrer au minimum 8 caractères!", "Avertissement!");
    }
    else if (this.newPass != this.newPassRepeat) {
      this.notification.showError("Votre nouveau mot de passe ne concordre pas à celui répété!", "Champs Non Égaux");
    } else {

      const formdata: FormData = new FormData();
      formdata.append('username', this.userService.currentUsername);
      this.userService.addTokens(formdata);
      formdata.append('new_password', this.newPass);
      formdata.append('old_password', this.currentPass)
      const url = SERVER_URL + 'password';

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

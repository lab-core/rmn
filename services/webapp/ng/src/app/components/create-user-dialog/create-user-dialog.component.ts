import { PASSWORD_CHARACTER_REGEX, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, passwordError } from 'src/app/utils';
import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { first } from 'rxjs/operators';
import { UserRole } from '../../generated/rmn-contracts';

@Component({
    selector: 'app-create-user-dialog',
    templateUrl: './create-user-dialog.component.html',
    styleUrls: ['./create-user-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class CreateUserDialogComponent implements OnInit {
  readonly UserRole = UserRole;
  username: string = '';
  readonly passwordMinLength = PASSWORD_MIN_LENGTH;
  readonly passwordMaxLength = PASSWORD_MAX_LENGTH;
  pass: string = '';
  passRepeat: string = '';
  selected: string = '';
  hideNewPass: boolean = true;
  hideNewPass2: boolean = true;

  constructor(
    public notification: NotificationService,
    public dialogRef: MatDialogRef<CreateUserDialogComponent>,
    private userService: UserService
  ) {
  }

  ngOnInit(): void {
  }

  updateCharacters(event: KeyboardEvent) {
    if (!PASSWORD_CHARACTER_REGEX.test(event.key)) {
      event.preventDefault();
    }
  }

  attemptCreate() {
    if (this.username.length == 0 || this.pass.length == 0 || this.passRepeat.length == 0) {
      this.notification.showWarning("Veuillez remplir le(s) champ(s) vide(s)!", "Champ Vide");
    }
    else if (passwordError(this.pass)) {
      // length and characters: the server's rules, checked before sending
      this.notification.showWarning(passwordError(this.pass), "Avertissement!");
    }
    else if (this.pass != this.passRepeat) {
      this.notification.showError("Votre mot de passe ne concordre pas à celui répété!", "Champs Non Égaux");
    }
    else if (this.selected == '') {
      this.notification.showWarning("Veuillez choisir le type de compte!", "Type de Compte");
    } else {
      this.createAccount()
    }
  }

  private createAccount() {
    this.userService.signup(this.username, this.pass, this.selected).pipe(first()).subscribe((resp) => {
      this.notification.showSuccess("", "Compte Créé")
      this.dialogRef.close('');

    }, (err) => {
      this.notification.showError(err.error.response, "Erreur à la création du compte")

    }
    )
  }

}

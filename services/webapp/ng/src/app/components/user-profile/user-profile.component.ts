import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { ChangePasswordDialogComponent } from '../change-password-dialog/change-password-dialog.component';
import { CreateUserDialogComponent } from '../create-user-dialog/create-user-dialog.component';
import { first } from 'rxjs/operators';

@Component({
    selector: 'app-user-profile',
    templateUrl: './user-profile.component.html',
    styleUrls: ['./user-profile.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class UserProfileComponent implements OnInit {

  constructor(public dialog: MatDialog,
    public userService: UserService,
    public router: Router) { }

  ngOnInit(): void {
  }



  openChangePasswordDialog(): void {
    const dialogRef = this.dialog.open(ChangePasswordDialogComponent, {
        width: '80%',
        maxWidth: '400px',
        height: '60%'
      })
  }

  openCreateUserDialog(): void {
    const dialogRef = this.dialog.open(CreateUserDialogComponent, {
      width: '80%',
      maxWidth: '600px',
      height: '73%'
    })
  }

  updateSaveVerifiedImagesValue(saveVerifiedImages: boolean): void {
    this.userService.updateSaveVerifiedImagesValue(saveVerifiedImages).pipe(first()).subscribe(
      (data) => {
        this.userService.saveVerifiedImages = saveVerifiedImages;
        localStorage.setItem('saveVerifiedImages', JSON.stringify(saveVerifiedImages))

      }
    );
  }

  updateSaveInMoodleStructure(moodleStructureInd: boolean): void {
    this.userService.updateMoodleStructureInd(moodleStructureInd).pipe(first()).subscribe(
      (data) => {
        this.userService.moodleStructureInd = moodleStructureInd;
        localStorage.setItem('moodleStructureInd', JSON.stringify(moodleStructureInd))


      }
    );
  }

  reroute() {
    this.router.navigate(['/main-menu']);
  }
}

import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { ChangePasswordDialogComponent } from './change-password-dialog/change-password-dialog.component';
import { CreateUserDialogComponent } from './create-user-dialog/create-user-dialog.component';

@Component({
  selector: 'app-user-profile',
  templateUrl: './user-profile.component.html',
  styleUrls: ['./user-profile.component.css']
})
export class UserProfileComponent implements OnInit {

  constructor(public dialog: MatDialog,
    public userService: UserService,
    public router: Router) { }

  ngOnInit(): void {
  }



  openChangePasswordDialog(): void {
    let dialogRef = this.dialog.open(ChangePasswordDialogComponent, {
        width: '30%',
        height: '60%'
      })

  }

  openCreateUserDialog(): void {
    let dialogRef = this.dialog.open(CreateUserDialogComponent, {
      width: '30%',
      height: '73%'
    })

  }

  updateSaveVerifiedImagesValue(saveVerifiedImages: boolean): void {
    this.userService.updateSaveVerifiedImagesValue(saveVerifiedImages).subscribe(
      (data) => {
        this.userService.saveVerifiedImages = saveVerifiedImages;
        localStorage.setItem('saveVerifiedImages', JSON.stringify(saveVerifiedImages))
      }
    );
  }

  updateSaveInMoodleStructure(moodleStructureInd: boolean): void {
    this.userService.updateMoodleStructureInd(moodleStructureInd).subscribe(
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

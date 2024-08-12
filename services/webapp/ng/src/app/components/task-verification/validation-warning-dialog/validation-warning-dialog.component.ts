import { Component, OnInit } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-validation-warning-dialog',
  templateUrl: './validation-warning-dialog.component.html',
  styleUrls: ['./validation-warning-dialog.component.css']
})
export class ValidationWarningDialogComponent implements OnInit {

  constructor(public dialogRef: MatDialogRef<ValidationWarningDialogComponent>) { }

  ngOnInit(): void {
  }


  confirm(): void {
    this.dialogRef.close(true);
  }

  cancel(): void {
    this.dialogRef.close(false);
  }

}

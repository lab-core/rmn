import { Component, OnInit } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';


@Component({
  selector: 'app-delete-template-dialog',
  templateUrl: './delete-template-dialog.component.html',
  styleUrls: ['./delete-template-dialog.component.css']
})
export class DeleteTemplateDialogComponent implements OnInit {

  constructor(public dialogRef: MatDialogRef<DeleteTemplateDialogComponent>) { }

  ngOnInit(): void {
  }

  confirm(): void {
    this.dialogRef.close(true);
  }

  cancel(): void {
    this.dialogRef.close(false);
  }

}

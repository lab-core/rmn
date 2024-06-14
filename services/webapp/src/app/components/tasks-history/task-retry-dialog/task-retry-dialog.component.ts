import { Component, OnInit, Inject } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { SERVER_URL } from 'src/app/utils';

export interface DialogData {
  taskId: string;
  taskName: number;
  taskMessages: string[];
}

@Component({
  selector: 'app-task-retry-dialog',
  templateUrl: './task-retry-dialog.component.html',
  styleUrls: ['./task-retry-dialog.component.css']
})
export class TaskRetryDialogComponent implements OnInit {

  downloading: boolean = false;
  downloadProgress = 0
  errorMessages: string[] = [];
  constructor(
    public dialogRef: MatDialogRef<TaskRetryDialogComponent>,
    private notifyService : NotificationService,
    private userService: UserService,
    private http: HttpClient,
    @Inject(MAT_DIALOG_DATA) public data: DialogData
  ) { 
    this.errorMessages = data.taskMessages;
  }

  ngOnInit(): void {
  }

  cancel(): void {
    this.dialogRef.close('');
  }
}

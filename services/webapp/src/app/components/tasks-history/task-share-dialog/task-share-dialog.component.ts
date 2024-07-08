import { Component, OnInit, Inject } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from "../../../services/notification.service";
import { UserService } from "../../../services/user.service";
import { DocumentsService } from 'src/app/services/documents.service';
import { HttpClient } from '@angular/common/http';
import { Clipboard } from '@angular/cdk/clipboard';
import { SERVER_URL } from 'src/app/utils';

export interface DialogData {
  taskId: string;
  taskName: string;
  questionIndex?: number;
}
@Component({
  selector: 'app-task-share-dialog',
  templateUrl: './task-share-dialog.component.html',
  styleUrls: ['./task-share-dialog.component.css']
})
export class TaskShareDialogComponent implements OnInit {

  url: string;
  shareUrl: string;
  groupsList: Array<string>;
  group: string;
  constructor(
    public dialogRef: MatDialogRef<TaskShareDialogComponent>,
    private notifyService : NotificationService,
    private userService: UserService,
    private docService: DocumentsService,
    private http: HttpClient,
    private clipboard: Clipboard,
    @Inject(MAT_DIALOG_DATA) public data: DialogData) {
    this.groupsList = [""];
    this.group = "";
  }

  ngOnInit(): void {
    const formdata: FormData = new FormData();
    formdata.append('token', this.userService.token);
    formdata.append('job_id', this.data.taskId);
    if (this.data.questionIndex) {
      formdata.append('question_index', this.data.questionIndex.toString());
    }
    this.http.post<any>(`${SERVER_URL}job/share`, formdata).subscribe(
      (data) => {
        let resp = data['response'];
        if (resp.share_url) {
          this.shareUrl = resp.share_url;
          this.docService.getDocuments(this.data.taskId).then(() => {
            this.groupsList = this.docService.groupsList;
            this.group = "";
            this.getUrl();
          });
        } else {
          this.close(false);
        }
      }, (error) => {
        console.error(error);
      });
  }

  getUrl(): void {
    this.url = this.shareUrl;
    if (this.group) this.url += "&group="+encodeURIComponent(this.group);
  }

  unshare(): void {
    const formdata: FormData = new FormData();
    formdata.append('token', this.userService.token);
    formdata.append('job_id', this.data.taskId);
    this.http.post<any>(`${SERVER_URL}job/unshare`, formdata).subscribe(
      (data) => {
        this.close(data['response'] == "OK");
      }, (error) => {
        console.error(error);
      });
  }

  share(): void {
    this.copyUrl();
    this.close(true);
  }

  close(r: any): void {
    this.dialogRef.close(r);
  }

  copyUrl() {
    this.clipboard.copy(this.url);
  }
}

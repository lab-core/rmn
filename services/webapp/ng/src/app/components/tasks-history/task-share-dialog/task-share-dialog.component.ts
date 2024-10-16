import { Component, OnInit, Inject } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from "../../../services/notification.service";
import { UserService } from "../../../services/user.service";
import { TasksService } from 'src/app/services/tasks.service';
import { HttpClient } from '@angular/common/http';
import { Clipboard } from '@angular/cdk/clipboard';
import { SERVER_URL } from 'src/app/utils';
import { first } from 'rxjs/operators';


export interface DialogData {
  taskId: string;
  taskName: string;
  shareType: 'job' | 'matricule';
  questionIndex?: number;
  file?: string;
  zip_index?: number;
  all?: boolean;
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
    private dialogRef: MatDialogRef<TaskShareDialogComponent>,
    private userService: UserService,
    private tasksService: TasksService,
    private http: HttpClient,
    private clipboard: Clipboard,
    @Inject(MAT_DIALOG_DATA) public data: DialogData
  ) {
    this.groupsList = [""];
    this.group = "";
  }

  async ngOnInit(): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.taskId);
    if (this.data.questionIndex !== undefined) {
      formdata.append('question_index', this.data.questionIndex.toString());
    }
    if (this.data.all) {
      formdata.append('all', 'true');
    }
    if (this.data.file !== undefined) {
      formdata.append('file', this.data.file);
    }
    if (this.data.zip_index !== undefined) {
      formdata.append('zip_index', this.data.zip_index.toString());
    }

    await this.http.post<any>(`${SERVER_URL}${this.data.shareType}/share`, formdata)
    .toPromise()
    .then(async (data: any) => {
        let resp = data['response'];
        if (resp.share_url) {
          this.shareUrl = resp.share_url;
          this.group = "";
          if (this.data.shareType === 'matricule') {
            this.tasksService.setvalidatingTaskId(this.data.taskId);
            const task = await this.tasksService.getTask();
            this.groupsList = task['groups'];
            this.groupsList.unshift("");
          }
          this.getUrl();
        } else {
          this.close({success: false, message: "Vous ne pouvez pas partager cette tâche."});
        }
      })
      .catch((error) => {
        console.error(error);
        this.close({success: false, message: "Une erreur est intervenue lors du partage de la tâche !"});
      });
  }

  getUrl(): void {
    this.url = this.shareUrl;
    if (this.group) this.url += "&group=" + encodeURIComponent(this.group);
  }

  unshare(): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.taskId);
    if (this.data.questionIndex) {
      formdata.append('question_index', this.data.questionIndex.toString());
    }
    if (this.data.all) {
      formdata.append('all', 'true');
    }
    this.http.post<any>(`${SERVER_URL}${this.data.shareType}/unshare`, formdata).pipe(first()).subscribe(
      (data) => {
        let resp = {success: data['response'] === "OK"};
        if (resp.success) {
          resp["message"] = "L'accès a été enlevé pour cette tâche.";
        } else {
          resp["message"] = "L'accès n'a pas pu être enlevé pour cette tâche.";
        }

        this.close(resp);
      }, (error) => {
        console.error(error);

        this.close({success: false, message: "Une erreur est intervenue lors du partage de la tâche !"});
      });
  }

  share(): void {
    this.copyUrl();
    this.close({success: true, message: "Le lien a été copié"});
  }

  close(result: any): void {
    this.dialogRef.close(result);
  }

  copyUrl() {
    this.clipboard.copy(this.url);
  }
}

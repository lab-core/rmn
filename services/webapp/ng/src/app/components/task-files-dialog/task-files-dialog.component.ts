import { Component, OnInit, Inject, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { saveAs } from 'file-saver';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { SERVER_URL } from 'src/app/utils';
import { first } from 'rxjs/operators';
import { JobStatus } from '../../generated/rmn-contracts';

export interface DialogData {
  taskId: string;
  nbZipFile: number;
  stats: boolean;
  share?: boolean;
}

@Component({
    selector: 'app-task-files-dialog',
    templateUrl: './task-files-dialog.component.html',
    styleUrls: ['./task-files-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TaskFilesDialogComponent implements OnInit {

  downloading: boolean = false;
  downloadProgress = 0
  constructor(
    public dialogRef: MatDialogRef<TaskFilesDialogComponent>,
    public dialog: MatDialog,
    private notifyService : NotificationService,
    private tasksService: TasksService,
    private userService: UserService,
    private http: HttpClient,
    @Inject(MAT_DIALOG_DATA) public data: DialogData
  ) { }

  ngOnInit(): void {
  }

  showNotificationError(){
    this.notifyService.showError("Assurez-vous de remplir le champ du nom de fichier!", "ERREUR")
  }

  numSequence(n: number): Array<number> {
    return Array(n);
  }

  setZipIds(index : number) : string{
    const value : string = "zip_file-index-" + index.toString();
    return value;
  }

  setDefaultZipValues(index : number) : string{
    let value : string;
    if (index == 0) {
      value = "copies";
    } else {
      value = "moodle";
      if (index > 1) {
        value += `-${index}`;
      }
    }
    return value;
  }

  checkInputBox(inputId : string, share: boolean, index : number = undefined){
    let inputValue : string;

    if(inputId === 'zip_file'){
      inputId = this.setZipIds(index);
      inputValue = (<HTMLInputElement>document.getElementById(inputId)).value;
      inputId = inputId.split('-index-')[0];
    }else{
      inputValue = (<HTMLInputElement>document.getElementById(inputId)).value;
    }

    if(inputValue.trim() === ""){
      this.showNotificationError();
    } else if (share) {
      this.shareTask(inputValue, inputId, index);
    } else {
      // this.downloadFile(inputValue, inputId, index);
      this.openShareURL(inputValue, inputId, index);
    }
  }

  async openShareURL(inputValue, inputId, index=undefined) {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.taskId);
    formdata.append('file', inputId);
    let filename = inputValue;
    if (index !== undefined) {
      formdata.append('zip_index', index.toString());
      filename = this.setDefaultZipValues(index) + '.zip';
    } else if (filename == 'notes') {
      filename = 'notes.csv';
    } else {
      filename += '.pdf';
    }

    await this.http.post<any>(`${SERVER_URL}file/share`, formdata)
    .toPromise()
    .then(async (data: any) => {
      const resp = data['response'];
      if (resp.share_url) {
        const download = document.getElementById('download-file');
        if (!download) {
          console.error('download anchor missing');
          return;
        }
        // the name is a query value: & or # in it used to truncate the URL
        download.setAttribute("href", resp.share_url + "&filename=" + encodeURIComponent(filename));
        download.setAttribute("download", filename);
        download.click();
      }
    })
    .catch((error) => {
      console.error(error);
    });
  }

  shareTask(inputValue, inputId, index=undefined) {
    const data = { taskId: this.data.taskId, taskName: inputValue, file: inputId, shareType: 'file', zip_index: index}
    this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      maxWidth: '400px',
      height: '40%',
      data: data
    }).afterClosed().pipe(first()).subscribe(resp => {
      if (resp !== undefined) {
        if (resp.success) {
          if (resp.message)
            this.notifyService.showSuccess(resp.message, "Succès!");
        } else if (resp.message) {
            this.notifyService.showError(resp.message, "Erreur!");
        }
      }

    }, (error) => {
      console.error(error);

    });
  }

  downloadFile(filename : string, fileType: string, index : number){
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.taskId);
    formdata.append('file', fileType);
    if (index !== undefined) {
      formdata.append('zip_index', index.toString());
    }
    if ( !this.downloading) {
      this.downloading = true;
      this.notifyService.showInfo('Téléchargement...', "")
      const sub = this.http.post(`${SERVER_URL}file/download`, formdata, {responseType: 'blob', reportProgress: true, observe: "events"}).subscribe(
        (data) => {
          if (data.type == HttpEventType.DownloadProgress) {
            this.downloadProgress = data.total ? Math.round(100 * data.loaded / data.total) : 0
          } else if (data.type == HttpEventType.Response) {
            let typeExport = 'text/csv'
            if (fileType == 'zip_file') {
              typeExport = 'application/zip'
            } else if (fileType == 'stats_pdf_file') {
              typeExport = 'application/pdf'
            }
            const file = new Blob([data.body as any], { type: typeExport });
            const downloadURL = window.URL.createObjectURL(file);
            // const download = document.createElement('download-file');
            // download.setAttribute("href", downloadURL);
            // download.setAttribute("download", filename);
            // download.click();
            // download.remove();
            saveAs(downloadURL, filename);
            URL.revokeObjectURL(downloadURL);
            this.downloading = false;
            this.downloadProgress = 0;
            sub.unsubscribe();
          }
        },
        (error) => {
          console.error(error);
          this.downloading = false;
          this.downloadProgress = 0;
          sub.unsubscribe();
        });
    } else {
      this.notifyService.showWarning("Un fichier est en cours de téléchargement!", "Attention" )
    }
  }

  async restore() {
    await this.tasksService.updateTaskStatus(this.data.taskId, JobStatus.VALIDATION);
    this.dialogRef.close(JobStatus.VALIDATION);
  }

  cancel(): void {
    this.dialogRef.close(undefined);
  }
}

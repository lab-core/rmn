import { Component, OnInit, Inject, ElementRef, ViewChild } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { SERVER_URL } from 'src/app/utils';
import { saveAs } from 'file-saver';

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

  @ViewChild('fileUpload', { static: false }) fileUpload: ElementRef;
  downloading: boolean = false;
  downloadProgress = 0;
  errorMessages: string[] = [];
  filenames: string[] = [];
  selectedFiles: File[] = [];
  uploadedFiles: string[] = [];

  constructor(
    public dialogRef: MatDialogRef<TaskRetryDialogComponent>,
    private notifyService: NotificationService,
    private userService: UserService,
    private http: HttpClient,
    @Inject(MAT_DIALOG_DATA) public data: DialogData
  ) { 
    this.errorMessages = data.taskMessages;
    this.extractFilenames();
  }

  ngOnInit(): void {
  }

  cancel(): void {
    this.dialogRef.close('');
  }

  extractFilenames(): void {
    this.filenames = this.errorMessages.map(msg => {
      const match = msg.match(/Erreur : (.+?)\.pdf/);
      return match ? `${match[1]}.pdf` : '';
    });
  }

  onUploadClick(): void {
    const fileUpload = this.fileUpload.nativeElement;
    fileUpload.click();
  }

  onFileSelected(event: any): void {
    if (event.target.files) {
      const files: FileList = event.target.files;
      this.selectedFiles.push(...Array.from(files));
    }
    console.log("onFileSelected", this.selectedFiles)
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer && event.dataTransfer.files) {
      this.selectedFiles.push(...Array.from(event.dataTransfer.files));
    }
    console.log("onDrop", this.selectedFiles)
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  isContinueDisabled(): boolean {
    return this.selectedFiles.length < this.filenames.length;
  }
  

 ignoreAndContinue(): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    formData.append('token', this.userService.token);
    formData.append('job_id', job_id);

    const requestURL = `${SERVER_URL}job/ignore`;
    this.http.post(requestURL, formData).subscribe(
        (data) => {
            this.notifyService.showSuccess('Reprise de la tâche', 'Success');
            this.dialogRef.close('');
        },
        (error) => {
            console.error('Ignore error', error);
            this.notifyService.showError('Erreur dans la reprise de la tâche', 'Error');
        }
    );
  }

  retryJob(): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    formData.append('token', this.userService.token);
    formData.append('job_id', job_id);
    this.selectedFiles.forEach((file, index) => {
      formData.append(`file${index}`, file);  // Use unique keys for each file
      console.log('Appending file:', file.name);  // Print the file name being appended
    });

    this.http.post(`${SERVER_URL}job/continue`, formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe(event => {
      if (event.type === HttpEventType.UploadProgress) {
        this.downloadProgress = Math.round(100 * event.loaded / (event.total ?? 1));
      } else if (event.type === HttpEventType.Response) {
        this.notifyService.showSuccess('Files uploaded successfully', 'Success');
        this.uploadedFiles.push(...this.selectedFiles.map(file => file.name));
        this.selectedFiles = [];
      }
    }, error => {
      this.notifyService.showError('File upload failed', 'Error');
    });
  }

  downloadFile(filename: string): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    formData.append('token', this.userService.token);
    formData.append('job_id', job_id);
    formData.append('file', filename);

    const requestURL = `${SERVER_URL}incorrect/download`;

    this.http.post(requestURL, formData, { responseType: 'blob', reportProgress: true, observe: "events" }).subscribe(
        (data) => {
            if (data.type === HttpEventType.DownloadProgress) {
                this.downloadProgress = data.total ? Math.round(100 * data.loaded / data.total) : 0;
            } else if (data.type === HttpEventType.Response) {
                let typeExport = 'application/pdf'; 
                const file = new Blob([data.body as any], { type: typeExport });
                const downloadURL = window.URL.createObjectURL(file);
                saveAs(downloadURL, filename);

                this.downloading = false;
                this.downloadProgress = 0;
            }
        },
        (error) => {
            console.error('Download error', error);
            this.downloading = false;
            this.downloadProgress = 0;
            this.notifyService.showError('File download failed', 'Error');
        }
    );
  }
}

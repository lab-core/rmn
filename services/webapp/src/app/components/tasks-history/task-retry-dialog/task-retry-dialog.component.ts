import { Component, OnInit, Inject, ElementRef, ViewChild } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { SERVER_URL } from 'src/app/utils';
import { saveAs } from 'file-saver';
import * as JSZip from 'jszip';

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
      this.handleFiles();
    }
    console.log("onFileSelected", this.selectedFiles)
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer && event.dataTransfer.files) {
      this.selectedFiles.push(...Array.from(event.dataTransfer.files));
      this.handleFiles();
    }
    console.log("onDrop", this.selectedFiles)
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  isContinueDisabled(): boolean {
    return this.selectedFiles.length != this.filenames.length;
  }

  async handleFiles(): Promise<void> {
    const nonZipFiles: File[] = [];
    for (const file of this.selectedFiles) {
      if (file.name.endsWith('.zip')) {
        await this.extractZip(file);
      } else {
        nonZipFiles.push(file);
      }
    }
    this.selectedFiles = nonZipFiles;
  }

  async extractZip(file: File): Promise<void> {
    const zip = new JSZip();
    const contents = await zip.loadAsync(file);
    const files = Object.keys(contents.files);

    for (const filename of files) {
      if (!contents.files[filename].dir) {
        const content = await contents.files[filename].async('blob');
        const fileNameOnly = filename.split('/').pop();  // Get the filename without any directory structure
        const newFile = new File([content], fileNameOnly, { type: content.type });
        this.selectedFiles.push(newFile);
      }
    }

    console.log('Files after ZIP extraction:', this.selectedFiles);
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
      formData.append(`file${index}`, file); 
    });

    this.http.post(`${SERVER_URL}job/continue`, formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe(event => {
      if (event.type === HttpEventType.UploadProgress) {
        this.downloadProgress = Math.round(100 * event.loaded / (event.total ?? 1));
      } else if (event.type === HttpEventType.Response) {
        this.notifyService.showSuccess('Files uploaded successfully', 'Success');
        this.dialogRef.close('');
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

  downloadAllAsZip(): void {
    const job_id = this.data.taskId;
    const zip = new JSZip();
    let count = 0;
    const filenames = this.filenames;

    filenames.forEach((filename) => {
      const formData = new FormData();
      formData.append('token', this.userService.token);
      formData.append('job_id', job_id);
      formData.append('file', filename);

      const requestURL = `${SERVER_URL}incorrect/download`;

      this.http.post(requestURL, formData, { responseType: 'blob' }).subscribe(
        (data: Blob) => {
          zip.file(filename, data);
          count++;
          if (count === filenames.length) {
            zip.generateAsync({ type: 'blob' }).then((content) => {
              saveAs(content, 'all_pdfs.zip');
            });
          }
        },
        (error) => {
          console.error('Download error', error);
          this.notifyService.showError('Some files could not be downloaded', 'Error');
        }
      );
    });
  }

  deleteFile(index: number): void {
    this.selectedFiles.splice(index, 1);
  }
}

import { Component, OnInit, Inject, ElementRef, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { SERVER_URL } from 'src/app/utils';
import { saveAs } from 'file-saver';
import JSZip from 'jszip';
import { forkJoin, of } from 'rxjs';
import { catchError, first, map } from 'rxjs/operators';
import { JobStatus } from '../../generated/rmn-contracts';
import { TaskSettingsDialogComponent } from '../task-settings/task-settings-dialog.component';


export interface DialogData {
  taskId: string;
  taskName: number;
  taskMessages: string[];
}

@Component({
    selector: 'app-task-retry-dialog',
    templateUrl: './task-retry-dialog.component.html',
    styleUrls: ['./task-retry-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TaskRetryDialogComponent implements OnInit {

  @ViewChild('fileUpload', { static: false }) fileUpload: ElementRef;
  downloading: boolean = false;
  uploading: boolean = false;
  disabled: boolean = true;
  downloadProgress = 0;
  uploadProgress = 0;
  errorMessages: string[] = [];
  filenames: string[] = [];
  selectedFiles: File[] = [];
  uploadedFiles: string[] = [];

  constructor(
    public dialogRef: MatDialogRef<TaskRetryDialogComponent>,
    private notifyService: NotificationService,
    private userService: UserService,
    private http: HttpClient,
    private dialog: MatDialog,
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

  /**
   * The copies were refused for their page count: the pages per question may
   * be what is wrong. Fixed in the settings, the refused copies are split
   * again and this dialog has nothing left to do.
   */
  editSettings(): void {
    const settings = this.dialog.open(TaskSettingsDialogComponent, {
      width: '80%',
      maxWidth: '500px',
      data: { taskId: this.data.taskId, taskName: String(this.data.taskName), status: JobStatus.RETRY },
    });
    settings.afterClosed().pipe(first()).subscribe((result) => {
      if (result && result.nPagesPerQuestion) {
        this.dialogRef.close(JobStatus.CORRECTED);
      }
    });
  }

  extractFilenames(): void {
    if (Array.isArray(this.errorMessages)) {
      this.filenames = this.errorMessages.map(msg => {
        // const match = msg.match(/Erreur: (.+?)\.pdf/);
        // return match ? `${match[1]}.pdf` : '';
        const parts = msg.split('Erreur:');
        return parts.length > 1 ? parts[1].trim() : '';
      });
    }
  }

  onUploadClick(): void {
    const fileUpload = this.fileUpload.nativeElement;
    fileUpload.click();
  }

  /** Returns once every selected zip has been unpacked, so callers can await it. */
  onFileSelected(event: any): Promise<void> {
    if (event.target.files) {
      const files: FileList = event.target.files;
      this.selectedFiles.push(...Array.from(files));
      return this.handleFiles();
    }
    return Promise.resolve();
  }

  onDrop(event: DragEvent): Promise<void> {
    event.preventDefault();
    if (event.dataTransfer && event.dataTransfer.files) {
      this.selectedFiles.push(...Array.from(event.dataTransfer.files));
      return this.handleFiles();
    }
    return Promise.resolve();
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  isContinueDisabled(): boolean {
    return this.selectedFiles.length !== this.filenames.length;
  }

  isFileNamesEmpty(): boolean {
    return this.filenames.length === 0;
  }

  async handleFiles(): Promise<void> {
    const pdfFiles: File[] = [];
    const zipFiles: File[] = [];

    for (const file of this.selectedFiles) {
        if (file.name.endsWith('.zip')) {
            zipFiles.push(file);
        } else if (this.isPDF(file)) {
            pdfFiles.push(file);
        }
    }

    this.selectedFiles = pdfFiles;

    for (const zipFile of zipFiles) {
        await this.extractZip(zipFile);
    }

    this.disabled = false;
  }

  isPDF(file: File): boolean {
      return file.type === 'application/pdf' && !file.name.startsWith('.');
  }

  async extractZip(file: File): Promise<void> {
      const zip = new JSZip();
      const contents = await zip.loadAsync(file);
      const files = Object.keys(contents.files);

      for (const filename of files) {
          if (!contents.files[filename].dir) {
              const content = await contents.files[filename].async('blob');
              const fileNameOnly = filename.split('/').pop();
              const newFile = new File(
                  [content],
                  fileNameOnly,
                  { type: fileNameOnly.endsWith('.pdf') ? 'application/pdf' : content.type }
              );
              if (this.isPDF(newFile)) {
                  this.selectedFiles.push(newFile);
              }
          }
      }
  }

  ignoreAndContinue(): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', job_id);

    const requestURL = `${SERVER_URL}job/ignore`;
    this.http.post(requestURL, formData).pipe(first()).subscribe(
        (data) => {
            this.notifyService.showSuccess('Reprise de la tâche', 'SUCCÈS');
            this.dialogRef.close(JobStatus.IGNORED);

        },
        (error) => {
            console.error('Ignore error', error);
            this.notifyService.showError('Erreur dans la reprise de la tâche', 'ERREUR');

        }
    );
  }

  retryJob(): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', job_id);
    this.selectedFiles.forEach((file, index) => {
      formData.append(`file${index}`, file);
    });

    // show the spinner while the copies upload, and disable the buttons
    this.uploading = true;
    this.uploadProgress = 0;

    const sub = this.http.post(`${SERVER_URL}job/continue`, formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe(event => {
      if (event.type === HttpEventType.UploadProgress) {
        this.uploadProgress = Math.round(100 * event.loaded / (event.total ?? 1));
      } else if (event.type === HttpEventType.Response) {
        this.uploading = false;
        this.notifyService.showSuccess('Fichier(s) téléversé(s) avec succès', 'SUCCÈS');
        this.dialogRef.close(JobStatus.CORRECTED);
        this.uploadedFiles.push(...this.selectedFiles.map(file => file.name));
        this.selectedFiles = [];
        sub.unsubscribe();
      }
    }, error => {
      // always clear the spinner so the dialog is never left stuck
      this.uploading = false;
      this.notifyService.showError('Échec du téléversement du/des fichier(s)', 'ERREUR');
      sub.unsubscribe();
    });
  }

  downloadFile(filename: string): void {
    const job_id = this.data.taskId;
    const formData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', job_id);
    formData.append('file', filename);

    const requestURL = `${SERVER_URL}incorrect/download`;

    const sub = this.http.post(requestURL, formData, { responseType: 'blob', reportProgress: true, observe: "events" }).subscribe(
        (data) => {
            if (data.type === HttpEventType.DownloadProgress) {
                this.downloadProgress = data.total ? Math.round(100 * data.loaded / data.total) : 0;
            } else if (data.type === HttpEventType.Response) {
                const typeExport = 'application/pdf';
                const file = new Blob([data.body as any], { type: typeExport });
                saveAs(file, filename);
                this.downloading = false;
                this.downloadProgress = 0;
                sub.unsubscribe();
            }
        },
        (error) => {
            console.error('Download error', error);
            this.downloading = false;
            this.downloadProgress = 0;
            this.notifyService.showError('Échec du téléchargement du fichier', 'ERREUR');
            sub.unsubscribe();
        }
    );
  }

  downloadAllAsZip(): void {
    const job_id = this.data.taskId;
    const filenames = this.filenames;
    if (filenames.length === 0) {
      return;
    }
    const downloads = filenames.map((filename) => {
      const formData = new FormData();
      this.userService.addTokens(formData);
      formData.append('job_id', job_id);
      formData.append('file', filename);
      return this.http.post(`${SERVER_URL}incorrect/download`, formData, { responseType: 'blob' }).pipe(
        first(),
        map((data: Blob) => ({ filename, data })),
        catchError(() => of({ filename, data: undefined as Blob | undefined })),
      );
    });
    // every download is awaited, failed or not: a counter of successes used
    // to leave the zip unbuilt forever when one file failed
    forkJoin(downloads).pipe(first()).subscribe(async (results) => {
      const zip = new JSZip();
      const failed = results.filter((r) => !r.data).map((r) => r.filename);
      results.filter((r) => r.data).forEach((r) => zip.file(r.filename, r.data));
      if (failed.length > 0) {
        this.notifyService.showError(`Fichier(s) non téléchargé(s): ${failed.join(', ')}`, 'ERREUR');
      }
      if (failed.length < results.length) {
        saveAs(await zip.generateAsync({ type: 'blob' }), 'all_pdfs.zip');
      }
    });
  }

  deleteFile(index: number): void {
    this.selectedFiles.splice(index, 1);
  }
}

import { Component, OnInit, Inject } from '@angular/core';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';


export interface DialogData {
  jobId: string;
}

@Component({
  selector: 'csv-update-dialog',
  templateUrl: './csv-update-dialog.component.html',
  styleUrls: ['./csv-update-dialog.component.css']
})
export class CsvUpdateDialogComponent implements OnInit {

  constructor(public dialogRef: MatDialogRef<CsvUpdateDialogComponent>,
    private http: HttpClient,
    private userService: UserService,
    private notificationService: NotificationService,
    @Inject(MAT_DIALOG_DATA) public data: DialogData) { }

  async ngOnInit() {}

  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.uploadCsvFile(file);
    }
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    const file = event.dataTransfer?.files[0];
    if (file) {
      this.uploadCsvFile(file);
    }
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
  }

  async readFileSync(file: File | Blob, text = false): Promise<string | ArrayBuffer> {
     return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      text ? reader.readAsText(file) : reader.readAsArrayBuffer(file);
    });
  }

  async uploadCsvFile(file: File) {
    const formdata = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.jobId);
    formdata.append('csv', file);

    try {
      const promise = await this.http.post(`${SERVER_URL}job/update/csv`, formdata).toPromise();
      if (promise['response'] === 'OK') {
        this.notificationService.showSuccess('Fichier csv remplacé avec succès!', 'Succès');
        this.dialogRef.close();
      } else {
        console.error(promise['response']);
        this.notificationService.showError('Erreur lors du remplacement du fichier csv', 'Erreur');
      }
    } catch (error) {
      console.error(error);
      this.notificationService.showError('Erreur lors du remplacement du fichier csv', 'Erreur');
    }
  }
}

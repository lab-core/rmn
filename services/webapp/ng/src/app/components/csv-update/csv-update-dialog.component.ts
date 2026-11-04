import { Component, OnInit, Inject, ChangeDetectionStrategy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { ClassListAssignments, askClassListAssignments } from '../class-list-duplicates/class-list-duplicates-dialog.component';


export interface DialogData {
  jobId: string;
  // the task's class lists by name; a task given a single one calls it "notes"
  lists?: string[];
}

/** The class lists of a task: one Moodle export per assignment.
 *
 *  A list can be removed and files added, each a list of its own, then
 *  everything is saved at once (``jobs/update/csv`` with ``keep``). A student
 *  then found in several lists is asked about, as when the task is created.
 *  Closes with true once saved. */
@Component({
    selector: 'csv-update-dialog',
    templateUrl: './csv-update-dialog.component.html',
    styleUrls: ['./csv-update-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class CsvUpdateDialogComponent implements OnInit {

  // the task's lists, false once the user removed it
  kept: { name: string; keep: boolean }[] = [];
  added: File[] = [];
  saving = false;

  constructor(public dialogRef: MatDialogRef<CsvUpdateDialogComponent>,
    private http: HttpClient,
    private dialog: MatDialog,
    private userService: UserService,
    private notificationService: NotificationService,
    @Inject(MAT_DIALOG_DATA) public data: DialogData) { }

  ngOnInit() {
    this.kept = (this.data.lists?.length ? this.data.lists : ['notes']).map((name) => ({ name, keep: true }));
  }

  onFileSelected(event: any) {
    this.addFiles(event.target.files);
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    this.addFiles(event.dataTransfer?.files);
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
  }

  /** Add files to the lists to save; a file of the same name is replaced. */
  addFiles(files: FileList | File[] | undefined) {
    for (const file of Array.from(files ?? [])) {
      this.added = [...this.added.filter((f) => f.name !== file.name), file];
    }
  }

  removeAdded(index: number) {
    this.added = this.added.filter((_, i) => i !== index);
  }

  /** How many lists the task would have once saved. */
  remaining(): number {
    return this.kept.filter((l) => l.keep).length + this.added.length;
  }

  changed(): boolean {
    return this.added.length > 0 || this.kept.some((l) => !l.keep);
  }

  async save(assignments: ClassListAssignments = null) {
    if (!this.changed() || this.remaining() === 0 || this.saving) {
      return;
    }
    const formdata = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.data.jobId);
    formdata.append('keep', JSON.stringify(this.kept.filter((l) => l.keep).map((l) => l.name)));
    for (const file of this.added) {
      formdata.append('csv', file);
    }
    if (assignments) {
      formdata.append('assignments', JSON.stringify(assignments));
    }

    this.saving = true;
    try {
      const answer = await firstValueFrom(this.http.post(`${SERVER_URL}jobs/update/csv`, formdata));
      if (answer['response'] === 'OK') {
        this.notificationService.showSuccess('Listes de classe enregistrées!', 'Succès');
        this.dialogRef.close(true);
      } else {
        console.error(answer['response']);
        this.notificationService.showError('Erreur lors du remplacement du fichier csv', 'Erreur');
      }
    } catch (error) {
      // a student in several lists: ask which one, and save again
      const chosen = await askClassListAssignments(this.dialog, error);
      if (chosen) {
        this.saving = false;
        return this.save(chosen);
      }
      if (chosen === null) {
        console.error(error);
        const message = (error as { error?: { response?: string } })?.error?.response;
        this.notificationService.showError(
          message?.replace(/^Error: /, '') || 'Erreur lors du remplacement du fichier csv', 'Erreur');
      }
    } finally {
      this.saving = false;
    }
  }
}

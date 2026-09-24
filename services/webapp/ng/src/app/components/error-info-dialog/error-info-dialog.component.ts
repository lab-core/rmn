import { Component, Inject, ChangeDetectionStrategy } from '@angular/core';
import { MAT_DIALOG_DATA } from '@angular/material/dialog';


/** Shows the message the executor stored in job_infos when a task failed. */
@Component({
    selector: 'app-error-info-dialog',
    templateUrl: './error-info-dialog.component.html',
    styleUrls: ['./error-info-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ErrorInfoDialogComponent {
  messages: string[];

  // job_infos is a string, or the list of per-copy errors of an import
  constructor(@Inject(MAT_DIALOG_DATA) public data: {taskName: string, infos: string | string[]}) {
    this.messages = Array.isArray(data.infos) ? data.infos : [data.infos];
  }
}

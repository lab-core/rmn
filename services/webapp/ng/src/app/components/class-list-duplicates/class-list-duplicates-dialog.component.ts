import { Component, ChangeDetectionStrategy, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';

/** A student found in several class lists, as the server answers it (409). */
export interface ClassListDuplicate {
  matricule: string;
  name: string;
  lists: string[];
}

export interface ClassListDuplicatesData {
  duplicates: ClassListDuplicate[];
}

/** The list each student found in several belongs to, by matricule. */
export type ClassListAssignments = Record<string, string>;

/** Asks which class list each student found in several of them belongs to.
 *
 *  A student in two Moodle exports is usually a mistake in one of them, so
 *  the dialog says to fix it there; meanwhile the task needs one list per
 *  student, or their copy would be graded in both assignments. Closes with
 *  the choices (ClassListAssignments), or undefined when cancelled. */
@Component({
    selector: 'app-class-list-duplicates-dialog',
    templateUrl: './class-list-duplicates-dialog.component.html',
    styleUrls: ['./class-list-duplicates-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ClassListDuplicatesDialogComponent {

  assignments: ClassListAssignments = {};

  constructor(public dialogRef: MatDialogRef<ClassListDuplicatesDialogComponent>,
              @Inject(MAT_DIALOG_DATA) public data: ClassListDuplicatesData) { }

  complete(): boolean {
    return this.data.duplicates.every((d) => d.lists.includes(this.assignments[d.matricule]));
  }

  confirm(): void {
    if (this.complete()) {
      this.dialogRef.close({ ...this.assignments });
    }
  }
}

/** When the server refused the class lists because of students found in
 *  several (a 409 with ``duplicates``), ask which list each belongs to.
 *
 *  @returns The choices to send again; undefined when the user cancelled;
 *      null when the error is about something else. */
export async function askClassListAssignments(
    dialog: MatDialog, error: unknown): Promise<ClassListAssignments | undefined | null> {
  const body = (error as { status?: number; error?: { duplicates?: ClassListDuplicate[] } });
  if (body?.status !== 409 || !body.error?.duplicates?.length) {
    return null;
  }
  const ref = dialog.open(ClassListDuplicatesDialogComponent, {
    width: '90%',
    maxWidth: '640px',
    data: { duplicates: body.error.duplicates },
  });
  return firstValueFrom(ref.afterClosed());
}

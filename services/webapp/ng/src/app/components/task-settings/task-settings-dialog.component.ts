import { Component, Inject, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { NotificationService } from 'src/app/services/notification.service';
import { JobStatus } from '../../generated/rmn-contracts';

export interface TaskSettingsData {
  taskId: string;
  taskName: string;
  status: string;
  // loaded from /job when not given (the retry dialog only knows the name)
  nPagesPerQuestion?: Array<[string, number]>;
  nMaxPointsPerQuestion?: Array<[string, number]>;
}

interface QuestionRow {
  key: string;
  pages: number;
  points: number;
}

// once validated, the points are in the output (csv, stats pages)
const POINTS_LOCKED = [JobStatus.VALIDATED, JobStatus.FINALIZING, JobStatus.ARCHIVED] as string[];

/**
 * Edit a task after creation: its name at any time, its points per question
 * until it is validated, its pages per question while its copies wait in RETRY
 * (they are then split again). The server enforces the same rules.
 */
@Component({
    selector: 'task-settings-dialog',
    templateUrl: './task-settings-dialog.component.html',
    styleUrls: ['./task-settings-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TaskSettingsDialogComponent implements OnInit {
  name: string;
  rows: QuestionRow[] = [];
  loading = false;
  saving = false;
  error = '';

  constructor(public dialogRef: MatDialogRef<TaskSettingsDialogComponent>,
    private tasksService: TasksService,
    private notificationService: NotificationService,
    @Inject(MAT_DIALOG_DATA) public data: TaskSettingsData) {
    this.name = data.taskName;
  }

  async ngOnInit(): Promise<void> {
    if (!this.data.nPagesPerQuestion || !this.data.nMaxPointsPerQuestion) {
      this.loading = true;
      try {
        const job = await this.tasksService.getTaskById(this.data.taskId);
        this.data.nPagesPerQuestion = job.n_pages_per_question;
        this.data.nMaxPointsPerQuestion = job.n_max_points_per_question;
        this.data.status = job.job_status;
      } catch (e) {
        this.error = 'impossible de charger la tâche.';
      } finally {
        this.loading = false;
      }
    }
    const points = new Map(this.data.nMaxPointsPerQuestion || []);
    this.rows = (this.data.nPagesPerQuestion || []).map(([key, pages]) => ({ key, pages, points: points.get(key) ?? 0 }));
  }

  get pointsEditable(): boolean {
    return !POINTS_LOCKED.includes(this.data.status);
  }

  get pagesEditable(): boolean {
    return this.data.status === JobStatus.RETRY;
  }

  /** Questions corrected (0 page means ignored: no points either). */
  correctedRows(): QuestionRow[] {
    return this.pagesEditable ? this.rows : this.rows.filter((row) => row.pages > 0);
  }

  async save(): Promise<void> {
    const changes: any = {};
    const name = (this.name || '').trim();
    if (name !== this.data.taskName) {
      changes.jobName = name;
    }
    const points = this.rows.map((row) => [row.key, Number(row.points)] as [string, number]);
    if (this.pointsEditable && JSON.stringify(points) !== JSON.stringify(this.data.nMaxPointsPerQuestion)) {
      changes.nMaxPointsPerQuestion = points;
    }
    const pages = this.rows.map((row) => [row.key, Number(row.pages)] as [string, number]);
    if (this.pagesEditable && JSON.stringify(pages) !== JSON.stringify(this.data.nPagesPerQuestion)) {
      changes.nPagesPerQuestion = pages;
    }
    if (Object.keys(changes).length === 0) {
      this.dialogRef.close();
      return;
    }

    this.saving = true;
    this.error = '';
    try {
      const result = await this.tasksService.updateTaskSettings(this.data.taskId, changes);
      let message = 'Tâche modifiée.';
      if (result.flagged) {
        message += ` ${result.flagged} note(s) au-dessus du nouveau maximum repassent à valider.`;
      }
      if (result.resplit) {
        message += ` ${result.resplit} copie(s) vont être redécoupées.`;
      }
      this.notificationService.showSuccess(message, 'Succès');
      this.dialogRef.close({ ...changes, ...result });
    } catch (e) {
      this.error = e?.message || 'la modification a échoué.';
    } finally {
      this.saving = false;
    }
  }

  cancel(): void {
    this.dialogRef.close();
  }
}

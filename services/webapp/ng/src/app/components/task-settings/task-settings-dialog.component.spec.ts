import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { TaskSettingsDialogComponent } from './task-settings-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { TasksService } from 'src/app/services/tasks.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy, settle } from '../../testing/helpers';

const PAGES: Array<[string, number]> = [['Q1', 1], ['Q2', 2], ['Q3', 0]];
const POINTS: Array<[string, number]> = [['Q1', 10], ['Q2', 5], ['Q3', 0]];

describe('TaskSettingsDialogComponent', () => {
  let fixture: ComponentFixture<TaskSettingsDialogComponent>;
  let component: TaskSettingsDialogComponent;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;
  let tasks: any;

  const create = async (data: any) => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    tasks = {
      updateTaskSettings: jasmine.createSpy('updateTaskSettings').and.resolveTo({ flagged: 0, resplit: 0 }),
      getTaskById: jasmine.createSpy('getTaskById').and.resolveTo({
        job_status: 'RETRY', n_pages_per_question: PAGES, n_max_points_per_question: POINTS,
      }),
    };
    TestBed.configureTestingModule({
      declarations: [TaskSettingsDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: TasksService, useValue: tasks },
        { provide: MAT_DIALOG_DATA, useValue: JSON.parse(JSON.stringify(data)) },
      ],
    });
    fixture = TestBed.createComponent(TaskSettingsDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await settle();
    fixture.detectChanges();
  };

  const task = (status: string) => ({
    taskId: 'job', taskName: 'Intra', status, nPagesPerQuestion: PAGES, nMaxPointsPerQuestion: POINTS,
  });

  it('while correcting, the name and the points of the corrected questions can change', async () => {
    await create(task('VALIDATION'));
    const html: HTMLElement = fixture.nativeElement;
    expect(html.querySelector('#points-Q1')).not.toBeNull();
    expect(html.querySelector('#points-Q3')).toBeNull();  // ignored question
    expect(html.querySelector('#pages-Q1')).toBeNull();  // the copies are already split

    component.name = ' Intra A26 ';
    component.rows[0].points = 12;
    await component.save();

    expect(tasks.updateTaskSettings).toHaveBeenCalledWith('job', {
      jobName: 'Intra A26',
      nMaxPointsPerQuestion: [['Q1', 12], ['Q2', 5], ['Q3', 0]],
    });
    expect(dialogRef.close).toHaveBeenCalledWith(jasmine.objectContaining({ jobName: 'Intra A26' }));
  });

  it('only what changed is sent, and nothing at all closes without a request', async () => {
    await create(task('VALIDATION'));
    component.name = 'Renamed';
    await component.save();
    expect(tasks.updateTaskSettings).toHaveBeenCalledWith('job', { jobName: 'Renamed' });

    tasks.updateTaskSettings.calls.reset();
    component.name = 'Intra';
    await component.save();
    expect(tasks.updateTaskSettings).not.toHaveBeenCalled();
    expect(dialogRef.close).toHaveBeenCalled();
  });

  it('a validated task keeps its points: only the name can change', async () => {
    await create(task('ARCHIVED'));
    expect(component.pointsEditable).toBeFalse();
    expect(fixture.nativeElement.querySelector('#points-Q1')).toBeNull();
    component.rows[0].points = 99;  // not reachable from the page, not sent either
    component.name = 'Archived intra';
    await component.save();
    expect(tasks.updateTaskSettings).toHaveBeenCalledWith('job', { jobName: 'Archived intra' });
  });

  it('from the retry dialog, loads the task and lets the pages change', async () => {
    await create({ taskId: 'job', taskName: 'Intra', status: 'RETRY' });
    expect(tasks.getTaskById).toHaveBeenCalledWith('job');
    expect(component.pagesEditable).toBeTrue();
    // every question, ignored ones too: one may have been ignored by mistake
    expect(fixture.nativeElement.querySelector('#pages-Q3')).not.toBeNull();

    component.rows[0].pages = 2;
    await component.save();
    expect(tasks.updateTaskSettings).toHaveBeenCalledWith('job', { nPagesPerQuestion: [['Q1', 2], ['Q2', 2], ['Q3', 0]] });
  });

  it('says what the change did', async () => {
    await create(task('VALIDATION'));
    tasks.updateTaskSettings.and.resolveTo({ flagged: 3, resplit: 0 });
    component.rows[1].points = 2;
    await component.save();
    expect(notification.showSuccess).toHaveBeenCalledWith(jasmine.stringContaining('3 note(s)'), 'Succès');
  });

  it('a refusal is shown and the dialog stays open', async () => {
    await create(task('VALIDATION'));
    tasks.updateTaskSettings.and.rejectWith(new Error('la tâche a changé d\'état entre-temps, réessayez.'));
    component.name = 'Other';
    await component.save();
    fixture.detectChanges();
    expect(dialogRef.close).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('#settings-error').textContent).toContain('réessayez');
    expect(component.saving).toBeFalse();
  });
});

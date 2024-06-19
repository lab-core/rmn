import { HttpClient } from '@angular/common/http';
import { Component, Input } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { TaskFilesDialogComponent } from '../tasks-history/task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from '../tasks-history/task-share-dialog/task-share-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css']
})
export class DashboardPageComponent {
  taskName: string = 'Tâche';
  questions: { corrected: number, total: number }[] = [
    { corrected: 0, total: 150 },
    { corrected: 10, total: 150 },
    { corrected: 75, total: 150 }
  ];
  averages: string[] = [
    '0/5',
    '2.18/3',
    '3.47/5'
  ];
  constructor(
    private router: Router, 
    private tasksService: TasksService, 
    private userService: UserService, 
    private http: HttpClient, 
    public dialog: MatDialog, 
    private notificationService: NotificationService
  ) { }

  getTaskInfo(task: any) {
    if (task.job_status === 'ARCHIVED') {
      this.openTaskFilesDialog(task.job_id);
    }
    else if (task.job_status === 'VALIDATION' || task.job_status === 'RUN') {
      this.tasksService.setvalidatingTaskId(task.job_id);
      this.router.navigate(['/task-validation']);
    }
  }

  openTaskFilesDialog(jobId: string): void {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).subscribe(
      (data) => {
        let nbZipFile = data['response']
        let dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '30%',
          height: '60%',
          data: { taskId: jobId, nbZipFile: nbZipFile }
        })
      }, (error) => {
        console.error(error);
      });
  }

  shareJob(jobId: string, jobName: string): void {
    let dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: {taskId: jobId, taskName: jobName}
    });
    dialogRef.afterClosed().subscribe(async result => {
        if (result === false) {
          const message = "Une erreur est intervenue lors du partage de la tâche !";
          this.notificationService.showError(message, "Erreur!");
        }
      }, (error) => {
        console.error(error);
      });
  }

  correctQuestion() {
    console.log('Correction button clicked');
  }

  shareQuestion(index: number) {
    console.log(`Share question ${index + 1}`);
  }

  reroute() {
    this.router.navigate(['/tasks-history']);
  }
}

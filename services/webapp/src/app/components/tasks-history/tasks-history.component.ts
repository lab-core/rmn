import { HttpClient } from '@angular/common/http';
import { Location } from '@angular/common';
import { Component, OnInit, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { TaskFilesDialogComponent } from './task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from "./task-share-dialog/task-share-dialog.component";
import { NavigationStart, Router } from '@angular/router';
import { MatTableDataSource } from '@angular/material/table'
import { MatPaginator } from '@angular/material/paginator';
import { MatSort } from '@angular/material/sort';
import { SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { ThemePalette } from '@angular/material/core';
import { ProgressSpinnerMode } from '@angular/material/progress-spinner';
import { SERVER_URL } from 'src/app/utils';
import { filter } from 'rxjs/operators';
import { TaskRetryDialogComponent } from './task-retry-dialog/task-retry-dialog.component';

@Component({
  selector: 'app-tasks-history',
  templateUrl: './tasks-history.component.html',
  styleUrls: ['./tasks-history.component.css']
})
export class TasksHistoryComponent implements OnInit {

  tasksList: Array<any> = [];
  remainingTime: Number;
  color: ThemePalette = 'primary';
  mode: ProgressSpinnerMode = 'determinate';
  diameter = 60;
  displayedColumns: string[] = ['job_name', 'template_name', 'queued_time', 'job_status', 'job_infos', 'job_estimation', 'job_deletion', 'job_retry'];
  dataSource: MatTableDataSource<any> = new MatTableDataSource<any>();

  @ViewChild(MatPaginator) paginator: MatPaginator;
  @ViewChild(MatSort) sort: MatSort;

  indicator_socket: Boolean = false;

  constructor(
    private location: Location,
    private tasksService: TasksService,
    private http: HttpClient,
    public dialog: MatDialog,
    private router: Router,
    private socketService: SocketService,
    private notificationService: NotificationService,
    private userService: UserService
  ) {
    this.router.events
      .pipe(filter((event: NavigationStart) => event.navigationTrigger === 'popstate'))
      .subscribe(() => {
          if (this.router.url === '/tasks-history') {
            this.reroute();
          }
        }, (error) => {
          console.error(error);
        });
  }

  async ngOnInit(): Promise<void> {
    // Assign the data to the data source for the table to render
    this.getTasks();
    this.socketService.join(this.userService.currentUsername)
    this.socketService.getSocket().on('jobs_status', async (params: any) => {
      let resp = JSON.parse(params)
      let job_id = resp.job_id;
      let job_status = resp.status;

      this.tasksList.forEach(x => {
        if (x.job_id === job_id) {
          x.job_status = job_status;
          let status = '';
          switch (job_status) {
            case 'QUEUED':
              status = 'En attente';
              break;
            case 'RUN':
              status = 'En traîtement';
              break;
            case 'VALIDATION':
              status = 'Prêt à la vérification';
              break;
            case 'FINALIZING':
              status = 'Finalisation en cours';
              break;
            case 'ARCHIVED':
              status = 'Archivée';
              break;
            case 'ERROR':
              status = 'Erreur';
              let cleanedInfos = resp.job_infos.slice(1, -1).replace(/['",]/g, '');
              x.job_infos = cleanedInfos.split(/(?<=[.?!])\s+/).map(info => info.trim());
              this.saveJobInfos(job_id, x.job_infos);
              break;
          }
          const message = "Le status de la tâche " + String(job_id) + " a changé à [" + String(status) + "] !";
          this.notificationService.showInfo(message, "Alerte!")
        }
      });
    });

    // subscribe to all running jobs
    this.tasksList.forEach(x => {
      if (x.job_status == 'QUEUED' || x.job_status == 'RUN') {
        this.socketService.join(x.job_id);
      }
    });

    this.socketService.getSocket().on('document_ready', async (params: any) => {
      let resp = JSON.parse(params)
      let job_id = resp.job_id;
      let lastN = resp.document_index;
      let lastExecTime = resp.execution_time;
      let n_total_doc = resp.n_total_doc;
      this.tasksList.forEach(x => {
        if (x.job_id === job_id) {
          x.job_estimation = Math.round((n_total_doc - lastN) * lastExecTime);
          // x.job_completion = Math.round((lastN / n_total_doc) * 100);
        }
      });
      this.dataSource.data = this.tasksList;
    });

    setInterval(this.decrementTime.bind(this), 1000);
  }

  ngOnDestroy(): void {
    this.socketService.getSocket().off('document_ready');
    this.socketService.getSocket().off('jobs_status');
    this.socketService.disconnectSocket();
  }

  applyFilter(event: Event) {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();

    if (this.dataSource.paginator) {
      this.dataSource.paginator.firstPage();
    }
  }

  getTasks() {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    this.http.post<any>(`${SERVER_URL}jobs`, formdata).subscribe(
      (data) => {
        let amountTask = 0;
        this.tasksList = data['response'];

        this.tasksList.forEach(x => {
          x.queued_time = new Date(x.queued_time + 'Z')
        })

        this.tasksList.forEach((task: any) => {
          if (task.job_status === 'VALIDATION') {
            amountTask += 1;
          }
        });
        this.tasksService.setamountTasks(amountTask);
        this.tasksList.forEach(x => {
          const formdata: FormData = new FormData();
          formdata.append('token', this.userService.token);
          formdata.append('job_id', x.job_id);
          this.http.post<any>(`${SERVER_URL}documents`, formdata).subscribe(
            (data) => {
              let lastN = 0;
              let lastExecTime = 0;
              let lastStatus = "NOT_READY";

              let mapStatus = new Map<string, number>();
              mapStatus.set("NOT_READY", 0);
              mapStatus.set("VALIDATED", 1);
              mapStatus.set("TO VALIDATE", 1);
              mapStatus.set("HIGH ACCURACY", 1);
              mapStatus.set("READY", 2);

              let response = data["response"];
              response.forEach(y => {
                if ((x.job_status === "RUN" && mapStatus.get(y.status) === 1) || (x.job_status === "FINALIZING" && mapStatus.get(y.status) === 2)) {
                  lastN = y.document_index;
                  lastExecTime = y.exec_time;
                  lastStatus = y.status;
                }
              });

              if (x.job_status === "RUN" || x.job_status === "FINALIZING") {
                x.job_estimation = Math.round((response[0].n_total_doc - lastN) * lastExecTime);
              }
              if (x.job_status === "QUEUED") {
                // x.job_completion = 0;
              } else if (x.job_status === "ERROR") {
                // x.job_completion = 0;
              } else if (x.job_status === "ARCHIVED") {
                // x.job_completion = 100;
              } else {
                // x.job_completion = Math.round((lastN / response[0].n_total_doc) * 100);
              }
            }, (error) => {
              console.error(error);
            });
        });
        this.dataSource.data = this.tasksList;
        this.dataSource.paginator = this.paginator;
        this.dataSource.sort = this.sort;
      }, (error) => {
        console.error(error);
      });
  }

  deleteJob(jobId: string): void {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/delete`, formdata).subscribe(
      (data) => {
        if (data['response'] === 'OK') {
          this.getTasks();
        }
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

  retryJob(jobId: string, jobName: string): void {
    let errorMessages = this.getSavedJobInfos(jobId);
    let dialogRef = this.dialog.open(TaskRetryDialogComponent, {
      width: '50%',
      height: '50%',
      data: {taskId: jobId, taskName: jobName, taskMessages: errorMessages }
    });
    dialogRef.afterClosed().subscribe(async result => {
        if (result === false) {
          const message = "Une erreur est intervenue lors de la correction de la tâche !";
          this.notificationService.showError(message, "Erreur!");
        }
      }, (error) => {
        console.error(error);
      });
  }

  getTaskInfo(task: any) {
    if (task.job_status === 'ARCHIVED') {
      this.openTaskFilesDialog(task.job_id);
    }
    else if (task.job_status === 'VALIDATION' || task.job_status === 'RUN') {
      this.tasksService.setvalidatingTaskId(task.job_id);
      this.router.navigate(['/task-validation']);
    }
  }

  goToDashBoard(task: any) {
    if (task.job_status === 'VALIDATION' || task.job_status === 'RUN') {
      this.router.navigate(['/dashboard', task.job_id]);
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

  saveJobInfos(jobId: string, jobInfos: string[]) {
    localStorage.setItem(`job_infos_${jobId}`, JSON.stringify(jobInfos));
  }

  getSavedJobInfos(jobId: string): string[] | null {
    const savedJobInfos = localStorage.getItem(`job_infos_${jobId}`);
    return savedJobInfos ? JSON.parse(savedJobInfos) : null;
  }

  decrementTime() {
    if (this.tasksList != null) {
      this.tasksList.forEach(x => {
        if (!isNaN(x.job_estimation) && x.job_estimation !== null && x.job_estimation !== 0) {
          x.job_estimation = x.job_estimation - 1;
        }
      });
    }

  }
  reroute() {
    this.router.navigate(['/main-menu']);
  }
}

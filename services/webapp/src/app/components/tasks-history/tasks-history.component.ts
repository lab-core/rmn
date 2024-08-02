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
  displayedColumns: string[] = ['job_name', 'template_name', 'queued_time', 'job_status' ,'job_infos', 'job_deletion'];  //, 'job_retry'
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
    this.socketService.getSocket().on('job_status', async (params: any) => {
      let resp = JSON.parse(params)
      let job_id = resp.job_id;
      let job_status = resp.status;

      this.tasksList.forEach(x => {
        if (x.job_id === job_id) {
          x.job_status = job_status;
          x.info = this.getTaskInfo(job_status);
          if (job_status === 'RETRY') {
              let cleanedInfos = resp.job_infos.slice(1, -1).replace(/['",]/g, '');
              x.job_infos = cleanedInfos.split(/(?<=[.?!])\s+/).map(info => info.trim());
          }
          const message = "Le status de la tâche " + x.job_name + " a changé à: " + x.info + " !";
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
      // let n_total_doc = resp.n_total_doc;
      this.tasksList.forEach(x => {
        if (x.job_id === job_id) {
          // x.job_estimation = Math.round((n_total_doc - lastN) * lastExecTime);
          // x.job_completion = Math.round((lastN / n_total_doc) * 100);
        }
      });
      this.dataSource.data = this.tasksList;
    });

    // setInterval(this.decrementTime.bind(this), 1000);
  }

  ngOnDestroy(): void {
    this.socketService.getSocket().off('document_ready');
    this.socketService.getSocket().off('job_status');
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
    this.userService.addTokens(formdata);
    this.http.post<any>(`${SERVER_URL}jobs`, formdata).subscribe(
      (data) => {
        this.tasksList = data['response'];

        this.tasksList.forEach(x => {
          x.queued_time = new Date(x.queued_time + 'Z')
        })

        this.tasksList.forEach((task: any) => {
          task.info = this.getTaskInfo(task.job_status);
          if (task.job_status === 'RETRY') {
              let cleanedInfos = task.job_infos.slice(1, -1).replace(/['",]/g, '');
              task.job_infos = cleanedInfos.split(/(?<=[.?!])\s+/).map(info => info.trim());
          }
        });

        this.tasksList.forEach(x => {
          const formdata: FormData = new FormData();
          this.userService.addTokens(formdata);
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

              // if (x.job_status === "RUN" || x.job_status === "FINALIZING") {
              //   x.job_estimation = Math.round((response[0].n_total_doc - lastN) * lastExecTime);
              // }
              // if (x.job_status === "QUEUED") {
              //   x.job_completion = 0;
              // } else if (x.job_status === "ERROR") {
              //   x.job_completion = 0;
              // } else if (x.job_status === "ARCHIVED") {
              //   x.job_completion = 100;
              // } else {
              //   x.job_completion = Math.round((lastN / response[0].n_total_doc) * 100);
              // }
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

  getTaskInfo(job_status) {
    switch (job_status) {
      case 'SPLIT':
        return 'En préparation';
      case 'RETRY':
        return 'Rectifier les pdf';
      case 'CORRECTED':
          return 'À nouveau en préparation';
      case 'IGNORED':
        return 'Prêt à la correction';
      case 'QUEUED':
        return 'Prêt à la correction';
      case 'RUN':
        return 'Prêt à la correction et traitement en cours des matricules';
      case 'VALIDATION':
        return 'Prêt à la correction et vérification des matricules';
      case 'VALIDATED':
        return "En attente d'être finalisé";
      case 'FINALIZING':
        return 'Finalisation en cours';
      case 'ARCHIVED':
        return 'Archivée';
      case 'ERROR':
        return 'Erreur';
    }
    return 'Non reconnu: ' + job_status;
  }

  deleteJob(jobId: string): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
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
      width: '60%',
      height: '90%',
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

  retryJob(task: any): void {
    let dialogRef = this.dialog.open(TaskRetryDialogComponent, {
      width: '60%',
      height: '90%',
      data: {taskId: task.job_id, taskName: task.job_name, taskMessages: task.job_infos }
    });
    dialogRef.afterClosed().subscribe(async result => {
        if (result === false) {
          const message = "Une erreur est intervenue lors de la correction de la tâche !";
          this.notificationService.showError(message, "Erreur!");
        } else if (result !== "") {
          task.status = result;
          task.info = this.getTaskInfo(result);
          this.getTasks();  // re render
        }
      }, (error) => {
        console.error(error);
      });
  }

  goToDashBoard(task: any) {
    if (task.job_status === 'ARCHIVED') {
      this.openTaskFilesDialog(task.job_id);
    }
    else if (task.job_status === 'IGNORED' ||
             task.job_status === 'QUEUED' ||
             task.job_status === 'RUN' ||
             task.job_status === 'VALIDATION') {
      this.router.navigate(['/dashboard', task.job_id]);
    } else if (task.job_status === 'RETRY') {
      this.retryJob(task);
    }
  }

  openTaskFilesDialog(jobId: string): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).subscribe(
      (data) => {
        let nbZipFile = data['response']
        let dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '40%',
          height: '90%',
          data: { taskId: jobId, nbZipFile: nbZipFile }
        })
      }, (error) => {
        console.error(error);
      });
  }

  // decrementTime() {
  //   if (this.tasksList != null) {
  //     this.tasksList.forEach(x => {
  //       if (!isNaN(x.job_estimation) && x.job_estimation !== null && x.job_estimation !== 0) {
  //         x.job_estimation = x.job_estimation - 1;
  //       }
  //     });
  //   }

  // }
  reroute() {
    this.router.navigate(['/main-menu']);
  }
}

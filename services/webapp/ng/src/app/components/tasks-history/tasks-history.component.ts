import { HttpClient } from '@angular/common/http';
import { Location } from '@angular/common';
import { Component, OnInit, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { TaskFilesDialogComponent } from './task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from "./task-share-dialog/task-share-dialog.component";
import { TaskRetryDialogComponent } from './task-retry-dialog/task-retry-dialog.component';
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
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
import { filter, first } from 'rxjs/operators';


@Component({
  selector: 'app-tasks-history',
  templateUrl: './tasks-history.component.html',
  styleUrls: ['./tasks-history.component.css']
})
export class TasksHistoryComponent implements OnInit {

  tasksList: Array<any> = [];
  remainingTime: number;
  color: ThemePalette = 'primary';
  mode: ProgressSpinnerMode = 'determinate';
  diameter = 60;
  displayedColumns: string[] = ['job_name', 'template_name', 'queued_time', 'job_status' ,'job_infos', 'job_deletion', 'job_share'];  //, 'job_retry'
  dataSource: MatTableDataSource<any> = new MatTableDataSource<any>();

  @ViewChild(MatPaginator) paginator: MatPaginator;
  @ViewChild(MatSort) sort: MatSort;

  indicator_socket: boolean = false;

  task_hover: boolean = false;

  statusInfo = {
    SPLIT: 'En préparation',
    RETRY: 'Rectifier les pdf',
    CORRECTED: 'À nouveau en préparation',
    IGNORED: 'Prêt à la correction',
    QUEUED: 'Prêt à la correction',
    RUN: 'Prêt à la correction et traitement en cours des matricules',
    VALIDATION: 'Prêt à la correction et vérification des matricules',
    VALIDATED: "En attente d'être finalisé",
    FINALIZING: 'Finalisation en cours',
    ARCHIVED: 'Archivée',
    ERROR: 'Erreur'
  }

  statusColors = {
    SPLIT: "yellow",
    RETRY: "orange",
    CORRECTED: "yellow",
    IGNORED: "green",
    QUEUED: "green",
    RUN: "orange",
    VALIDATION: "blue",
    VALIDATED: "yellow",
    FINALIZING: "green",
    ARCHIVED: "gray",
    ERROR: "red",
  }

  constructor(
    private location: Location,
    private tasksService: TasksService,
    private http: HttpClient,
    public dialog: MatDialog,
    private router: Router,
    private socketService: SocketService,
    private notificationService: NotificationService,
    private userService: UserService
  ) {}

  async ngOnInit(): Promise<void> {
    // Assign the data to the data source for the table to render
    this.getTasks();
    this.socketService.join(this.userService.currentUsername)
    this.socketService.getSocket().on('job_status', async (params: any) => {
      let resp = JSON.parse(params)
      let job_id = resp.job_id;
      let job_status = resp.status;

      const task = this.tasksList.find(task => task.job_id === job_id);
      if (task !== undefined) {
        task.job_status = job_status;
        if (resp.job_infos) task.job_infos = resp.job_infos;
        this.updateTask(task);
        const message = "Le status de la tâche " + task.job_name + " a changé à: " + task.info + " !";
        this.notificationService.showInfo(message, "Alerte!")
      };
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
    if (this.socketService.getSocket()) {
      this.socketService.getSocket().off('document_ready');
      this.socketService.getSocket().off('job_status');
      this.socketService.disconnectSocket();
    }
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
    this.http.post<any>(`${SERVER_URL}jobs`, formdata).pipe(first()).subscribe(
      (data) => {
        this.tasksList = data['response'];
        this.tasksList.forEach((task: any) => {
          this.updateTask(task, true);
        });

        this.tasksList.forEach(x => {
          const formdata: FormData = new FormData();
          this.userService.addTokens(formdata);
          formdata.append('job_id', x.job_id);
          this.http.post<any>(`${SERVER_URL}documents`, formdata).pipe(first()).subscribe(
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

  updateTask(task, updateTime: boolean=false) {
    if (updateTime) {
      task.queued_time = new Date(task.queued_time + 'Z');
    }
    task.info = this.statusInfo[task.job_status];
    if (task.job_status === 'RETRY') {
        const cleanedInfos = task.job_infos.slice(1, -1).replace(/['",]/g, '');
        task.job_infos = cleanedInfos.split(/(?<=[.?!])\s+/).map(info => info.trim());
    }
  }

  openDeleteDialog(jobId: string): void {
    const task = this.tasksList.find(task => { return task.job_id == jobId });
    let dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '40%',
      height: '50%',
      data: "Êtes-vous sur de vouloir supprimer la tâche " + task.job_name + " ?"
    })
    dialogRef.afterClosed().pipe(first()).subscribe(async result => {
      if (result === true) {
        this.deleteJob(jobId);
      }
    });
  }

  deleteJob(jobId: string): void {
    // delete task from list
    const index = this.tasksList.findIndex(task => { return task.job_id == jobId });
    if (index > -1) { // only splice array when item is found
      this.tasksList.splice(index, 1);
      this.dataSource.data = this.tasksList;
    }
    // delete task from server
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/delete`, formdata).pipe(first()).subscribe(
      (data) => {
        this.getTasks();
      }, (error) => {
        console.error(error);
        this.getTasks();
      });
  }

  shareJob(jobId: string, jobName: string): void {
    let dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: {taskId: jobId, taskName: jobName, shareType: 'job', all: true}
    });
    dialogRef.afterClosed().pipe(first()).subscribe(resp => {
      if (resp !== undefined) {
        if (resp.success) {
          if (resp.message)
            this.notificationService.showSuccess(resp.message, "Succès!");
        } else if (resp.message) {
            this.notificationService.showError(resp.message, "Erreur!");
        }
      }
    }, (error) => {
      console.error(error);
    });
  }

  retryJob(task: any): void {
    let dialogRef = this.dialog.open(TaskRetryDialogComponent, {
      width: '60%',
      height: '90%',
      data: {taskId: task.job_id, taskName: task.job_name, taskMessages: task.job_infos}
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async result => {
        if (result === false) {
          const message = "Une erreur est intervenue lors de la correction de la tâche !";
          this.notificationService.showError(message, "Erreur!");
        } else if (result !== "") {
          task.status = result;
          task.info = this.statusInfo[result];
          this.getTasks();  // re render
        }
      }, (error) => {
        console.error(error);
      });
  }

  goToDashBoard(task: any) {
    if (task.job_status === 'ARCHIVED') {
      this.openTaskFilesDialog(task);
    }
    else if (task.job_status === 'IGNORED' ||
             task.job_status === 'QUEUED' ||
             task.job_status === 'RUN' ||
             task.job_status === 'VALIDATION' ||
             task.job_status === 'VALIDATED' ||
             task.job_status === 'FINALIZING') {
      this.router.navigate(['/dashboard', task.job_id]);
    } else if (task.job_status === 'RETRY') {
      this.retryJob(task);
    }
  }

  // disableClick(task: any) {
  //   if (task.job_status === 'ARCHIVED' ||
  //       task.job_status === 'IGNORED' ||
  //       task.job_status === 'QUEUED' ||
  //       task.job_status === 'RUN' ||
  //       task.job_status === 'VALIDATION') {
  //         return "text-decoration: underline;";
  //       }
  //   return "text-decoration: none;";
  // }

  openTaskFilesDialog(task: any): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', task.job_id);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).pipe(first()).subscribe(
      (data) => {
        let dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '40%',
          height: '90%',
          data: { taskId: task.job_id, nbZipFile: data['nZips'], stats: data['stats'] }
        })
        dialogRef.afterClosed().pipe(first()).subscribe(async result => {
          if (result) {
            task.job_status = result;
            this.updateTask(task);
          }
        }, (error) => {
          console.error(error);
        });
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
}

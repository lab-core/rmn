import { HttpClient } from '@angular/common/http';
import { Location } from '@angular/common';
import { Component, OnInit, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { TaskFilesDialogComponent } from '../task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { TaskRetryDialogComponent } from '../task-retry-dialog/task-retry-dialog.component';
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { NavigationStart, Router } from '@angular/router';
import { MatTableDataSource } from '@angular/material/table';
import { MatPaginator } from '@angular/material/paginator';
import { MatSort } from '@angular/material/sort';
import { SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { ThemePalette } from '@angular/material/core';
import { ProgressSpinnerMode } from '@angular/material/progress-spinner';
import { SERVER_URL } from 'src/app/utils';
import { filter, first } from 'rxjs/operators';
import { firstValueFrom } from 'rxjs';
import { DocumentStatus, JobStatus } from '../../generated/rmn-contracts';


@Component({
    selector: 'app-tasks-history',
    templateUrl: './tasks-history.component.html',
    styleUrls: ['./tasks-history.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TasksHistoryComponent implements OnInit {
  readonly JobStatus = JobStatus;

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

  // the rooms this page joined, left when it is destroyed
  private readonly joinedRooms: string[] = [];

  private readonly onJobStatus = (params: any) => {
    const resp = JSON.parse(params)
    const job_id = resp.job_id;
    const job_status = resp.status;

    const task = this.tasksList.find(task => task.job_id === job_id);
    if (task !== undefined) {
      task.job_status = job_status;
      if (resp.job_infos) task.job_infos = resp.job_infos;
      this.updateTask(task);
      const message = "Le status de la tâche " + task.job_name + " a changé à: " + task.info + " !";
      this.notificationService.showInfo(message, "Alerte!")
    };
  };

  private readonly onDocumentReady = (params: any) => {
    // progress events of the running jobs: the table only re-renders
    this.dataSource.data = this.tasksList;
  };

  async ngOnInit(): Promise<void> {
    // the list first: the room joins below used to run over an empty array
    // because getTasks() was not awaited, so live jobs never updated
    await this.getTasks();
    this.joinRoom(this.userService.currentUsername);
    this.socketService.on('job_status', this.onJobStatus);

    // subscribe to all running jobs
    this.tasksList.forEach(x => {
      if (x.job_status == JobStatus.QUEUED || x.job_status == JobStatus.RUN) {
        this.joinRoom(x.job_id);
      }
    });
    this.socketService.on('document_ready', this.onDocumentReady);
  }

  private joinRoom(room: string) {
    this.joinedRooms.push(room);
    this.socketService.join(room);
  }

  ngOnDestroy(): void {
    this.socketService.off('document_ready', this.onDocumentReady);
    this.socketService.off('job_status', this.onJobStatus);
    for (const room of this.joinedRooms) {
      this.socketService.leave(room);
    }
  }

  applyFilter(event: Event) {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();

    if (this.dataSource.paginator) {
      this.dataSource.paginator.firstPage();
    }
  }

  async getTasks(): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    try {
      const data = await firstValueFrom(this.http.post<any>(`${SERVER_URL}jobs`, formdata));
      this.tasksList = data['response'];
      this.tasksList.forEach((task: any) => {
        this.updateTask(task, true);
      });
      // (one POST /documents per task used to follow, computing progress
      // values whose every consumer was commented out)
      this.dataSource.data = this.tasksList;
      this.dataSource.paginator = this.paginator;
      this.dataSource.sort = this.sort;
    } catch (error) {
      console.error(error);
    }
  }

  updateTask(task, updateTime: boolean=false) {
    if (updateTime) {
      task.queued_time = new Date(task.queued_time + 'Z');
    }
    task.info = this.statusInfo[task.job_status];
    // the server sends the messages as one string; a second RETRY event on
    // the same row used to find the array of the first and throw
    if (task.job_status === JobStatus.RETRY && typeof task.job_infos === 'string') {
        const cleanedInfos = task.job_infos.slice(1, -1).replace(/['",]/g, '');
        task.job_infos = cleanedInfos.split(/(?<=[.?!])\s+/).map(info => info.trim());
    }
  }

  openDeleteDialog(jobId: string): void {
    const task = this.tasksList.find(task => { return task.job_id == jobId });
    const dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '80%',
      maxWidth: '500px',
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
    const dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '80%',
      maxWidth: '300px',
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
    const dialogRef = this.dialog.open(TaskRetryDialogComponent, {
      data: {taskId: task.job_id, taskName: task.job_name, taskMessages: task.job_infos},
      height: '95%',
      width: '98%',
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
    // if (task.job_status === 'ARCHIVED') {
    //   this.openTaskFilesDialog(task);
    // }
    if (task.job_status === JobStatus.IGNORED ||
             task.job_status === JobStatus.QUEUED ||
             task.job_status === JobStatus.RUN ||
             task.job_status === JobStatus.VALIDATION ||
             task.job_status === JobStatus.VALIDATED ||
             task.job_status === JobStatus.FINALIZING ||
             task.job_status === JobStatus.ARCHIVED) {
      this.router.navigate(['/dashboard', task.job_id]);
    } else if (task.job_status === JobStatus.RETRY) {
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
        const dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '80%',
          maxWidth: '600px',
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

import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { UserService } from './user.service';
import { NotificationService } from './notification.service';
import { SERVER_URL } from '../utils';
import { map, tap } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class TasksService {

  private validatingTaskId: string;
  private hasTasks: boolean = false;
  private amountTask: number = 0;
  percentDone: number = 0;
  uploadPart1: boolean = false;
  uploadPart2: boolean = false;
  constructor(private router: Router, private http: HttpClient, private userService: UserService, private notification: NotificationService) {
    this.validatingTaskId = localStorage.getItem('job_id');
  }

  setvalidatingTaskId(id: string) {
    this.validatingTaskId = id;
    localStorage.setItem('job_id', id);
  }

  getvalidatingTaskId() {
    return this.validatingTaskId;
  }

  getHasTasks() {
    return this.hasTasks;
  }

  setamountTasks(amount: number) {
    this.amountTask = amount;

    if (this.amountTask != 0) {
      this.hasTasks = true;
    } else {
      this.hasTasks = false;
    }
  }

  getamountTasks() {
    return this.amountTask;
  }

  getpercentageDone() {
    return this.percentDone;
  }

  getUploadPart1State() {
    return this.uploadPart1;
  }

  getUploadPart2State() {
    return this.uploadPart2;
  }


  getTasks() {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    this.http.post<any>(`${SERVER_URL}jobs`, formdata).subscribe(
      (data) => {
        let amountTask = 0;
        let tasksList = data['response'];

        tasksList.forEach((task: any) => {
          if (task.job_status === 'VALIDATION') {
            amountTask += 1;
          }
        });
        this.setamountTasks(amountTask);
      });
  }

  async getTaskById(jobId) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    this.userService.addTokens(formdata);
    const data = await this.http.post<any>(`${SERVER_URL}job`, formdata).toPromise();
    return data['response'];
  }

  async getTask() {
    if (this.validatingTaskId) {
      return this.getTaskById(this.validatingTaskId);
    } else {
      return null;
    }
  }

  private showProgress(event: HttpEvent<any>) {
    console.log(event)
    if (event.type == HttpEventType.UploadProgress) {
      const percentDone = event.total ? Math.round(100 * event.loaded / event.total) : 0
      console.log("Percentage Done : " + percentDone)
    }
  }

  addTask(copies, csv, front_template_id, regular_template_id, n_pages_per_question, n_max_points_per_question, taskName, front_template_name, regular_template_name) {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    formdata.append('front_template_id', front_template_id);
    formdata.append('regular_template_id', regular_template_id);
    formdata.append('zip_file', copies);
    formdata.append('notes_csv_file', csv);
    // formdata.append('nb_pages', number_pages.toString());
    formdata.append('n_pages_per_question', JSON.stringify(Array.from(n_pages_per_question.entries())));
    formdata.append('n_max_points_per_question', JSON.stringify(Array.from(n_max_points_per_question.entries())));
    formdata.append('job_name', taskName);
    formdata.append('front_template_name', front_template_name);
    formdata.append('regular_template_name', regular_template_name);

    this.percentDone = 0;

    this.http.post<any>(`${SERVER_URL}evaluate`, formdata, {reportProgress: true, observe: "events"})
    .subscribe(
      (data) => {
        this.uploadPart1 = true;
        if (data.type == HttpEventType.UploadProgress) {
          this.percentDone = data.total ? Math.round(100 * data.loaded / data.total) : 0
        }
        else if (data.type == HttpEventType.Response) {
          this.percentDone = 100;
          this.router.navigate(['/main-menu']);
          let message: string = "Tâche créée avec succès!"
          this.notification.showInfo(message, "Alerte!")
        }
      },
      (error) => {
        console.error(error.error);
      });

    let tasks: Array<any> = [];
    this.amountTask = 0;

    const formdataJobs: FormData = new FormData();
    formdataJobs.append('user_id', this.userService.currentUsername);
    formdataJobs.append('token', this.userService.token);
    this.http.post<any>(`${SERVER_URL}jobs`, formdataJobs).subscribe(
      (data) => {
        tasks = data['response']
      });

    tasks.forEach((task: any) => {
      if (task.job_status === 'VALIDATION') {
        this.amountTask += 1;
      }
    });

    if (this.amountTask != 0) {
      this.hasTasks = true;
    } else {
      this.hasTasks = false;
    }
  }
}

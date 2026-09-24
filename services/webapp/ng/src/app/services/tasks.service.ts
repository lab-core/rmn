import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { UserService } from './user.service';
import { NotificationService } from './notification.service';
import { SERVER_URL } from '../utils';
import { firstValueFrom } from 'rxjs';
import { first, map, tap } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class TasksService {

  private validatingTaskId: string;
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

  getvalidatingTaskId() : string {
    return this.validatingTaskId;
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

  private showProgress(_event: HttpEvent<any>) {
    // upload progress used to be written to the console on every event; the
    // components show their own progress bars
  }

  async addTask(copies, csv, front_template_id, regular_template_id,
                n_pages_per_question, n_max_points_per_question, bonus_enabled_map,
                taskName, front_template_name, regular_template_name,
                statistics_for_students, validateMatricule): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('front_template_id', front_template_id);
    formdata.append('regular_template_id', regular_template_id);
    formdata.append('zip_file', copies);
    formdata.append('notes_csv_file', csv);
    // formdata.append('nb_pages', number_pages.toString());
    formdata.append('n_pages_per_question', JSON.stringify(Array.from(n_pages_per_question.entries())));
    formdata.append('n_max_points_per_question', JSON.stringify(Array.from(n_max_points_per_question.entries())));
    formdata.append('bonus_enabled_map', JSON.stringify(Array.from(bonus_enabled_map.entries())));
    formdata.append('job_name', taskName);
    formdata.append('front_template_name', front_template_name);
    formdata.append('regular_template_name', regular_template_name);
    formdata.append('statistics_for_students', statistics_for_students);
    formdata.append('validate_matricule', validateMatricule ? "true" : "false");

    this.percentDone = 0;
    return new Promise((resolve, reject) => {
      const sub = this.http.post<any>(`${SERVER_URL}evaluate`, formdata, {reportProgress: true, observe: "events"}).subscribe(
        (data) => {
          this.uploadPart1 = true;
          if (data.type == HttpEventType.UploadProgress) {
            this.percentDone = data.total ? Math.round(100 * data.loaded / data.total) : 0
          }
          else if (data.type == HttpEventType.Response) {
            this.percentDone = 100;
            this.notification.showInfo("Tâche créée avec succès!", "Alerte!");
            sub.unsubscribe();
            resolve();
          }
        },
        (error) => {
          console.error(error.error);
          sub.unsubscribe();
          reject(error);
        }
      );
    });
  }

  async updateTaskStats(jobId: string, taskStats): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('statistics_for_students', taskStats);
    await this.http.post<any>(`${SERVER_URL}job/update/stats`, formdata).toPromise();
  }

  async updateTaskStatus(jobId: string, jobStatus: string): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('job_status', jobStatus);
    await this.http.post<any>(`${SERVER_URL}job/update/status`, formdata).toPromise();
  }

  async updateTaskBonus(jobId: string, bonusMap): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('bonus_enabled_map', JSON.stringify(bonusMap));
    await this.http.post<any>(`${SERVER_URL}job/update/bonus`, formdata).toPromise();
  }

  /**
   * Change the name, points or pages per question of a task (each optional).
   * Resolves with how many grades went back to validation and how many
   * rejected copies are split again; rejects with the server's message.
   */
  async updateTaskSettings(jobId: string, changes: {
    jobName?: string,
    nMaxPointsPerQuestion?: Array<[string, number]>,
    nPagesPerQuestion?: Array<[string, number]>,
  }): Promise<{ flagged: number, resplit: number }> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    if (changes.jobName !== undefined) {
      formdata.append('job_name', changes.jobName);
    }
    if (changes.nMaxPointsPerQuestion !== undefined) {
      formdata.append('n_max_points_per_question', JSON.stringify(changes.nMaxPointsPerQuestion));
    }
    if (changes.nPagesPerQuestion !== undefined) {
      formdata.append('n_pages_per_question', JSON.stringify(changes.nPagesPerQuestion));
    }
    try {
      const resp = await firstValueFrom(this.http.post<any>(`${SERVER_URL}job/update/settings`, formdata));
      return { flagged: resp.flagged ?? 0, resplit: resp.resplit ?? 0 };
    } catch (error) {
      const message = error?.error?.response;
      throw new Error(typeof message === 'string' ? message.replace(/^Error: /, '') : 'la modification a échoué.');
    }
  }

}

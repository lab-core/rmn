import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';
import { timeout } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class ValidationService {

  constructor(
    private router: Router,
    private http: HttpClient,
    private userService: UserService
  ) { }

  async validateDocument(jobId: string, validatingCopy: number, file: File,
                         questionIndex, grade, nMaxPointsPerQuestion, status,
                         version, annotations) {
    const formData: FormData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', jobId);
    formData.append('document_index', validatingCopy.toString());
    formData.append('file', file);
    if (questionIndex) {
      formData.set('question_index', questionIndex);
    }
    if (grade !== undefined) {
      formData.append('grades', JSON.stringify([grade]));
    }
    formData.append('status', status);
    if (version !== undefined) {
      formData.append('version', version.toString());
    }
    if (annotations !== undefined) {
      formData.append('annotations', JSON.stringify(annotations));
    }

    let response;
    try {
        const promise = await this.http.post<any>(`${SERVER_URL}document/update`, formData).pipe(timeout(15000)).toPromise();
        response = promise['response'];
    } catch (error) {
        console.error(error);
    }
    return response;
  }

  async validateJob(jobId, moodle_ind) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    this.userService.addTokens(formdata);
    formdata.append('moodle_ind', (Number(moodle_ind)).toString());
    let response;
    try {
      const promise = await this.http.post<any>(`${SERVER_URL}job/validate`, formdata).toPromise();
      response = promise['response'];
    } catch (error) {
      console.error(error);
    }
    return response;
  }

}

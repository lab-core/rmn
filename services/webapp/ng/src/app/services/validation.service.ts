import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';

@Injectable({
  providedIn: 'root'
})
export class ValidationService {

  constructor(
    private router: Router,
    private http: HttpClient,
    private userService: UserService
  ) { }

  /** Saves a copy: its status, grade and tag, and the pdf as the viewer
   *  rendered it, its annotations written in it (the server keeps that pdf
   *  as the copy's new version). `submitted`: validated with no grade, the
   *  copy is corrected and its grade is left to the reader. */
  async validateDocument(jobId: string, validatingCopy: number, file: File,
                         questionIndex, grade, nMaxPointsPerQuestion, status, tag,
                         submitted: boolean = false) {
    const formData: FormData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', jobId);
    formData.append('document_index', validatingCopy.toString());
    formData.append('file', file);
    if (questionIndex) {
      formData.set('question_index', questionIndex);
    }
    if (grade != undefined) {
      formData.append('grades', grade.toString());
    }
    formData.append('status', status);
    if (tag != undefined) {
      formData.append('tag', tag);
    }
    if (submitted) {
      formData.append('submitted', 'true');
    }

    let response;
    try {
        const promise = await this.http.post<any>(`${SERVER_URL}documents/update`, formData).toPromise();
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
      const promise = await this.http.post<any>(`${SERVER_URL}jobs/validate`, formdata).toPromise();
      response = promise['response'];
    } catch (error) {
      console.error(error);
    }
    return response;
  }

}

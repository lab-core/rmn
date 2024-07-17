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

  async validateDocument(jobId, validatingCopy, file, copiesInformations, registration, nMaxPointsPerQuestion = new Map(), status) {
    const formData: FormData = new FormData();
    this.userService.addTokens(formData);
    formData.append('job_id', jobId);
    formData.append('document_index', validatingCopy.toString());
    formData.append('file', file);
    const serializedCopiesInformations = JSON.stringify(
        Array.from(copiesInformations.entries()).map(([key, value]) => [key, Array.from(value.entries())])
    );
    formData.append('copies_informations', serializedCopiesInformations);
    
    // only append n_max_points_per_question if provided
    if (nMaxPointsPerQuestion && nMaxPointsPerQuestion.size > 0) {
        const serializedNMaxPointsPerQuestion = JSON.stringify(Array.from(nMaxPointsPerQuestion.entries()));
        formData.append('n_max_points_per_question', serializedNMaxPointsPerQuestion);
    }
    
    formData.append('matricule', registration);
    formData.append('status', status);

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
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
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

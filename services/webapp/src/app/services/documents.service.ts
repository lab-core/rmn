import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';

@Injectable({
  providedIn: 'root'
})
export class DocumentsService {

  jobId: string;
  documentsList: Array<any>;
  groupsList: Array<string>;

  constructor(private http: HttpClient,
              private userService: UserService) { }

  async getDocuments(jobId: string, questions: boolean) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    if (questions) {
      formdata.append('questions', 'true');
    }
    this.userService.addTokens(formdata);
    this.groupsList = [""];

    try {
      const promise = await this.http.post<any>(`${SERVER_URL}documents`, formdata).toPromise();
      this.documentsList = promise['response'];

      // fetch groups if any
      this.documentsList.forEach((exam: any) => {
        if (exam.group && !this.groupsList.includes(exam.group)) {
            this.groupsList.push(exam.group);
        }
      });
      this.groupsList.sort((a, b) => {
        if (a === "") return -1;
        return a.localeCompare(b);
      });
    } catch (error) {
      console.error(error);
    }
  }
}

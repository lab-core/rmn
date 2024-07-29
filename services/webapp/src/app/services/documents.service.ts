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
  nMaxPointsPerQuestion = new Map<string, number>();
  copiesInformations = new Map<string, Map<string, number>>();
  bonusEnabledMap = new Map<string, boolean>();

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

  async getJobInfos(jobId: string) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    this.userService.addTokens(formdata);

    try {
      const promise = await this.http.post<any>(`${SERVER_URL}job`, formdata).toPromise();
      if (!promise || !promise['response']) {
        throw new Error("Invalid response from server");
      }

      let job = promise['response'];

      // fetch n_max_points_per_question
      if (!job['n_max_points_per_question']) {
        throw new Error("n_max_points_per_question is undefined");
      }
      const nMaxPointsPerQuestionArray = job['n_max_points_per_question'];
      this.nMaxPointsPerQuestion = new Map<string, number>(
        nMaxPointsPerQuestionArray.map((item: [string, number]) => [item[0], item[1]])
      );

      // fetch copies_informations
      if (!job['copies_informations']) {
        throw new Error("copies_informations is undefined");
      }
      const copiesInformationsArray = job['copies_informations'];
      this.copiesInformations = new Map<string, Map<string, number>>(
        copiesInformationsArray.map((item: [string, Array<[string, number]>]) =>
          [item[0], new Map<string, number>(item[1].map(innerItem => [innerItem[0], innerItem[1]]))]
        )
      );

      // fetch bonus_enabled_map
      if (!job['bonus_enabled_map']) {
        throw new Error("bonus_enabled_map is undefined");
      }
      const bonusEnabledMapArray = job['bonus_enabled_map'];
      this.bonusEnabledMap = new Map<string, boolean>(
        bonusEnabledMapArray.map((item: [string, boolean]) => [item[0], item[1]])
      );

    } catch (error) {
      console.error('Error in getJobInfos:', error);
    }
  }

}

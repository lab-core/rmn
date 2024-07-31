import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';


class PDFSource {
  index: number;
  version: number;
  url: string;
  timestamp_min: number;
  lastVersion: number;

  constructor(index: number, url: string, version) {
    this.index = index;
    this.url = url;
    this.version;
    this.timestamp_min = Date.now() / 60000;
  }

  isOlderThan(minutes) {
    let t = Date.now() / 60000;
    return t - this.timestamp_min > minutes;
  }

  canBeUsed(minutes, version=undefined) {
    return !this.isOlderThan(minutes) && this.version === version && (version === undefined || version <= this.lastVersion);
  }
}

@Injectable({
  providedIn: 'root'
})
export class DocumentsService {

  jobId: string;
  documentsList: Array<any>;
  groupsList: Array<string>;
  pdfSources = new Map<number, PDFSource>();
  questions: boolean;  // true if fetch question, false for documents
  refreshMinutes: number = 15;  // refresh document every X minutes

  constructor(private http: HttpClient,
              private userService: UserService) { }

  async getDocuments(jobId: string, questions: boolean) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    this.questions = questions;
    if (questions) {
      formdata.append('questions', 'true');
    }
    this.userService.addTokens(formdata);
    this.groupsList = [""];

    try {
      const promise = await this.http.post<any>(`${SERVER_URL}documents`, formdata).toPromise();
      this.documentsList = promise['response'];
      this.pdfSources.clear();

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

  async downloadPdf(jobId: string, index: number, version=undefined): Promise<PDFSource> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('document_index', index.toString());
    if (this.questions) {
      formdata.append('questions', 'true');
    }
    if (version !== undefined) {
      if (version < 0) version = 0;
      formdata.append('document_version', version.toString());
    }

    try {
      const data = await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).toPromise();
      const url = window.URL.createObjectURL(data);
      this.pdfSources[index] = new PDFSource(index, url, version);
      this.pdfSources[index].lastVersion = await this.getLastVersion(jobId, index);
      return this.pdfSources[index];
    } catch (error) {
      console.error(error);
      return null;
    }
  }

  async getLastVersion(jobId: string, index: number): Promise<number> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('document_index', index.toString());
    if (this.questions) {
      formdata.append('questions', 'true');
    }

    await this.http.post(`${SERVER_URL}document/last_version`, formdata)
      .toPromise()
      .then(async (data: any) => {
           return data["last_version"];
      })
      .catch((error) => {
          console.error(error);
      });
      return null;
  }

  async getPdfSource(jobId: string, index: number, version=undefined, minutes=undefined): Promise<PDFSource> {
    let pdfSource = this.pdfSources[index];
    if (pdfSource && pdfSource.canBeUsed(minutes || this.refreshMinutes, version)) {
      return pdfSource;
    } else {
      let pdfSource = await this.downloadPdf(jobId, index, version);
      return pdfSource;
    }
  }
}

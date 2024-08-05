import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EditorAnnotation } from 'ngx-extended-pdf-viewer';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';


export class PDFSource {
  index: number;
  version: number;
  annotations: EditorAnnotation[];
  url: string;
  timestamp_min: number;
  lastVersion: number;

  constructor(index: number, url: string, version) {
    this.index = index;
    this.url = url;
    this.version = version;
    this.timestamp_min = Date.now() / 60000;
    this.annotations = [];
  }

  setLastVersion(lastVersion: number) {
    this.lastVersion = lastVersion;
    if (this.version === undefined || this.version > this.lastVersion) {
      this.version = this.lastVersion;
    }
  }

  isOlderThan(minutes) {
    let t = Date.now() / 60000;
    return t - this.timestamp_min > minutes;
  }

  canBeUsed(minutes, version=undefined) {
    return !this.isOlderThan(minutes) && (version === undefined || this.version === version);
  }
}

@Injectable({
  providedIn: 'root'
})
export class DocumentsService {

  jobId: string;
  documentsList: Array<any>;
  questions: boolean;  // true if fetch question, false for documents
  refreshMinutes: number = 15;  // refresh document every X minutes

  private pdfSources = new Map<number, PDFSource>();

  constructor(private http: HttpClient,
              private userService: UserService) { }

  async getDocuments(jobId: string, questions: boolean, docIndices: number[]=undefined) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', jobId);
    this.questions = questions;
    if (questions) {
      formdata.append('questions', 'true');
    }
    if (docIndices) {
      formdata.append('documents_indices', JSON.stringify(docIndices));
    }
    this.userService.addTokens(formdata);

    try {
      const promise = await this.http.post<any>(`${SERVER_URL}documents`, formdata).toPromise();
      this.documentsList = promise['response'] || [];
      this.clearPdfSources();
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
      formdata.append('version', version.toString());
    }

    try {
      const data = await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).toPromise();
      const url = window.URL.createObjectURL(data);
      const pdfSource = new PDFSource(index, url, version);
      this.pdfSources[index] = pdfSource;
      await this.getAnnotations(jobId, pdfSource);
      return pdfSource;
    } catch (error) {
      console.error(error);
      return null;
    }
  }

  async getAnnotations(jobId: string, pdfSource: PDFSource): Promise<void> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('document_index', pdfSource.index.toString());
    if (pdfSource.version !== undefined) {
      formdata.append('version', pdfSource.version.toString());
    }
    if (this.questions) {
      formdata.append('questions', 'true');
    }

    await this.http.post(`${SERVER_URL}document/annotations`, formdata)
      .toPromise()
      .then(async (data: any) => {
        pdfSource.setLastVersion(data["last_version"]);
        pdfSource.annotations = data["annotations"] || [];
      })
      .catch((error) => {
          console.error(error);
      });
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

  clearPdfSources() {
    this.pdfSources = new Map<number, PDFSource>();
  }
}

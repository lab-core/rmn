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
    return this.annotations.length == 0 &&
    (minutes === undefined || !this.isOlderThan(minutes)) &&
    (version === undefined || this.version === version);
  }

  async toJSONDict() {
    const blob = await fetch(this.url).then(r => r.blob());
    return {
      index: this.index,
      version: this.version,
      annotations: this.annotations,
      timestamp_min: this.timestamp_min,
      lastVersion: this.lastVersion,
      base64: await this.readBlobSync(blob),
    }
  }

  async readBlobSync(blob: Blob): Promise<string | ArrayBuffer> {
     return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);  // base64 string of the pdf
    });
  }

  async loadJSONDict(dict) {
    const blob = await fetch(dict['base64']).then(r => r.blob());
    this.revokeURL();
    this.url = window.URL.createObjectURL(blob);
    this.index = dict['index'];
    this.version = dict['version'];
    this.annotations = dict['annotations'];
    this.timestamp_min = dict['timestamp_min'];
    this.lastVersion = dict['lastVersion'];
  }

  revokeURL() {
    if (this.url) {
      URL.revokeObjectURL(this.url);
    }
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
      // const src = base64Src ? await this.readBlobSync(data) : window.URL.createObjectURL(data);
      const url = window.URL.createObjectURL(data);
      const pdfSource = new PDFSource(index, url, version);
      if (this.pdfSources[index]) {
        this.pdfSources[index].revokeURL();
      }
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
    let pdfSource = this.getAvailablePdfSource(jobId, index, version, minutes || this.refreshMinutes);
    if (pdfSource !== undefined) {
      return pdfSource;
    } else {
      let pdfSource = await this.downloadPdf(jobId, index, version);
      return pdfSource;
    }
  }

  getAvailablePdfSource(jobId: string, index: number, version=undefined, minutes=undefined) {
    let pdfSource = this.pdfSources[index];
    if (pdfSource && pdfSource.canBeUsed(minutes, version)) {
      return pdfSource;
    }
    return undefined;
  }

  clearPdfSources() {
    for (let pdfSrc of Object.values(this.pdfSources)) {
      pdfSrc.revokeURL();
    }
    this.pdfSources = new Map<number, PDFSource>();
  }
}

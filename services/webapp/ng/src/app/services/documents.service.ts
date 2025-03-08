import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EditorAnnotation } from 'ngx-extended-pdf-viewer';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';


export class PDFSource {
  index: number;
  version: number;
  annotations: EditorAnnotation[];
  url?: string;
  blob?: Blob;
  timestamp_min: number;
  lastVersion: number;
  modified: boolean;

  constructor(index: number=undefined, url: string=undefined, version=undefined) {
    this.index = index;
    this.url = url;
    this.version = version;
    this.timestamp_min = Date.now() / 60000;
    this.annotations = [];
  }

  destroy() {
    this.revokeURL();
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
    return (minutes === undefined || !this.isOlderThan(minutes)) &&
          (version === undefined || this.version === version);
  }

  toMinimalJSONDict() {
    return {
      index: this.index,
      version: this.version,
      annotations: this.annotations,
      timestamp_min: this.timestamp_min,
      lastVersion: this.lastVersion,
    }
  }

  async toJSONDict() {
    let json = this.toMinimalJSONDict();
    const blob = await fetch(this.url).then(r => r.blob());
    json['base64'] = await PDFSource.readBlobSync(blob);
    return json;
  }

  static async readBlobSync(blob: Blob | File): Promise<string | ArrayBuffer> {
     return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);  // base64 string of the pdf
    });
  }

  async loadMinimalDict(dict) {
    this.index = dict['index'];
    this.version = dict['version'];
    this.annotations = dict['annotations'];
    this.timestamp_min = dict['timestamp_min'];
    this.lastVersion = dict['lastVersion'];
  }

  async loadDict(dict) {
    this.loadMinimalDict(dict);
    this.blob = dict['blob'] || await fetch(dict['base64']).then(async (r) => r.blob());
    if (this.blob) {
      this.url = window.URL.createObjectURL(this.blob);
    }
  }

  revokeURL() {
    if (this.url) {
      URL.revokeObjectURL(this.url);
    }
  }

  save(jobId: string) {
    const jsonDict = this.toMinimalJSONDict();
    localStorage.setItem(`${jobId}_pdf_${this.index}`, JSON.stringify(jsonDict));
  }

  restore(jobId: string) {
    const jsonDict = localStorage.getItem(`${jobId}_pdf_${this.index}`);
    if (jsonDict) {
      const dict = JSON.parse(jsonDict);
      if (this.version === dict.version) {
        this.loadMinimalDict(dict);
        this.modified = true;
      }
    }
  }

  clear(jobId: string) {
    localStorage.removeItem(`${jobId}_pdf_${this.index}`);
  }

  static clearAll(jobId: string, size: number) {
    for (let i = 0; i < size; i++) {
      localStorage.removeItem(`${jobId}_pdf_${i}`);
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
    } catch (error) {
      console.error(error);
    }
  }

  async downloadPdf(jobId: string, index: number, fetchAnnotations: boolean=true, version=undefined): Promise<PDFSource> {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    formdata.append('document_index', index.toString());
    if (!fetchAnnotations) {
      formdata.append('with_annotations', 'true');
    }
    if (this.questions) {
      formdata.append('questions', 'true');
    }
    if (version !== undefined) {
      if (version < 0) version = 0;
      formdata.append('version', version.toString());
    }

    try {
      const data = await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).toPromise();
      if (data) {
        const url = window.URL.createObjectURL(data);
        const pdfSource = new PDFSource(index, url, version);
        this.pdfSources[index] = pdfSource;
        if (fetchAnnotations) {
          await this.getAnnotations(jobId, pdfSource);
          pdfSource.restore(jobId);
        }
        return pdfSource;
      }
      return null;
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

  async getPdfSource(jobId: string, index: number, fetchAnnotations: boolean=true,
                     version=undefined, minutes=undefined): Promise<PDFSource> {
    let pdfSource = this.getAvailablePdfSource(jobId, index, version, minutes || this.refreshMinutes);
    if (pdfSource !== undefined) {
      return pdfSource;
    } else {
      let pdfSource = await this.downloadPdf(jobId, index, fetchAnnotations, version);
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

  async loadPDFSource(dict): Promise<PDFSource> {
    const pdfSrc = new PDFSource();
    await pdfSrc.loadDict(dict);
    this.pdfSources[pdfSrc.index] = pdfSrc;
    return pdfSrc;
  }

  clearPdfSources() {
    for (let pdfSrc of Object.values(this.pdfSources)) {
      pdfSrc.revokeURL();
    }
    this.pdfSources = new Map<number, PDFSource>();
  }
}

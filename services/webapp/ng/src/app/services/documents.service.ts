import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';
import { PDFSource } from './pdf-source';

// the class used to live here: keep the import path working
export { PDFSource };


@Injectable({
  providedIn: 'root'
})
export class DocumentsService {

  jobId: string;
  documentsList: Array<any>;
  questions: boolean;  // true if fetch question, false for documents
  refreshMinutes: number = 15;  // refresh document every X minutes

  // keyed by job AND document index: keyed by the index alone, job A's
  // document 7 was served as job B's until clearPdfSources() ran
  private pdfSources = new Map<string, PDFSource>();

  constructor(private http: HttpClient,
              private userService: UserService) {
    // the previous user's pdfs and object URLs must not survive the session
    this.userService.loggedOut$.subscribe(() => this.clearPdfSources());
  }

  private static key(jobId: string, index: number): string {
    return `${jobId}:${index}`;
  }

  private setPdfSource(jobId: string, pdfSource: PDFSource) {
    const key = DocumentsService.key(jobId, pdfSource.index);
    const previous = this.pdfSources.get(key);
    if (previous && previous !== pdfSource) {
      previous.revokeURL();  // overwriting without revoking leaked a blob per refresh
    }
    this.pdfSources.set(key, pdfSource);
  }

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
        this.setPdfSource(jobId, pdfSource);
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
    const pdfSource = this.getAvailablePdfSource(jobId, index, version, minutes || this.refreshMinutes);
    if (pdfSource !== undefined) {
      return pdfSource;
    } else {
      const pdfSource = await this.downloadPdf(jobId, index, fetchAnnotations, version);
      return pdfSource;
    }
  }

  getAvailablePdfSource(jobId: string, index: number, version=undefined, minutes=undefined) {
    const pdfSource = this.pdfSources.get(DocumentsService.key(jobId, index));
    if (pdfSource && pdfSource.canBeUsed(minutes, version)) {
      return pdfSource;
    }
    return undefined;
  }

  async loadPDFSource(dict, jobId: string): Promise<PDFSource> {
    const pdfSrc = new PDFSource();
    await pdfSrc.loadDict(dict);
    this.setPdfSource(jobId, pdfSrc);
    return pdfSrc;
  }

  clearPdfSources() {
    for (const pdfSrc of this.pdfSources.values()) {
      pdfSrc.revokeURL();
    }
    this.pdfSources.clear();
  }
}

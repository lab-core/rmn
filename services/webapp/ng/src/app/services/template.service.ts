import { Injectable } from '@angular/core'

@Injectable({
  providedIn: 'root'
})
export class TemplateService {

  editingTemplate: boolean = false;

  templateFile: File;
  templateUrl: string;

  templateName: string;
  templateId: string;

  constructor() { }

  async createNewTemplate(data: Blob) {
    let url = window.URL.createObjectURL(data);
    this.templateUrl = url;

    // let loadingTask = pdfjs.getDocument(url);
    // let pdf = await loadingTask.promise;
    // let page = await pdf.getPage(1);
    // this.template = page;
  }

  setFile(file: File) {
    this.templateFile = file;
  }

  getFile() {
    return this.templateFile;
  }

  getTemplateUrl() {
    return this.templateUrl;
  }

  setTemplateName(name: string) {
    this.templateName = name;
  }

  getTemplateName() {
    return this.templateName;
  }

  setTemplateId(id: string) {
    this.templateId = id;
  }

  getTemplateId() {
    return this.templateId;
  }
}

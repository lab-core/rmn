import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class TemplateService {

  templateFile: File;
  templateUrl: string;

  templateName: string;
  templateId: string;

  constructor() { }

  async createNewTemplate(data: Blob) {
    let url = window.URL.createObjectURL(data);
    this.templateUrl = url;
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

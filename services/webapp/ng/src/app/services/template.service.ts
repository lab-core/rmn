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
  locked: boolean = false;

  constructor() { }

  async createNewTemplate(data: Blob) {
    this.revokeTemplate();
    let url = window.URL.createObjectURL(data);
    this.templateUrl = url;
  }

  revokeTemplate() {
    if (this.templateUrl) {
      URL.revokeObjectURL(this.templateUrl);
    }
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

  setLocked(locked: boolean) {
    this.locked = locked;
  }

  getLocked() {
    return this.locked;
  }
}

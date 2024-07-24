import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class TemplateService {

  editingTemplate: boolean = false;
  templateFile: File;
  templateUrl: string;

  templateName: string;
  templateId: string;
  templatePage: number = 1;

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

  setPage(page: number) {
    this.templatePage = page;
  }

  getPage() {
    return this.templatePage;
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

  setEditingExisting(isEditing: boolean) {
    this.editingTemplate = isEditing;
  }

  checkEditing() {
    return this.editingTemplate;
  }
}

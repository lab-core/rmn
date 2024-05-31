import { Injectable } from '@angular/core';
// import * as pdfjs from 'pdfjs-dist/build/pdf';
// import * as pdfjsWorker  from 'pdfjs-dist/build/pdf.worker.entry';
// pdfjs.GlobalWorkerOptions.workerSrc = pdfjsWorker;
// NOTE: This is a workaround for the pdfjs-dist lib not being compatible with ngx-extended-pdf-viewer.

@Injectable({
  providedIn: 'root'
})
export class TemplateService {

  editingTemplate: boolean = false;

  templateFile : File;
  template : any;

  templateName : string;
  templateId : string;

  constructor() { }

  async createNewTemplate(copy : File) {
    let url = URL.createObjectURL(copy);
    // let loadingTask = pdfjs.getDocument(url);
    // let pdf = await loadingTask.promise;

    // let page = await pdf.getPage(1);
    // this.template = page;
  }

  setFile(file: File){
    this.templateFile = file;
  }

  getFile(){
    return this.templateFile;
  }

  getTemplate() {
    return this.template;
  }

  setTemplateName(name: string){
    this.templateName = name;
  }

  getTemplateName(){
    return this.templateName;
  }

  setTemplateId(id: string){
    this.templateId = id;
  }

  getTemplateId(){
    return this.templateId;
  }

  setEditingExisting(isEditing: boolean){
    this.editingTemplate = isEditing;
  }

  checkEditing() {
    return this.editingTemplate;
  }
}

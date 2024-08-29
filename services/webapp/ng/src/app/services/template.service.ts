import { Injectable } from '@angular/core'

@Injectable({
  providedIn: 'root'
})
export class TemplateService {
  file: File;
  url: string;

  name: string;
  id: string;
  locked: boolean = false;
  nQuestions: number = 0;

  constructor() {
    this.id = localStorage.getItem('templateId');
  }

  clearId() {
    this.id = undefined;
    localStorage.removeItem('templateId');
  }

  async createNewTemplate(data: Blob) {
    this.revokeUrl();
    let url = window.URL.createObjectURL(data);
    this.url = url;
  }

  revokeUrl() {
    if (this.url) {
      URL.revokeObjectURL(this.url);
    }
  }

  setFile(file: File) {
    this.file = file;
  }

  getFile() {
    return this.file;
  }

  getUrl() {
    return this.url;
  }

  setName(name: string) {
    this.name = name;
  }

  getName() {
    return this.name;
  }

  setId(id: string) {
    this.id = id;
    localStorage.setItem('templateId', id);
  }

  getId() {
    return this.id;
  }

  setNQuestions(nQuestions: number) {
    this.nQuestions = nQuestions;
  }

  getNQuestions() {
    return this.nQuestions;
  }

  setLocked(locked: boolean) {
    this.locked = locked;
  }

  getLocked() {
    return this.locked;
  }
}

import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { UserService } from 'src/app/services/user.service';
import { TasksService } from 'src/app/services/tasks.service';
import { SERVER_URL } from 'src/app/utils';
import { NotificationService } from 'src/app/services/notification.service';
import { FormBuilder, Validators } from '@angular/forms';
import { MatSelectChange } from '@angular/material/select';

import * as saveAs from 'file-saver';

//DropBox API
declare function dropboxFiles(): void;
declare function dropboxCSV(): void;

//OneDrive API
declare function onedrivePicker(): void;
declare function onedrivePickerCSV(): void;

@Component({
  selector: 'app-new-exam-correction',
  templateUrl: './new-exam-correction.component.html',
  styleUrls: ['./new-exam-correction.component.css']
})
export class NewExamCorrectionComponent implements OnInit {
  copies: File;
  csv: File;
  firstFormGroup: any;
  secondFormGroup: any;
  thirdFormGroup: any;
  fourthFormGroup: any;
  isLinear = true;
  nQuestionsReadOnly = true;

  copiesName: string = "";
  csvName: string = "";
  templates: Array<Map<string, string>>;
  selectedFrontTemplate: string = "";
  selectedRegularTemplate: string = "";
  disabled: boolean = false;
  uploading: boolean = false;
  statisticsForStudents: boolean = true;

  nQuestions: number = 0;
  totalPages: number = 0;
  totalPoints: number = 0;
  totalBonus: number = 0;
  nPagesPerQuestion = new Map<string, number>();
  nMaxPointsPerQuestion = new Map<string, number>();
  bonusEnabledMap = new Map<string, boolean>();
  questionKeys: string[] = [];
  taskName: string = "Tâche";

  suffix: string = "";
  presentationCopies: File;
  latexFrontPage: File;
  latexInputPage: File;

  presentationCopiesName: string = "";
  latexFrontPageName: string = "";

  showDropbox: boolean = false;
  showOneDrive: boolean = false;

  constructor(
    private router: Router,
    private tasksService: TasksService,
    private http: HttpClient,
    private userService: UserService,
    private notifyService: NotificationService,
    private _formBuilder: FormBuilder
  ) {
    this.firstFormGroup = this._formBuilder.group({
      firstCtrl: ['', Validators.required],
    });
    this.secondFormGroup = this._formBuilder.group({
      secondCtrl: ['', Validators.required],
    });
    this.thirdFormGroup = this._formBuilder.group({
      thirdCtrl: ['', Validators.required],
    });
    this.fourthFormGroup = this._formBuilder.group({
      fourthCtrl: ['', Validators.required],
    });
  }

  async ngOnInit(): Promise<void> {
    this.getTemplates();
  }

  selectText(event): void {
    event.target.select();
  }

  onQuestionIndexChange(event: MatSelectChange): void {
    if (event.value) {
      const template = this.templates.find(t => t['template_id'] === event.value);
      this.nQuestions = template["n_questions"];
      this.updateQuestionsCount();
    }
  }

  updateTotals() {
    this.totalPages = 0;
    this.totalPoints = 0;
    this.totalBonus = 0;
    this.questionKeys.forEach(key => {
    this.totalPages += this.nPagesPerQuestion.get(key) || 0;
      if (!this.bonusEnabledMap.get(key)) {
        this.totalPoints += this.nMaxPointsPerQuestion.get(key) || 0;
      }
    });
  }

  updateQuestionsCount() {
    this.nPagesPerQuestion.clear();
    this.nMaxPointsPerQuestion.clear();
    this.questionKeys = [];
    this.bonusEnabledMap.clear();
    for (let i = 1; i <= this.nQuestions; i++) {
      this.nPagesPerQuestion.set(`Q${i}`, 0);
      this.nMaxPointsPerQuestion.set(`Q${i}`, 0);
      this.questionKeys.push(`Q${i}`);
      this.bonusEnabledMap.set(`Q${i}`, false);
    }
  }

  updatePageCount(key: string, event: Event) {
    const inputElement = event.target as HTMLInputElement;
    const pageCount = parseInt(inputElement.value, 10);
    this.nPagesPerQuestion.set(key, pageCount);
    this.updateTotals();
  }

  updateMaxPoints(key: string, event: Event) {
    const inputElement = event.target as HTMLInputElement;
    const maxPoints = parseInt(inputElement.value, 10);
    this.nMaxPointsPerQuestion.set(key, maxPoints);
    this.updateTotals();
  }

  toggleBonus(key: string) {
    const currentValue = this.bonusEnabledMap.get(key) || false;
    this.bonusEnabledMap.set(key, !currentValue);
    this.updateTotals();
  }

  updateSuffix(event: KeyboardEvent) {
    let regex = new RegExp("^[a-zA-ZÀ-ÿ0-9\-\_\ ]+$");
    let key = String.fromCharCode(!event.charCode ? event.which : event.charCode);
    if (!regex.test(key)) {
      event.preventDefault();
    }
  }

  presentationCopiesFileEvent(fileInput: Event) {
    let target = fileInput.target as HTMLInputElement;
    let file: File = (target.files as FileList)[0];
    this.presentationCopiesName = file.name;
    this.presentationCopies = file;
  }

  latexFrontPageEvent(fileInput: Event) {
    let target = fileInput.target as HTMLInputElement;
    let file: File = (target.files as FileList)[0];
    this.latexFrontPageName = file.name;
    this.latexFrontPage = file;
  }

  getDropBoxUpload() {
    if (this.copiesName != "") {
      this.copies = null;
      this.copiesName = "";
    }

    if (this.getOneDriveAttibute("files-onedrive-input") != null) {
      document.getElementById("files-onedrive-input").removeAttribute("value");
      document.getElementById("files-upload-label").removeAttribute("value");
      document.getElementById("files-upload-label").innerHTML = "";
    }

    dropboxFiles();
  }

  getOneDriveUpload() {
    if (this.copiesName != "") {
      this.copies = null;
      this.copiesName = "";
    }

    if (this.getDropboxAttibute("files-dropbox-input") != null) {
      document.getElementById("files-dropbox-input").removeAttribute("value");
      document.getElementById("files-upload-label").removeAttribute("value");
      document.getElementById("files-upload-label").innerHTML = "";
    }

    onedrivePicker();
  }

  getDropBoxUploadCSV() {
    if (this.csvName != "") {
      this.csv = null;
      this.csvName = "";
    }

    if (this.getOneDriveAttibute("csv-onedrive-input") != null) {
      document.getElementById("csv-onedrive-input").removeAttribute("value");
      document.getElementById("csv-upload-label").removeAttribute("value");
      document.getElementById("csv-upload-label").innerHTML = "";
    }

    dropboxCSV();
  }

  getOneDriveUploadCSV() {
    if (this.csvName != "") {
      this.csv = null;
      this.csvName = "";
    }

    if (this.getDropboxAttibute("csv-dropbox-input") != null) {
      document.getElementById("csv-dropbox-input").removeAttribute("value");
      document.getElementById("csv-upload-label").removeAttribute("value");
      document.getElementById("csv-upload-label").innerHTML = "";
    }

    onedrivePickerCSV();
  }

  async getTemplates() {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    this.http.post<any>(`${SERVER_URL}user/template`, formdata).subscribe(
      (data) => {
        this.templates = data['response'];
        if (this.templates.length === 0) {
          this.notifyService.showWarning("Veuillez créer un template avant de commencer une correction.", "Avertissement");
          this.disabled = true;
        } else {
          // this.selectedFrontTemplate = this.templates[0]['template_id'];
          // this.selectedRegularTemplate = this.templates[0]['template_id'];
        }
      });
  }

  CopiesFileEvent(fileInput: Event) {
    if (this.getDropboxAttibute("files-dropbox-input") != null) {
      document.getElementById("files-dropbox-input").removeAttribute("value");
    }

    if (this.getOneDriveAttibute("files-onedrive-input") != null) {
      document.getElementById("files-onedrive-input").removeAttribute("value");
    }

    if (document.getElementById("files-upload-label").getAttribute("value") != null) {
      document.getElementById("files-upload-label").removeAttribute("value");
      document.getElementById("files-upload-label").innerHTML = "";
    }

    let target = fileInput.target as HTMLInputElement;
    let file: File = (target.files as FileList)[0];
    this.copiesName = file.name;
    document.getElementById("files-upload-label").setAttribute("value", this.copiesName);
    document.getElementById("files-upload-label").innerHTML = this.copiesName;
    this.copies = file;
  }

  CsvFileEvent(fileInput: Event) {
    if (this.getDropboxAttibute("csv-dropbox-input") != null) {
      document.getElementById("csv-dropbox-input").removeAttribute("value");
    }

    if (this.getOneDriveAttibute("csv-onedrive-input") != null) {
      document.getElementById("csv-onedrive-input").removeAttribute("value");
    }

    if (document.getElementById("csv-upload-label").getAttribute("value") != null) {
      document.getElementById("csv-upload-label").removeAttribute("value");
      document.getElementById("csv-upload-label").innerHTML = "";
    }

    let target = fileInput.target as HTMLInputElement;
    let file: File = (target.files as FileList)[0];
    this.csvName = file.name;
    document.getElementById("csv-upload-label").setAttribute("value", this.csvName);
    document.getElementById("csv-upload-label").innerHTML = this.csvName;
    this.csv = file;
  }

  checkDisabled(): boolean {
    let dropboxInput = this.getDropboxAttibute("files-dropbox-input");
    let onedriveInput = this.getOneDriveAttibute("files-onedrive-input");

    let dropboxInputCSV = this.getDropboxAttibute("csv-dropbox-input");
    let onedriveInputCSV = this.getOneDriveAttibute("csv-onedrive-input");

    if (this.copiesName === "" && dropboxInput === null && onedriveInput === null) {
      return true;
    } else if (this.csvName === "" && dropboxInputCSV === null && onedriveInputCSV === null) {
      return true;
    } else if (this.taskName === "") {
      return true;
    } else {
      return false;
    }
  }

  async convertDownloadableFile() {
    if (this.getDropboxAttibute("files-dropbox-input") != null) {
      let blob = await fetch(document.getElementById("files-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    } else if (this.getOneDriveAttibute("files-onedrive-input") != null) {
      let blob = await fetch(document.getElementById("files-onedrive-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    }
  }

  async convertDownloadableCSV() {
    if (this.getDropboxAttibute("csv-dropbox-input") != null) {
      let blob = await fetch(document.getElementById("csv-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.csv = new File([blob], document.getElementById("csv-upload-label").getAttribute("value"));
    } else if (this.getOneDriveAttibute("csv-onedrive-input") != null) {
      let blob = await fetch(document.getElementById("csv-onedrive-input").getAttribute("value")).then(r => r.blob());
      this.csv = new File([blob], document.getElementById("csv-upload-label").getAttribute("value"));
    }
  }

  getDropboxAttibute(id) {
    if(!this.showDropbox) {
      return null;
    } else {
      return this.getAttibute(id);
    }
  }

  getOneDriveAttibute(id) {
    if(!this.showDropbox) {
      return null;
    } else {
      return this.getAttibute(id);
    }
  }

  getAttibute(id) {
    if(document.getElementById(id).getAttribute("value") != null) {
      return document.getElementById(id).getAttribute("value");
    } else {
      return null;
    }
  }

  getUploadState1() {
    if (this.uploading === true && this.tasksService.getUploadPart1State() === true) {
      return true;
    } else {
      return false;
    }
  }

  getUploadState2() {
    if (this.uploading === true && this.tasksService.getUploadPart2State() === true) {
      return true;
    } else {
      return false;
    }
  }

  cancel() {
    this.copiesName = "";
    this.csvName = "";
    this.router.navigate(['/main-menu']);
  }

  cancelPresentation() {
    this.presentationCopiesName = "";
    this.latexFrontPageName = "";
    this.suffix = "";
  }

  checkDisabledPresentation() {
    if (this.presentationCopiesName !== "" && this.latexFrontPageName !== "" ) {
      return false;
    } else {
      return true;
    }
  }

  createPresentation() {
    if (this.checkDisabledPresentation()) {
      this.notifyService.showError("Assurez-vous de complêter toutes les étapes!", "ERREUR");
    } else {
      this.disabled = true;
      // post request
      const formdata: FormData = new FormData();
      this.userService.addTokens(formdata);
      formdata.append('suffix', this.suffix);
      formdata.append('moodle_zip', this.presentationCopies);
      formdata.append('latex_front_page', this.latexFrontPage);

      let file: Blob;

      this.http.post(`${SERVER_URL}front_page`, formdata, { responseType: 'blob' }).subscribe(
        (data) => {
          // moodle.zip in data
          file = data;
          let downloadURL = window.URL.createObjectURL(data);
          saveAs(downloadURL, this.presentationCopiesName);
          this.disabled = false;
        },
        (error) => {
          this.notifyService.showError(error.message, "ERREUR");
          this.disabled = false;
        });
    }
  }

  async createTask() {
    if (this.checkDisabled()) {
      this.notifyService.showError("Assurez-vous de complêter toutes les étapes!", "ERREUR");
    } else {
      this.uploading = true;
      await this.convertDownloadableFile();
      await this.convertDownloadableCSV();
      let front_template_name = this.templates.find(template => template['template_id'] == this.selectedFrontTemplate)['template_name'];
      let regular_template_name = this.templates.find(template => template['template_id'] == this.selectedRegularTemplate)['template_name'];

      this.tasksService.addTask(this.copies, this.csv, this.selectedFrontTemplate, this.selectedRegularTemplate, this.nPagesPerQuestion, this.nMaxPointsPerQuestion, this.bonusEnabledMap, this.taskName, front_template_name, regular_template_name, this.statisticsForStudents);
    }
  }

  reroute() {
    this.router.navigate(['/main-menu']);
  }
}

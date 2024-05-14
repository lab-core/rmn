import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { UserService } from 'src/app/services/user.service';
import { TasksService } from 'src/app/services/tasks.service';
import { SERVER_URL } from 'src/app/utils';
import { NotificationService } from 'src/app/services/notification.service';
import {FormBuilder, Validators} from '@angular/forms';
import * as saveAs from 'file-saver';


//DropBox API
declare function dropboxFiles(): void;
declare function dropboxCSV(): void;

//OneDrive API
declare function onedrivePicker(): void;
declare function onedrivePickerCSV(): void;


@Component({
  selector: 'app-new-correction',
  templateUrl: './new-correction.component.html',
  styleUrls: ['./new-correction.component.css']
})
export class NewCorrectionComponent implements OnInit {
  copies: File;
  csv: File;

  firstFormGroup = this._formBuilder.group({
    firstCtrl: ['', Validators.required],
  });
  secondFormGroup = this._formBuilder.group({
    secondCtrl: ['', Validators.required],
  });
  thirdFormGroup = this._formBuilder.group({
    thirdCtrl: ['', Validators.required],
  });
  fourthFormGroup = this._formBuilder.group({
    fourthCtrl: ['', Validators.required],
  })
  fifthFormGroup = this._formBuilder.group({
    fourthCtrl: ['', Validators.required],
  })
  isLinear = true;

  copiesName: string = "";
  csvName: string = "";
  templates: Array<Map<string, string>>;
  selectedTemplate: string = ""
  disabled: boolean = false;
  uploading: boolean = false;

  numberPages: number = 1;
  taskName: string = "Tâche";

  suffix: string = "";
  presentationCopies: File;
  latexFrontPage: File;
  latexInputPage: File;

  presentationCopiesName: string = "";
  latexFrontPageName: string = "";

  constructor(
    private router: Router,
    private tasksService: TasksService,
    private http: HttpClient,
    private userService: UserService,
    private notifyService: NotificationService,
    private _formBuilder: FormBuilder
  ) { }

  async ngOnInit(): Promise<void> {
    this.getTemplates();
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
    this.copiesName = file.name;
    this.copies = file;
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

    if (document.getElementById("files-onedrive-input").getAttribute("value") != null) {
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

    if (document.getElementById("files-dropbox-input").getAttribute("value") != null) {
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

    if (document.getElementById("csv-onedrive-input").getAttribute("value") != null) {
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

    if (document.getElementById("csv-dropbox-input").getAttribute("value") != null) {
      document.getElementById("csv-dropbox-input").removeAttribute("value");
      document.getElementById("csv-upload-label").removeAttribute("value");
      document.getElementById("csv-upload-label").innerHTML = "";
    }

    onedrivePickerCSV();
  }


  async getTemplates() {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    this.http.post<any>(`${SERVER_URL}user/template`, formdata).subscribe(
      (data) => {
        this.templates = data['response'];
        if (this.templates.length === 0) {
          this.notifyService.showWarning( "Veuillez créer un template avant de commencer une correction.", "Avertissement");
          this.disabled = true;
        }else{
          this.selectedTemplate = this.templates[0]['template_id'];
        }
      });
  }

  CopiesFileEvent(fileInput: Event) {
    if (document.getElementById("files-dropbox-input").getAttribute("value") != null) {
      document.getElementById("files-dropbox-input").removeAttribute("value");
    }

    if (document.getElementById("files-onedrive-input").getAttribute("value") != null) {
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
    document.getElementById("number-page-container").style.display = (this.copiesName.endsWith('.zip')) ? 'none' : 'block';
  }

  CsvFileEvent(fileInput: Event) {
    if (document.getElementById("csv-dropbox-input").getAttribute("value") != null) {
      document.getElementById("csv-dropbox-input").removeAttribute("value");
    }

    if (document.getElementById("csv-onedrive-input").getAttribute("value") != null) {
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
    let dropboxInput = document.getElementById("files-dropbox-input").getAttribute("value");
    let onedriveInput = document.getElementById("files-onedrive-input").getAttribute("value");

    let dropboxInputCSV = document.getElementById("csv-dropbox-input").getAttribute("value");
    let onedriveInputCSV = document.getElementById("csv-onedrive-input").getAttribute("value");

    if (this.copiesName === "" && dropboxInput === null && onedriveInput === null) {
      return true;
    } else if (this.csvName === "" && dropboxInputCSV === null && onedriveInputCSV === null) {
      return true;
    } else if (this.taskName === "") {
      return true;
    }
    else {
      return false;
    }
  }

  async convertDownloadableFile() {
    if (document.getElementById("files-dropbox-input").getAttribute("value") != null) {
      let blob = await fetch(document.getElementById("files-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    } else if (document.getElementById("files-onedrive-input").getAttribute("value") != null) {
      let blob = await fetch(document.getElementById("files-onedrive-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    }
  }

  async convertDownloadableCSV() {
    if (document.getElementById("csv-dropbox-input").getAttribute("value") != null) {
      let blob = await fetch(document.getElementById("csv-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.csv = new File([blob], document.getElementById("csv-upload-label").getAttribute("value"));
    } else if (document.getElementById("csv-onedrive-input").getAttribute("value") != null) {
      let blob = await fetch(document.getElementById("csv-onedrive-input").getAttribute("value")).then(r => r.blob());
      this.csv = new File([blob], document.getElementById("csv-upload-label").getAttribute("value"));
    }
  }

  getUploadState1() {
    if(this.uploading === true && this.tasksService.getUploadPart1State() === true){
      return true;
    }else{
      return false;
    }
  }

  getUploadState2() {
    if(this.uploading === true && this.tasksService.getUploadPart2State() === true){
      return true;
    }else{
      return false;
    }
  }

  cancel() {
    this.copiesName = "";
    this.csvName = "";
    this.router.navigate(['/main-menu']);
  }

  cancelPresentation() {
    this.copiesName = "";
    this.latexFrontPageName = "";
    this.suffix = "";
  }

  checkDisabledPresentation() {
    if (this.copiesName !== "" && this.latexFrontPageName !== "" ) {
      return false;
    } else {
      return true;
    }
  }

  createPresentation() {
    if (this.checkDisabledPresentation()) {
      this.notifyService.showError("Assurez-vous de complêter toutes les étapes!", "ERREUR")
    } else {
      this.disabled = true;
      console.log("suffix:", this.suffix)
      // post request
      const formdata: FormData = new FormData();
      formdata.append('user_id', this.userService.currentUsername);
      formdata.append('token', this.userService.token);
      formdata.append('suffix', this.suffix);
      formdata.append('moodle_zip', this.copies);
      formdata.append('latex_front_page', this.latexFrontPage);

      let file: Blob;

      this.http.post(`${SERVER_URL}front_page`, formdata, { responseType: 'blob' }).subscribe(
        (data) => {
          // moodle.zip in data
          file = data;
          let downloadURL = window.URL.createObjectURL(data);
          saveAs(downloadURL, this.copiesName);
          this.disabled = false;
        },
        (error) => {
          this.notifyService.showError(error.message, "ERREUR")
          this.disabled = false;
        });

    }
  }

  async createTask() {
    if (this.checkDisabled()) {
      this.notifyService.showError("Assurez-vous de complêter toutes les étapes!", "ERREUR")
    } else {
      this.uploading = true;
      await this.convertDownloadableFile();
      await this.convertDownloadableCSV();
      let template_name = this.templates.find(template => template['template_id'] == this.selectedTemplate)['template_name'];

      this.tasksService.addTask(this.copies, this.csv, this.selectedTemplate, this.numberPages, this.taskName, template_name);
    }
  }

  reroute() {
    this.router.navigate(['/main-menu']);
  }

}

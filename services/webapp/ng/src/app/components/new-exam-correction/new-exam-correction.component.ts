import { Component, HostListener, OnInit, OnChanges, SimpleChanges, OnDestroy, Renderer2, ChangeDetectionStrategy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { UserService } from 'src/app/services/user.service';
import { TasksService } from 'src/app/services/tasks.service';
import { SERVER_URL } from 'src/app/utils';
import { NotificationService } from 'src/app/services/notification.service';
import { FormBuilder, Validators } from '@angular/forms';
import { MatSelectChange } from '@angular/material/select';
import { first } from 'rxjs/operators';

import { saveAs } from 'file-saver';
import { csvLines, detectSeparator, splitCsvLine } from 'src/app/csv';

//DropBox API
declare function dropboxFiles(): void;
declare function dropboxCSV(): void;

//OneDrive API
declare function onedrivePicker(): void;
declare function onedrivePickerCSV(): void;

@Component({
    selector: 'app-new-exam-correction',
    templateUrl: './new-exam-correction.component.html',
    styleUrls: ['./new-exam-correction.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class NewExamCorrectionComponent implements OnInit, OnChanges, OnDestroy {
  copies: File;
  csv: File;
  firstFormGroup: any;
  secondFormGroup: any;
  thirdFormGroup: any;
  fourthFormGroup: any;
  isLinear: boolean = true;
  nQuestionsReadOnly: boolean = true;
  correct: boolean = true;
  validateMatricule: boolean = false;

  copiesName: string = "";
  csvName: string = "";
  templates: Array<Map<string, string>>;
  selectedFrontTemplate: string = "";
  selectedFrontTemplateName: string = "";
  selectedRegularTemplate: string = "";
  disabled: boolean = false;
  uploading: boolean = false;
  statisticsForStudents: boolean = true;
  doNotSaveTask: boolean = false;

  nQuestions: number;
  totalPages: number = 0;
  totalPoints: number = 0;
  totalBonus: number = 0;
  nPagesPerQuestion = new Map<string, number>();
  nMaxPointsPerQuestion = new Map<string, number>();
  bonusEnabledMap = new Map<string, boolean>();
  // A question of the template that the exam does not use: 0 page, 0 point,
  // skipped everywhere except on the cover page where its box is left blank.
  // UI-only state; the server derives it from the 0 pages.
  ignoredQuestions = new Map<string, boolean>();
  questionKeys: string[] = [];
  taskName: string = "Tâche";

  /** The task this one is being created from, when the route names one. */
  sourceTask: { id: string, name: string } = null;
  /** Whether that task's copies, and its notes, are still the ones to use.
   *  Uploading a file of its own turns the matching one off. */
  reuseCopies: boolean = false;
  reuseCsv: boolean = false;
  /** The dashboard link's token when the source task is someone else's: the
   *  server lets the user copy it, templates included, only with it. */
  sourceShareToken: string = null;
  /** That task's templates, offered among the user's own: the server copies
   *  them into the user's templates unless another one is picked. */
  private sourceTemplates: Array<any> = [];

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
    private route: ActivatedRoute,
    private tasksService: TasksService,
    private http: HttpClient,
    private renderer: Renderer2,
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
    if (this.showDropbox) await this.loadDropbox();
    if (this.showOneDrive) await this.loadOnedrive();
    this.getTemplates();
    const from = this.route.snapshot.paramMap.get('from');
    if (from) {
      // the draft of an unfinished task would fight the prefill: the user
      // asked for this task, not for the one they left half-written
      await this.loadSourceTask(from, this.route.snapshot.queryParamMap?.get('token'));
    } else {
      await this.loadTask();
    }
    this.updateQuestionsCount();
    this.updateTotals();
  }

  async loadDropbox(): Promise<void> {
    return new Promise((resolve, reject) => {
      const script = this.renderer.createElement('script');
      script.src = 'https://www.dropbox.com/static/api/2/dropins.js';
      script.type = 'text/javascript';
      script.async = true;
      script.id="dropboxjs";
      script['data-app-key']="auq6uoeobdj8du4";
      script.onload = () => resolve();
      script.onerror = () => reject();
      this.renderer.appendChild(document.body, script);
    });
  }

  async loadOnedrive(): Promise<void> {
    return new Promise((resolve, reject) => {
      const script = this.renderer.createElement('script');
      script.src = 'https://js.live.net/v7.2/OneDrive.js';
      script.type = 'text/javascript';
      script.async = true;
      script.id="onedrivejs";
      script.onload = () => resolve();
      script.onerror = () => reject();
      this.renderer.appendChild(document.body, script);
    });
  }

  async ngOnChanges(changes: SimpleChanges): Promise<void> {
    this.saveTask();
  }

  async ngOnDestroy(): Promise<void> {
    this.saveTask();
  }

  @HostListener('window:beforeunload', ['$event'])
  beforeUnloadHandler(event) {
     this.saveTask();
   }

  selectText(event): void {
    event.target.select();
  }

  onQuestionIndexChange(event: MatSelectChange): void {
    if (event.value) {
      const template = this.templates.find(t => t['template_id'] === event.value);
      this.nQuestions = template["n_questions"];
      this.selectedFrontTemplateName = template["template_name"];
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
    this.bonusEnabledMap.clear();
    this.ignoredQuestions.clear();
    this.questionKeys = [];
    for (let i = 1; i <= this.nQuestions; i++) {
      const key = `Q${i}`;
      this.nPagesPerQuestion.set(key, this.nPagesPerQuestion[key] || 0);
      this.nMaxPointsPerQuestion.set(key, this.nMaxPointsPerQuestion[key] || 0);
      this.bonusEnabledMap.set(key, this.bonusEnabledMap[key] || false);
      this.ignoredQuestions.set(key, this.ignoredQuestions[key] || false);
      this.questionKeys.push(key);
    }
  }

  isIgnored(key: string): boolean {
    return this.ignoredQuestions.get(key) || false;
  }

  toggleIgnored(key: string) {
    const ignored = !this.isIgnored(key);
    this.ignoredQuestions.set(key, ignored);
    this.ignoredQuestions[key] = ignored;
    if (ignored) {
      // the inputs are bound to the property form (nPagesPerQuestion[key]) while
      // the task is sent from the Map entries: keep both in sync
      this.nPagesPerQuestion.set(key, 0);
      this.nPagesPerQuestion[key] = 0;
      this.nMaxPointsPerQuestion.set(key, 0);
      this.nMaxPointsPerQuestion[key] = 0;
      this.bonusEnabledMap.set(key, false);
      this.bonusEnabledMap[key] = false;
    } else {
      this.nPagesPerQuestion.delete(key);
      delete this.nPagesPerQuestion[key];
      this.nMaxPointsPerQuestion.delete(key);
      delete this.nMaxPointsPerQuestion[key];
    }
    this.updateTotals();
    this.saveTask();
  }

  /** Questions that are corrected but miss their number of pages or points. */
  incompleteQuestions(): string[] {
    return this.questionKeys.filter(key => !this.isIgnored(key) &&
      (!(this.nPagesPerQuestion.get(key) > 0) || !(this.nMaxPointsPerQuestion.get(key) > 0)));
  }

  updatePageCount(key: string, event: Event) {
    const inputElement = event.target as HTMLInputElement;
    if (inputElement.value === '') {
      this.nPagesPerQuestion.delete(key);
      this.saveTask();
      return;
    }
    const pageCount = Number(inputElement.value);
    if (!Number.isInteger(pageCount) || pageCount <= 0) {
      this.notifyService.showError("Veuillez entrer une valeur entière positive.", "ERREUR");
      inputElement.value = '';
    } else {
      this.nPagesPerQuestion.set(key, pageCount);
      this.updateTotals();
      this.saveTask();
    }
  }

  updateMaxPoints(key: string, event: Event) {
    const inputElement = event.target as HTMLInputElement;
    if (inputElement.value === '') {
      this.nMaxPointsPerQuestion.delete(key);
      this.saveTask();
      return;
    }
    const maxPoints = Number(inputElement.value);
    if (!Number.isFinite(maxPoints) || maxPoints <= 0.001) {
      this.notifyService.showError("Veuillez entrer une valeur positive.", "ERREUR");
      inputElement.value = '';
    } else {
      this.nMaxPointsPerQuestion.set(key, maxPoints);
      this.updateTotals();
      this.saveTask();
    }
  }

  toggleBonus(key: string) {
    const currentValue = this.bonusEnabledMap.get(key) || false;
    this.bonusEnabledMap.set(key, !currentValue);
    this.updateTotals();
    this.saveTask();
  }

  updateSuffix(event: KeyboardEvent) {
    const regex = new RegExp("^[a-zA-ZÀ-ÿ0-9\-\_\ ]+$");
    const key = String.fromCharCode(!event.charCode ? event.which : event.charCode);
    if (!regex.test(key)) {
      event.preventDefault();
    }
    this.saveTask();
  }

  presentationCopiesFileEvent(fileInput: Event) {
    const target = fileInput.target as HTMLInputElement;
    const file: File = (target.files as FileList)[0];
    this.presentationCopiesName = file.name;
    this.presentationCopies = file;
  }

  latexFrontPageEvent(fileInput: Event) {
    const target = fileInput.target as HTMLInputElement;
    const file: File = (target.files as FileList)[0];
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
    this.http.post<any>(`${SERVER_URL}templates/user`, formdata).pipe(first()).subscribe(
      (data) => {
        this.templates = data['response'].filter((temp) => { return !temp.locked; });
        this.offerSourceTemplates();
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

    const target = fileInput.target as HTMLInputElement;
    const file: File = (target.files as FileList)[0];
    this.reuseCopies = false;  // the upload replaces the source task's copies
    this.copiesName = file.name;
    // textContent: the file name is user data, not markup
    document.getElementById("files-upload-label").setAttribute("value", this.copiesName);
    document.getElementById("files-upload-label").textContent = this.copiesName;
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

    const target = fileInput.target as HTMLInputElement;
    const file: File = (target.files as FileList)[0];

    // Verify csv file
    const reader = new FileReader();
    reader.onload = () => {
      // Every line must have the header's number of fields; quoted separators
      // and a byte-order mark are handled by the csv helpers. The server checks
      // the Moodle columns themselves when the task is created.
      const lines = csvLines(String(reader.result));
      let validCSV = lines.length > 0;
      if (validCSV) {
        const sep = detectSeparator(lines[0]);
        const nCols = splitCsvLine(lines[0], sep).length;
        validCSV = nCols >= 2;
        const badLine = lines.find((line) => splitCsvLine(line, sep).length !== nCols);
        if (badLine !== undefined) {
          this.notifyService.showError("Cette ligne est invalide: " + badLine, "ERREUR");
          validCSV = false;
        }
      }

      if (validCSV) {
        this.csv = file;
        this.reuseCsv = false;  // the upload replaces the source task's notes
        this.setCSVName(file.name);
        this.saveTask();
      } else {
        this.csvName = "";
        this.notifyService.showError("Veuillez fournir un csv valide", "ERREUR");
      }
    };
    reader.readAsText(file);
  }

  setCSVName(csvName: string) {
    this.csvName = csvName;
    document.getElementById("csv-upload-label").setAttribute("value", this.csvName);
    document.getElementById("csv-upload-label").textContent = this.csvName;
  }

  checkDisabled(): boolean {
    const dropboxInputCSV = this.getDropboxAttibute("csv-dropbox-input");
    const onedriveInputCSV = this.getOneDriveAttibute("csv-onedrive-input");

    // The zip with the copies to correct is optional: when missing, an empty
    // zip is sent instead (see createEmptyZipFile).
    if (this.csvName === "" && dropboxInputCSV === null && onedriveInputCSV === null) {
      return true;
    } else if (this.taskName === "") {
      return true;
    } else {
      return false;
    }
  }

  async convertDownloadableFile() {
    if (this.getDropboxAttibute("files-dropbox-input") != null) {
      const blob = await fetch(document.getElementById("files-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    } else if (this.getOneDriveAttibute("files-onedrive-input") != null) {
      const blob = await fetch(document.getElementById("files-onedrive-input").getAttribute("value")).then(r => r.blob());
      this.copies = new File([blob], document.getElementById("files-upload-label").getAttribute("value"));
    }
  }

  async convertDownloadableCSV() {
    if (this.getDropboxAttibute("csv-dropbox-input") != null) {
      const blob = await fetch(document.getElementById("csv-dropbox-input").getAttribute("value")).then(r => r.blob());
      this.csv = new File([blob], document.getElementById("csv-upload-label").getAttribute("value"));
    } else if (this.getOneDriveAttibute("csv-onedrive-input") != null) {
      const blob = await fetch(document.getElementById("csv-onedrive-input").getAttribute("value")).then(r => r.blob());
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
    if(!this.showOneDrive) {
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
    this.saveTask();
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
      this.http.post(`${SERVER_URL}frontpage`, formdata, { responseType: 'blob' }).pipe(first()).subscribe(
        (data) => {
          // moodle.zip in data
          saveAs(data, this.presentationCopiesName);
          this.disabled = false;

        },
        (error) => {
          this.notifyService.showError(error.message, "ERREUR");
          this.disabled = false;

        });
    }
  }

  /**
   * Builds a valid empty zip file (a bare end-of-central-directory record),
   * used when the user creates a task without uploading any copies.
   */
  createEmptyZipFile(): File {
    const emptyZipBytes = new Uint8Array([
      0x50, 0x4b, 0x05, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
      0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    ]);
    return new File([emptyZipBytes], `${this.taskName || 'copies'}.zip`, { type: 'application/zip' });
  }

  async createTask() {
    if (this.checkDisabled()) {
      this.notifyService.showError("Assurez-vous de complêter toutes les étapes!", "ERREUR");
    } else if (this.correct && this.incompleteQuestions().length > 0) {
      this.notifyService.showError(
        `Veuillez indiquer le nombre de pages et de points de ${this.incompleteQuestions().join(", ")}, ou ignorer la question.`,
        "ERREUR");
    } else {
      this.uploading = true;
      try {
        await this.convertDownloadableFile();
        await this.convertDownloadableCSV();
        if (!this.copies && !this.reuseCopies) {
          // No copies uploaded: send an empty zip so the task is created
          // without any exam to correct.
          this.copies = this.createEmptyZipFile();
        }
        const front_template_name = this.templates.find(template => template['template_id'] == this.selectedFrontTemplate)['template_name'];
        const regular_template_name = this.templates.find(template => template['template_id'] == this.selectedRegularTemplate)['template_name'];
        if (!this.correct) {
          this.nPagesPerQuestion.clear();
          this.nMaxPointsPerQuestion.clear();
          this.bonusEnabledMap.clear();
          this.statisticsForStudents = false;
        }
        // what is reused is not sent: the server copies it from the source
        await this.tasksService.addTask(this.reuseCopies ? null : this.copies,
                                        this.reuseCsv ? null : this.csv,
                                        this.selectedFrontTemplate, this.selectedRegularTemplate,
                                        this.nPagesPerQuestion, this.nMaxPointsPerQuestion, this.bonusEnabledMap, this.taskName,
                                        front_template_name, regular_template_name, this.statisticsForStudents,
                                        this.validateMatricule, this.sourceTask ? this.sourceTask.id : null,
                                        this.sourceShareToken);
        this.removeTask();
        this.doNotSaveTask = true;
        this.reroute();
      } catch (error) {
        // clear the spinner and inform the user instead of hanging behind the overlay
        console.error(error);
        this.uploading = false;
        this.notifyService.showError("Échec de la création de la tâche.", "ERREUR");
      }
    }
  }

  /** The draft of the task being defined, kept in localStorage between visits.
   *
   *  The per-question Maps are written as plain objects: JSON.stringify of a
   *  Map is "{}", so a draft used to come back with every question at zero.
   *  The class list is not stored: it was base64-encoded (names and
   *  matricules of every student) on every keystroke, against a ~5 MB quota
   *  shared with the annotation drafts; the user picks the csv again. */
  saveTask() {
    if (this.doNotSaveTask) return;

    const task = {
      name: this.taskName,
      frontTemplate: this.selectedFrontTemplate,
      regularTemplate: this.selectedRegularTemplate,
      nQuestions: this.nQuestions,
      nPages: Object.fromEntries(this.nPagesPerQuestion),
      maxPoints: Object.fromEntries(this.nMaxPointsPerQuestion),
      bonus: Object.fromEntries(this.bonusEnabledMap),
      ignored: Object.fromEntries(this.ignoredQuestions),
      stats: this.statisticsForStudents,
    };
    try {
      localStorage.setItem('newTask', JSON.stringify(task));
    } catch (error) {
      console.warn('draft task not saved', error);  // quota exceeded: the form still works
    }
  }

  /** Fill a per-question map from ``[key, value]`` pairs.
   *
   *  Both the Map and its property form: the inputs are bound to
   *  nPagesPerQuestion[key] while the logic reads the Map.
   */
  private restoreQuestions(map: Map<string, any>, entries: Array<[string, any]>): void {
    for (const [key, value] of entries || []) {
      map.set(key, value);
      map[key] = value;
    }
  }

  async loadTask() {
    const taskJson = localStorage.getItem('newTask');

    if (taskJson != undefined) {
      const task = JSON.parse(taskJson);
      this.taskName = task.name;
      this.selectedFrontTemplate = task.frontTemplate;
      this.selectedRegularTemplate = task.regularTemplate;
      this.nQuestions = task.nQuestions;
      this.restoreQuestions(this.nPagesPerQuestion, Object.entries(task.nPages || {}));
      this.restoreQuestions(this.nMaxPointsPerQuestion, Object.entries(task.maxPoints || {}));
      this.restoreQuestions(this.bonusEnabledMap, Object.entries(task.bonus || {}));
      this.restoreQuestions(this.ignoredQuestions, Object.entries(task.ignored || {}));
      this.statisticsForStudents = task.stats;
    }
  }

  /** Fill the form with an existing task, and reuse its files to begin with.
   *
   *  Everything is prefilled and everything stays editable: the name gets a
   *  suffix so the two are told apart in the history, and the copies and the
   *  notes are the ones already on the server until the user replaces them.
   */
  async loadSourceTask(jobId: string, shareToken: string = null): Promise<void> {
    let job: any;
    try {
      job = await this.tasksService.getTaskById(jobId, shareToken);
    } catch (error) {
      console.error(error);
    }
    if (!job) {
      this.notifyService.showError("La tâche d'origine est introuvable.", "ERREUR");
      return;
    }
    this.sourceTask = { id: jobId, name: job.job_name };
    this.taskName = `${job.job_name} (copie)`;
    this.selectedFrontTemplate = job.front_template_id;
    this.selectedFrontTemplateName = job.front_template_name;
    this.selectedRegularTemplate = job.regular_template_id;
    this.restoreQuestions(this.nPagesPerQuestion, job.n_pages_per_question);
    this.restoreQuestions(this.nMaxPointsPerQuestion, job.n_max_points_per_question);
    this.restoreQuestions(this.bonusEnabledMap, job.bonus_enabled_map);
    this.nQuestions = (job.n_pages_per_question || []).length;
    // the wizard's own notion: a question the template has a box for and the
    // exam does not use, which the server stores as 0 page and 0 point
    for (const [key, pages] of job.n_pages_per_question || []) {
      if (!pages && !this.nMaxPointsPerQuestion.get(key)) {
        this.ignoredQuestions.set(key, true);
        this.ignoredQuestions[key] = true;
      }
    }
    this.statisticsForStudents = !!job.statistics_for_students;
    this.validateMatricule = !!job.validate_matricule;
    this.reuseCopies = true;
    this.reuseCsv = true;
    // checkDisabled() asks for a csv, and there is one: the source's
    this.copiesName = `Copies de « ${job.job_name} »`;
    this.csvName = `Notes de « ${job.job_name} »`;
    if (shareToken) {
      // shared by someone else: their templates are not in the user's list
      this.sourceShareToken = shareToken;
      const offered = [[job.front_template_id, job.front_template_name],
                       [job.regular_template_id, job.regular_template_name]];
      this.sourceTemplates = offered
        .filter(([id], i) => id && offered.findIndex(([other]) => other === id) === i)
        .map(([id, name]) => ({ template_id: id, template_name: name, n_questions: this.nQuestions }));
      this.offerSourceTemplates();
    }
  }

  /** Add the templates of a task shared by someone else to the user's own,
   *  whichever of the two lists arrives last. */
  private offerSourceTemplates(): void {
    if (!this.templates || this.sourceTemplates.length === 0) {
      return;
    }
    for (const template of this.sourceTemplates) {
      if (!this.templates.some(t => t['template_id'] === template.template_id)) {
        this.templates.push(template);
      }
    }
    // a user without any template of their own can still copy this task
    this.disabled = false;
  }

  /** Stop reusing the copies of the source task (the copies are optional). */
  dropReusedCopies(): void {
    this.reuseCopies = false;
    this.copies = undefined;
    this.copiesName = "";
  }

  /** Stop reusing the notes of the source task; another csv must be given. */
  dropReusedCsv(): void {
    this.reuseCsv = false;
    this.csv = undefined;
    this.csvName = "";
  }

  removeTask() {
    localStorage.removeItem('newTask');
  }

  reroute() {
    this.router.navigate(['/main-menu']);
  }
}

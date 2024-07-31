import { Component, HostListener, OnInit, OnDestroy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { HttpClient } from '@angular/common/http';
import { ValidationWarningDialogComponent } from './validation-warning-dialog/validation-warning-dialog.component';
import { Router, ActivatedRoute } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService } from 'src/app/services/documents.service';
import { SERVER_URL } from 'src/app/utils';
import { NgxExtendedPdfViewerService,  pdfDefaultOptions } from 'ngx-extended-pdf-viewer';
import { MatSelectChange } from '@angular/material/select';
import * as saveAs from 'file-saver';
import * as JSZip from 'jszip';
import { PDFDocument } from 'pdf-lib';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-task-verification',
  templateUrl: './task-verification.component.html',
  styleUrls: ['./task-verification.component.css']
})
export class TaskVerificationComponent implements OnInit, OnDestroy {

  constructor(private tasksService: TasksService,
    private validationService: ValidationService,
    private socketService: SocketService,
    private notificationService: NotificationService,
    private http: HttpClient,
    public dialog: MatDialog,
    private router: Router,
    private route: ActivatedRoute,
    private userService: UserService,
    private docService: DocumentsService,
    private ngxService: NgxExtendedPdfViewerService) {
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
    }

  isSidebarHidden: boolean = false;
  isIndexProvided: boolean = false;
  pictureLoading: boolean = true;
  pdfLoading: boolean = true;
  pdfModified: boolean = false;
  disabledValidationcontainer = true;
  disabledValidationButton = true;
  disabledDropDown = false;
  validating: boolean = false;
  disablePrevious: boolean = false;
  disableNext: boolean = false;
  hasDownloadedZip: boolean = false;
  hasUploadedZip: boolean = false;

  job: Map<string, any>;
  pdfSrc: string;
  pdfSize: number = 0;
  zoomSetting: any;
  pdfViewerInitialized: boolean = false;

  nMaxPointsPerQuestion = new Map<string, number>();
  bonusEnabledMap = new Map<string, boolean>();
  bonusNoticationsShown = new Map<string, boolean>();
  initialCopyIndex: number = -1;
  currentCopy: number = -1;
  currentCopyName: string;
  currentQuestionIndex: string;
  index: string = "Tout sélectionner";
  currentVersion: number = 0;
  lastVersion: number = 0;
  currentGrade: number | null;
  currentTotal: number;
  currentGrades: Map<string, number>;
  currentStatus: string;

  colorChosen: string;

  examsList: Array<any>;
  subExamsList: Array<any>;
  group: string;
  groupsList: Array<string>;
  questionIndexes: Array<string> = [];
  formattedIndexes: Array<string> = [];
  // default max copies per pdf value
  maxCopiesPerPdf: number = 40;
  currentGradesMap: Map<number, number> = new Map();

  async ngOnInit(): Promise<any> {
    // fetch query entries
    let token = this.route.snapshot.queryParams['token'];
    if (token) {
      this.userService.setShareToken(token, this.route.snapshot.queryParams['question_index']);
    }

    let jobId = this.route.snapshot.queryParams['job_id'];
    if (jobId) {
      this.tasksService.setvalidatingTaskId(jobId);
    }

    this.group = this.route.snapshot.queryParams['group'];
    if (this.group == null) {
      this.group = "";
    }
    this.groupsList = [this.group];

    try {
      this.job = await this.tasksService.getTask();
    } catch (err) {
      console.error(err);
    }
    if (!this.job || !this.job["job_id"]) {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche non disponible');
      this.router.navigate(['/tasks-history']);
    }

    // set job parameters
    this.getMaxPointsPerQuestion();
    this.getBonusEnabledMap();

    // fetch job and documents
    await this.getDocuments();

    this.socketService.join(this.job["job_id"]);
    this.socketService.getSocket().on('document_ready', async (params: any) => {
      await this.getDocuments();
      if (this.disabledValidationcontainer) {
        this.nextCopy();
      }
    });

    if (this.userService.token) {
      this.socketService.join(this.userService.currentUsername);
      this.socketService.getSocket().on('job_status', async (params: any) => {
        const resp = JSON.parse(params);
        const jobId = resp.job_id;
        if (this.job["job_id"] === jobId) {
          this.job["job_status"] = resp.status;
          this.checkValidationButton();
        }
      });
    }
    this.formattedIndexes = this.generateFormattedIndexes();
    this.initializeQuestionIndexes();
    this.checkValidationButton();
  }

  async ngOnDestroy(): Promise<any> {
    this.socketService.getSocket().off('document_ready');
    this.socketService.getSocket().off('job_status');
    this.socketService.disconnectSocket();
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    this.validateCurrentCopy();
  }

  initializePdfViewer(): void {
    if (!this.pdfViewerInitialized &&
        this.ngxService?.ngxExtendedPdfViewerInitialized) {
      this.ngxService.editorInkColor = '#FF0000';
      this.ngxService.editorInkThickness = 2;
      this.ngxService.editorFontColor = '#FF0000';
      this.ngxService.editorFontSize = 14;
      this.pdfViewerInitialized = true;
    }
  }

  undoChange(e: any){
    const undoEvent = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      charCode: 0,
      keyCode: 90,
      code: "KeyZ",
      composed: true,
      key: 'z',
      shiftKey: false,
      altKey: false,
      ctrlKey: true,
      metaKey: false,
      repeat: false,
      location: KeyboardEvent.DOM_KEY_LOCATION_STANDARD,
    });

    document.body.dispatchEvent(undoEvent);
  }

  public redo(): void{
     document.execCommand('redo');
  }

  toggleSidebar() {
    this.isSidebarHidden = !this.isSidebarHidden;
  }

  generateFormattedIndexes(): Array<string> {
    const formattedIndexes: Array<string> = [];
    const maxIndex = this.examsList.length;
    const questionString = `Q1`;
    let subExamsListSize = this.examsList.filter(exam => exam.question === questionString).length;
    if (subExamsListSize === 0) {
      subExamsListSize = maxIndex;
    }

    for (let i = 1; i <= Math.ceil(maxIndex / subExamsListSize); i++) {
        for (let j = 1; j <= subExamsListSize; j++) {
            const index = `${j}-${i}`;
            if ((i - 1) * subExamsListSize + j <= maxIndex) {
                formattedIndexes.push(index);
            }
        }
    }
    return formattedIndexes;
  }

  loadScore(): void {
    if (this.currentExam()["grade"]) {
      this.currentGrade = this.currentExam()["grade"];
      this.currentGradesMap.set(this.currentCopy, this.currentGrade);
    } else {
      this.currentGrade = this.currentGradesMap.get(this.currentCopy) || null;
    }
  }

  async saveCurrentGrade(): Promise<void> {
    this.currentGradesMap.set(this.currentCopy, this.currentGrade);
  }

  initializeQuestionIndexes(): void {
    this.questionIndexes = ["Tout sélectionner", ...Array.from({ length: this.nMaxPointsPerQuestion.size }, (_, i) => (i + 1).toString())];
    // if question index is provided in query params
    const questionIndex = this.route.snapshot.queryParams['question_index'];
    if (questionIndex) {
      this.index = questionIndex;
      this.onQuestionIndexChange({ value: questionIndex } as MatSelectChange);
      if (!this.userService.loggued()) {
        this.disabledDropDown = true;
        this.isIndexProvided = true;
      }
    } else {
      this.route.params.subscribe(params => {
        const index = params['index'];
        if (index) {
          this.index = index;
          this.onQuestionIndexChange({ value: index } as MatSelectChange);
        } else if (this.checkForAvailableCopies()) {
          this.nextCopy();
        }
      });
    }
  }

  onQuestionIndexChange(event: MatSelectChange): void {
    if (event.value === "Tout sélectionner") {
        this.subExamsList = this.examsList;
        this.formattedIndexes = this.generateFormattedIndexes();
    } else {
        this.filterExamsByQuestion(event.value);
    }
    if (this.subExamsList.length > 0) {
        const firstExam = this.subExamsList[0];
        this.changeCurrentCopy(firstExam["document_index"], firstExam["status"]);
    }
  }

  filterExamsByQuestion(questionIndex: number): void {
    const questionString = `Q${questionIndex}`;
    this.subExamsList = this.examsList.filter(exam => exam.question === questionString);

    this.formattedIndexes = this.subExamsList.map((_, i) => {
      const subIndex = (i % this.subExamsList.length) + 1;
      return `${subIndex}-${questionIndex}`;
    });
  }

  setQuestionId(question: string): string {
    return question.replace(/\s/g, '');
  }

  selectText(event): void {
    // const input = document.getElementById('text-box');
    // input.focus();
    event.target.select();
  }

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId(), true);
    this.examsList = this.docService.documentsList;
    // this.groupsList = this.docService.groupsList;
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0 && this.initialCopyIndex < 0) {
      this.initialCopyIndex = this.examsList[0].document_index;
      this.currentCopy = this.initialCopyIndex - 1;
    }
  }

 getMaxPointsPerQuestion() {
    this.nMaxPointsPerQuestion = new Map<string, number>();
    this.job["n_max_points_per_question"].forEach(e => {
      this.nMaxPointsPerQuestion.set(e[0], e[1]);
    });
  }

 getBonusEnabledMap() {
    this.bonusEnabledMap = new Map<string, boolean>();
    this.job["bonus_enabled_map"].forEach(e => {
      this.bonusEnabledMap.set(e[0], e[1]);
    });
  }

  getSubExamsList(): void {
    console.log("group", this.group)
    if (this.group) {
      let subExamsList = [];
      this.examsList.forEach((exam: any) => {
        if (exam['group'] == this.group) {
          subExamsList.push(exam);
        }
      })
      this.subExamsList = subExamsList;
      console.log("sub exam list size for group", this.group, subExamsList.length, "/", this.examsList.length)
    } else {
      console.log("sub exam list is the full list of size", this.examsList.length)
      this.subExamsList = this.examsList;
    }
  }

  loadSubExamsList(): void {
    this.getSubExamsList();
    console.log("Group:", this.group, this.subExamsList.length, "exams")
    // if any copy available
    if (this.checkForAvailableCopies()) {
      this.currentCopy = this.initialCopyIndex - 1;
      this.nextCopy();
    } else {
      this.disabledValidationcontainer = true;
    }
  }

 addScoreToQuestion(): boolean {
    if (this.currentGrade !== null) {
      if (this.currentGrade >= 0) {
        if (this.currentGrade > this.nMaxPointsPerQuestion.get(this.currentQuestionIndex)) {
          const excessPoints = this.currentGrade - this.nMaxPointsPerQuestion.get(this.currentQuestionIndex);
          this.notificationService.showWarning(`Vous avez rajouté ${excessPoints} point(s) bonus`, 'Attention!');
        }
        this.currentGradesMap.set(this.currentCopy, this.currentGrade);
        this.currentGrade = null;
      } else {
        this.notificationService.showWarning('Veuillez saisir une note valide.', 'Note invalide');
        throw new Error('Note invalide');
      }
    } else {
      this.notificationService.showWarning('Veuillez saisir une note.', 'Note invalide');
      return false;
    }
    return true;
  }

  async loadPdf(version: number = undefined): Promise<void> {
    if (this.currentExam()["status"] !== "NOT_READY") {
      this.setPdfLoading(true);
      const pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, version);
      if (pdfSource.url) {
        this.pdfSrc = pdfSource.url;
        this.lastVersion = pdfSource.lastVersion;
        // set to last version if undefined or greater than last version
        if (version === undefined || version >= this.lastVersion) {
          this.currentVersion = this.lastVersion;
        } else {
          this.currentVersion = version;
        }
        this.pdfModified = false;
        // initialize pdf viewer options
        if (!this.pdfViewerInitialized)
         setTimeout(() => { this.initializePdfViewer(); }, 1000);
        // console.log("Current Exam: ", this.examsList[this.currentIndex()])
      }
      this.setPdfLoading(false);
    }
  }

  setPdfLoading(pdfLoading: boolean) {
    this.pdfLoading = pdfLoading;
    this.disablePrevious = pdfLoading || (this.currentVersion == 0);
    this.disableNext = pdfLoading || (this.currentVersion >= this.lastVersion);
  }

  async pdfLoaded(e) {
    const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
    if (editedPdfData) this.pdfSize = editedPdfData.size;
  }

  async annotationEdited(e) {
    this.pdfModified = true;
  }

  async changeCurrentCopy(copyIndex, status): Promise<void> {
    if (status !== "NOT_READY") {
      if (await this.saveCurrentCopy()) {
        let exam = this.examsList[copyIndex-this.initialCopyIndex];
        console.log("Change current copy to", copyIndex)
        this.currentQuestionIndex = exam["question"];
        this.currentCopyName = exam["basename"];
        this.currentCopy = copyIndex;
        console.log("Current copy", this.currentCopy);
        this.disabledValidationcontainer = false;
        await this.loadCopy();
        this.setChosenColor(status);
        this.loadScore();
        this.verifyIfQuestionIsBonus();
      } else {
          console.error('Erreur lors de l\'obtention du document PDF modifié.');
          this.notificationService.showError('Échec de la sauvegarde du document PDF modifié.', 'Erreur de validation');
      }
    }
  }

  async changeCurrentExam(examIndex): Promise<void> {
    await this.changeCurrentCopy(this.initialCopyIndex + examIndex, this.examsList[examIndex].status);
  }

  async setNewVersion(event){
    await this.loadPdf(event.target.value);
  }

  async loadCopy(): Promise<void> {
    await this.loadPdf();
    this.getCurrentStatus();
    // try to load the following copy
    let nextIndex = this.nextCopyIndex();
    if (nextIndex < this.examsList.length) {
      this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), nextIndex);
    }
  }

  verifyIfQuestionIsBonus(): void {
    if (this.currentGrade == null && this.bonusEnabledMap.get(this.currentQuestionIndex)) {
      this.currentGrade = 0;
      this.addScoreToQuestion();
      if (!this.bonusNoticationsShown.get(this.currentQuestionIndex)) {
        this.notificationService.showInfo('Cette question est une question bonus. Sa note initiale est 0.', 'Information');
        this.bonusNoticationsShown.set(this.currentQuestionIndex, true);
      }
    }
  }


  setChosenColor(status: string): void {
    if(status === "TO VALIDATE") {
      this.colorChosen = "red";
    }
    if(status === "HIGH ACCURACY") {
      this.colorChosen = "blue";
    }
    if(status === "VALIDATED") {
      this.colorChosen = "green";
    }
  }

  checkForAvailableCopies(): boolean {
    if (this.subExamsList.length == 0) return false;
    let exam = this.subExamsList.find((exam: any) => exam["status"] != "NOT_READY");
    console.log("Found ready exam", exam);
    return exam != undefined;
  }

  getCurrentStatus() {
    this.currentStatus = this.currentExam()["status"];
  }

  setValidatedStatus() {
    this.currentExam()["status"] = "VALIDATED";
  }


  async validateCurrentCopy() {
    if (this.hasDownloadedZip && !this.hasUploadedZip && this.currentIndex() === this.examsList.length - 1) {
      this.notificationService.showWarning("Vous n'avez téléversé aucun nouveaux fichiers.", 'Attention!');
    }

    try {
        if (this.addScoreToQuestion() && await this.saveCurrentCopy(true)) {
            this.setValidatedStatus();
            this.nextCopy();
        }
    } catch (error) {
        console.error('Erreur lors de la validation ou du téléchargement du fichier :', error);
        this.notificationService.showError('Échec de la validation ou du téléchargement du document.', 'Erreur de validation');
        this.changeCurrentExam(this.currentIndex());
    }
    this.checkValidationButton();
}

  async saveCurrentCopy(forceValidation: boolean = false) {
    const currentExam = this.currentExam();
    if (currentExam) {
      const filename = currentExam["filename"] + ".pdf";
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      if (forceValidation || editedPdfData) {
        // if file not modified, stop here and return true if not forcing validation
        const saveFile = (editedPdfData.size !== this.pdfSize || this.pdfModified);
        if (!forceValidation && !saveFile)
          return true;
        const file = saveFile ? new File([editedPdfData], filename, { type: editedPdfData.type }) : undefined;
        let validationResponse = await this.validationService.validateDocument(
            this.tasksService.getvalidatingTaskId(),
            this.currentCopy,
            file,
            this.currentQuestionIndex.slice(1),
            this.currentGradesMap.get(this.currentCopy),
            this.nMaxPointsPerQuestion,
            this.currentStatus
        );

        console.log('Save current copy and obtained response:', validationResponse);

        return (validationResponse === "OK");
      }
    }
    return true;  // nothing to do -> true
  }

  updateTotal(key, value): void {
    this.currentGrades[key] = value;
    this.currentTotal = this.getTotal();
  }

  getTotal(): number {
    let sum = 0;
    for (const question of Object.keys(this.currentGrades)) {
      sum += this.currentGrades[question];
    }
    return sum;
  }

  trackByIndex(index, _): number {
    return index;
  }

  currentIndex(): number {
    return this.currentCopy - this.initialCopyIndex;
  }

  currentExam() {
    return this.examsList[this.currentCopy - this.initialCopyIndex];
  }

  async reroute() {
    await this.saveCurrentCopy();
    this.router.navigate(['/dashboard', this.job["job_id"]]);
  }

  async previousCopy(): Promise<void> {
    let tempIndex = this.currentIndex() - 1;
    while (tempIndex >= 0 && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex --;
    }
    console.log("Previous copy", tempIndex)
    if (tempIndex >= 0) {
      await this.changeCurrentExam(tempIndex);
    }
  }

  async nextCopy(): Promise<void> {
    let tempIndex = this.nextCopyIndex();
    console.log("Next copy", tempIndex)
    if (tempIndex < this.examsList.length) {
      await this.changeCurrentExam(tempIndex);
    }
  }

  nextCopyIndex(): number {
    let tempIndex = this.currentIndex() + 1;
    while (tempIndex < this.examsList.length && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex ++;
    }
    return tempIndex;
  }

  loggued(): boolean {
    return this.userService.loggued();
  }

  sortNull(): void {}

  showFilter(): boolean {
    return this.loggued() && this.groupsList.length > 1;
  }

  filesListHeight(): string {
    let height = 80;
    if (!this.loggued()) height += 10;
    if (!this.showFilter()) height += 10;
    // console.log("height", height+"%")
    return height+"%";
  }

  checkValidationButton(): void {
    // this.disabledValidationButton = !this.job || this.job["job_status"] !== 'VALIDATION';
    const disabledValidationButton = this.examsList.some(exam => exam.status !== 'VALIDATED');
    const questionIndex = this.route.snapshot.queryParams['question_index'];

    if (!this.disabledDropDown) {
      this.disabledValidationButton = disabledValidationButton;
    } else if (questionIndex) {
      const subExams = this.examsList.filter(exam => exam.filename.includes(`Q${questionIndex}`));
      this.disabledValidationButton = subExams.some(exam => exam["status"] !== 'VALIDATED');
    }
  }

  async downloadAllFilesAsZip() {
    this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    const zip = new JSZip();
    const mergedDocs: { [key: string]: PDFDocument[] } = {};

    for (const exam of this.subExamsList) {
        if (exam["status"] !== 'NOT_READY') {
            const formdata: FormData = new FormData();
            this.userService.addTokens(formdata);
            formdata.append('job_id', this.tasksService.getvalidatingTaskId());
            formdata.append('document_index', exam["document_index"].toString());
            formdata.append('questions', 'true');

            await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' })
                .toPromise()
                .then(async (data: Blob) => {
                    const arrayBuffer = await data.arrayBuffer();
                    const pdfDoc = await PDFDocument.load(arrayBuffer);
                    const fileName = exam["filename"];
                    const questionIndex = exam["question"];

                    if (!mergedDocs[questionIndex]) {
                        mergedDocs[questionIndex] = [await PDFDocument.create()];
                    }

                    let cDoc = mergedDocs[questionIndex][mergedDocs[questionIndex].length - 1];
                    if (cDoc.getPageCount() >= this.maxCopiesPerPdf * pdfDoc.getPageCount()) {
                      cDoc = await PDFDocument.create();
                      mergedDocs[questionIndex].push(cDoc);
                    }

                    const copiedPages = await cDoc.copyPages(pdfDoc, pdfDoc.getPageIndices());
                    copiedPages.forEach((page) => {
                        cDoc.addPage(page);
                    });
                })
                .catch((error) => {
                    console.error(`Error downloading file ${exam["filename"]}:`, error);
                    this.notificationService.showError(`Erreur lors du téléchargement du fichier ${exam["filename"]}`, 'Erreur de téléchargement');
                });
        }
    }

    for (const questionIndex of Object.keys(mergedDocs)) {
        for (let i = 0; i < mergedDocs[questionIndex].length; i++) {
            const doc = mergedDocs[questionIndex][i];
            if (doc.getPageCount() > 0) {
                const mergedPdfBytes = await doc.save();
                const blob = new Blob([mergedPdfBytes], { type: 'application/pdf' });
                zip.file(`Q${questionIndex}${i > 0 ? `_${i}` : ''}.pdf`, blob);
            }
        }
    }

    const zipName = this.index && this.index !== "Tout sélectionner"
        ? `${this.job['job_name']}_Q${this.index}.zip`
        : `${this.job['job_name']}.zip`;

    zip.generateAsync({ type: 'blob' })
        .then((content) => {
            saveAs(content, zipName);
        });

    this.hasDownloadedZip = true;
    this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
  }

  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.uploadZipFile(file);
    }
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    const file = event.dataTransfer?.files[0];
    if (file) {
      this.uploadZipFile(file);
    }
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
  }

  async uploadZipFile(file: File) {
    const jobId = this.tasksService.getvalidatingTaskId();
    const nPagesPerQuestionArray = this.job["n_pages_per_question"];
    const nPagesPerQuestion = new Map<string, number>(nPagesPerQuestionArray);
    const zip = new JSZip();

    try {
        const zipContent = await JSZip.loadAsync(file);
        const mergedFiles = Object.keys(zipContent.files).filter(filename => filename.endsWith('.pdf'));
        const mergedPDFDocs = {};

        // loading and merge PDFs based on their question indices
        for (const mergedFile of mergedFiles) {
            try {
                const pdfData = await zipContent.file(mergedFile).async('arraybuffer');
                const pdfDoc = await PDFDocument.load(pdfData);
                const match = mergedFile.match(/Q(\d+).pdf$/);
                const questionIndex = match ? mergedPDFDocs[match[0].split(".")[0]] : "Unknown";
                if (!mergedPDFDocs[questionIndex]) {
                    mergedPDFDocs[questionIndex] = await PDFDocument.create();
                }

                const totalPageCount = pdfDoc.getPageCount();
                console.log(`The document ${mergedFile} has ${totalPageCount} pages.`);

                const copiedPages = await mergedPDFDocs[questionIndex].copyPages(pdfDoc, pdfDoc.getPageIndices());
                copiedPages.forEach((page) => {
                    mergedPDFDocs[questionIndex].addPage(page);
                });
            } catch (pdfError) {
                console.error(`Error processing merged file: ${mergedFile}`, pdfError);
            }
        }

        // processing each question index and replace the original documents
        for (const questionIndex of Object.keys(mergedPDFDocs)) {
            const mergedDoc = mergedPDFDocs[questionIndex];
            const totalPageCount = mergedDoc.getPageCount();
            const originalDocs = this.subExamsList.filter(exam => exam.question === `Q${questionIndex}`);
            const pagesPerQuestion = nPagesPerQuestion.get(`Q${questionIndex}`) || 1;

            let startPage = 0;
            for (const originalDoc of originalDocs) {
                try {
                    const singlePagePdf = await PDFDocument.create();
                    const endPage = startPage + pagesPerQuestion;

                    if (totalPageCount < endPage) {
                        console.warn(`The merged document for Q${questionIndex} does not have enough pages for ${originalDoc["filename"]}.pdf. Required: ${endPage}, available: ${totalPageCount}.`);
                        break;
                    }

                    const copiedPages = await singlePagePdf.copyPages(mergedDoc, Array.from({ length: pagesPerQuestion }, (_, k) => startPage + k));
                    copiedPages.forEach((page) => {
                        singlePagePdf.addPage(page);
                    });

                    const pdfBytes = await singlePagePdf.save();
                    const blob = new Blob([pdfBytes], { type: 'application/pdf' });
                    const fileName = originalDoc["filename"] + ".pdf";
                    zip.file(fileName, blob);

                    startPage = endPage;
                } catch (innerError) {
                    console.error(`Error processing original document: ${originalDoc["filename"]}.pdf`, innerError);
                }
            }
        }

        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        const finalZipFile = new File([finalZipBlob], 'split_documents.zip', { type: 'application/zip' });

        const uploadFormData = new FormData();
        this.userService.addTokens(uploadFormData);
        uploadFormData.append('job_id', jobId);
        uploadFormData.append('file', finalZipFile);
        uploadFormData.append('questions', 'true');

        await this.http.post(`${SERVER_URL}/documents/replace`, uploadFormData).toPromise()
            .then((response) => {
                console.log('Files replaced successfully', response);
                this.hasUploadedZip = true;
                this.notificationService.showSuccess('Fichiers remplacés avec succès!', 'Succès');
            })
            .catch((uploadError) => {
                console.error('Error replacing files:', uploadError);
                this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
            });

    } catch (zipError) {
        console.error('Error processing zip file:', zipError);
        this.notificationService.showError('Erreur lors du traitement du fichier zip', 'Erreur');
    }
  }
}

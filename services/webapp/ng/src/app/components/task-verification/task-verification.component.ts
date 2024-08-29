import { Component, HostListener, OnInit, OnDestroy, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { PdfManagementDialogComponent } from './pdf-management/pdf-management-dialog.component'
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { TasksService } from 'src/app/services/tasks.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { Router, ActivatedRoute } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { PDFViewerComponent } from 'src/app/components/pdf-viewer/pdf-viewer.component';
import { MatSelectChange } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { first } from 'rxjs/operators';
import { db, OfflineCopy } from './offline-db';


@Component({
  providers: [PDFViewerComponent],
  selector: 'app-task-verification',
  templateUrl: './task-verification.component.html',
  styleUrls: ['./task-verification.component.css']
})
export class TaskVerificationComponent implements OnInit, OnDestroy {

  constructor(private tasksService: TasksService,
    private validationService: ValidationService,
    private socketService: SocketService,
    private notificationService: NotificationService,
    public dialog: MatDialog,
    private router: Router,
    private route: ActivatedRoute,
    private userService: UserService,
    private docService: DocumentsService) {
      window.addEventListener('beforeunload', (event) => {
        if (this.offline) {
          event.preventDefault();
          event.returnValue = '';
        }
      });
    }

  @ViewChild(PDFViewerComponent)
  pdfViewer: PDFViewerComponent;

  isSidebarHidden: boolean = false;
  isIndexProvided: boolean = false;
  disabledValidationButton = true;
  disabledDropDown = false;
  validating: boolean = false;
  disablePrevious: boolean = false;
  disableNext: boolean = false;
  hasDownloadedZip: boolean = false;
  hasUploadedZip: boolean = false;

  job: Map<string, any>;

  offline: boolean = false;
  offlineCopies = new Map<number, OfflineCopy>();

  nMaxPointsPerQuestion = new Map<string, number>();
  bonusEnabledMap = new Map<string, boolean>();
  bonusNoticationsShown = new Map<string, boolean>();
  initialCopyIndex: number = -1;
  currentCopy: number = -1;
  currentCopyName: string;
  currentQuestionIndex: string;
  index: string = "Tout sélectionner";
  currentPdfSrc: PDFSource;
  currentGradeModified: boolean = false;
  currentVersion: number = 0;
  currentGrade: number | null;
  currentTotal: number;
  currentGrades: Map<string, number>;
  currentStatus: string;
  pdfUrl: string;

  colorChosen: string;

  examsList: Array<any>;
  subExamsList: Array<any>;
  group: string;
  groupsList: Array<string>;
  questionIndexes: Array<string> = [];
  formattedIndexes: Array<string> = [];

  async ngOnInit(): Promise<any> {
    // fetch query entries
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
    // this.groupsList = this.job['groups'];
    // this.groupsList.unshift("");
    this.getMaxPointsPerQuestion();
    this.getBonusEnabledMap();

    // fetch job and documents
    await this.getDocuments();

    // create indexedDB store
    db.setCurrentJobId(this.tasksService.getvalidatingTaskId());

    // load offline information
    if (await db.isOffline()) {
      this.offline = true;
      await this.loadOfflineCopies();
    }

    this.socketService.join(this.job["job_id"]);
    this.socketService.getSocket().on('document_ready', async (params: any) => {
      await this.getDocuments();
      this.nextCopy();
    });

    if (this.userService.loggued()) {
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
    this.docService.clearPdfSources();
    if (this.socketService.getSocket()){
      this.socketService.getSocket().off('document_ready');
      this.socketService.getSocket().off('job_status');
      this.socketService.disconnectSocket();
    }
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    if (!this.pdfViewer.isWriting()) {
      this.validateCurrentCopy();
    }
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
    this.currentGrade = this.currentExam()["grade"];
  }

  saveCurrentGrade(): boolean {
    if (this.currentExam()["grade"] !== this.currentGrade) {
      this.currentExam()["grade"] = this.currentGrade;
      return true;
    } else if (this.offline) {
      const offlineCopy = this.offlineCopies.get(this.currentCopy);
      return offlineCopy !== undefined && offlineCopy.grade !== undefined;
    }
    return false;
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
      this.route.params.pipe(first()).subscribe(params => {
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
    }
  }

 addGradeToQuestion(): boolean {
    if (this.currentGrade !== null) {
      if (this.currentGrade >= 0) {
        if (this.currentGrade > this.nMaxPointsPerQuestion.get(this.currentQuestionIndex)) {
          const excessPoints = this.currentGrade - this.nMaxPointsPerQuestion.get(this.currentQuestionIndex);
          this.notificationService.showWarning(`Vous avez rajouté ${excessPoints} point(s) bonus`, 'Attention!');
        }
        return this.saveCurrentGrade();
      } else {
        this.notificationService.showWarning('Veuillez saisir une note valide.', 'Note invalide');
        throw new Error('Note invalide');
      }
    } else {
      this.notificationService.showWarning('Veuillez saisir une note.', 'Note invalide');
      throw new Error('Note invalide');
    }
    return false;
  }

  async loadPdf(version: number = undefined): Promise<boolean> {
    if (this.currentExam()["status"] !== "NOT_READY") {
      this.checkNavigationArrows(false);
      let pdfSource;
      if (this.offline) {
        pdfSource = this.docService.getAvailablePdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy)
      } else {
        pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, version);
      }
      if (pdfSource) {
        this.currentPdfSrc = pdfSource;
        this.pdfUrl = pdfSource.url;
        this.pdfViewer.renderAnnotations(pdfSource.annotations);
        this.currentVersion = pdfSource.version;
        return true;
      } else {
        this.currentPdfSrc = undefined;
        this.pdfUrl = undefined;
        this.checkNavigationArrows(false);
        return false;
      }
    }
  }

  checkNavigationArrows(pdfLoaded: boolean) {
    this.disablePrevious = !pdfLoaded || this.offline || (this.currentVersion == 0);
    this.disableNext = !pdfLoaded || this.offline || (this.currentVersion >= this.currentPdfSrc.lastVersion);
  }

  async changeCurrentCopy(copyIndex, status, updateScroll: boolean=true): Promise<void> {
    if (status !== "NOT_READY") {
      if (await this.saveCurrentCopy()) {
        let exam = this.examsList[copyIndex-this.initialCopyIndex];
        console.log("Change current copy to", copyIndex)
        this.currentQuestionIndex = exam["question"];
        this.currentCopyName = exam["basename"];
        this.currentCopy = copyIndex;
        console.log("Current copy", this.currentCopy);
        if (await this.loadCopy()) {
          if (updateScroll) {
            this.updateScrollPosition();
          }
          this.setChosenColor(status);
          this.loadScore();
          this.verifyIfQuestionIsBonus();
        }
      } else {
          console.error('Erreur lors de l\'obtention du document PDF modifié.');
          this.notificationService.showError('Échec de la sauvegarde du document PDF modifié.', 'Erreur de validation');
      }
    }
  }

  updateScrollPosition() {
    let e = document.getElementById('files-list-container');  // scrollTop + clientHeight = scrollHeight
    if (e) {
      let child = e.firstElementChild;
      let nChildrenByRow = Math.floor(e.clientWidth / child.clientWidth);
      let nRows = Math.ceil(this.subExamsList.length / nChildrenByRow);
      let subIndex = 1 + this.subExamsList.findIndex(exam => exam.document_index === this.currentCopy);
      let currentRow = Math.ceil(subIndex / nChildrenByRow);  // start at 1
      let distanceTop = e.scrollHeight * currentRow / nRows;
      // goal is to be in the middle => clientHeight / 2
      let targetScrollTop = Math.floor(distanceTop - (e.clientHeight / 2));
      if (targetScrollTop > 0) {
        e.scrollTop = targetScrollTop;
      }
    }
  }

  async changeCurrentExam(examIndex): Promise<void> {
    await this.changeCurrentCopy(this.initialCopyIndex + examIndex, this.examsList[examIndex].status);
  }

  async setNewVersion(event){
    await this.loadPdf(event.target.value);
  }

  async loadCopy(): Promise<boolean> {
    const pdfLoaded = await this.loadPdf();
    this.currentGradeModified = false;
    this.getCurrentStatus();
    // try to load the following copy
    if (!this.offline) {
      let nextIndex = this.nextCopyIndex();
      if (nextIndex < this.examsList.length) {
        this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), nextIndex);
      }
    }
    return pdfLoaded;
  }

  verifyIfQuestionIsBonus(): void {
    if (this.currentGrade == null && this.bonusEnabledMap.get(this.currentQuestionIndex)) {
      this.currentGrade = 0;
      this.saveCurrentGrade();
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
    this.currentStatus = "VALIDATED";
    this.currentExam()["status"] = this.currentStatus;
  }


  async validateCurrentCopy() {
    if (!this.offline && this.hasDownloadedZip && !this.hasUploadedZip && this.currentIndex() === this.examsList.length - 1) {
      this.notificationService.showWarning("Vous n'avez téléversé aucun nouveaux fichiers.", 'Attention!');
    }

    let hasNext = false;
    try {
        const gradeChanged = this.addGradeToQuestion();
        if (gradeChanged) {
          this.currentGradeModified = true;  // ensure that the copy will be saved
        }
        this.setValidatedStatus();
        hasNext = await this.nextCopy();
    } catch (error) {
        console.error('Erreur lors de la validation ou du téléchargement du fichier :', error);
        this.notificationService.showError('Échec de la validation ou du téléchargement du document.', 'Erreur de validation');
        this.changeCurrentExam(this.currentIndex());
    }
    this.checkValidationButton();

    if (!hasNext) {
      this.isSidebarHidden = false;
    }
  }

  async saveCurrentCopy() {
    const currentExam = this.currentExam();
    if (currentExam) {
      // get the file only if it has been modified
      const filename = currentExam["filename"] + ".pdf";
      const file = await this.pdfViewer.getRenderedPdfFile(filename, !this.currentGradeModified);
      if (file !== undefined) {
        this.currentPdfSrc.annotations = this.pdfViewer.getAnnotations() || [];
        if (this.offline) {
          const copy = this.offlineCopies.get(this.currentCopy);
          copy.file = file;
          copy.status = this.currentStatus;
          if (this.currentGradeModified) {
            copy.grade = this.currentGrade;
          }
          db.updateCopy(copy);
        } else {
          let validationResponse = await this.saveCopy(
            this.currentPdfSrc,
            file,
            this.currentGradeModified ? this.currentGrade : undefined,
            this.currentStatus,
            this.currentQuestionIndex.slice(1));
          if (validationResponse === undefined) {
            this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche non disponible');
          }
          this.currentPdfSrc.lastVersion++;
          this.currentPdfSrc.version = this.currentPdfSrc.lastVersion;

          console.log('Save current copy and obtained response:', validationResponse);

          return validationResponse;
        }
      }
    }
    return true;  // nothing to do -> true
  }

  async saveCopy(pdfSource, file, grade, status, questionIndex): Promise<any> {
    let validationResponse = await this.validationService.validateDocument(
        this.tasksService.getvalidatingTaskId(),
        pdfSource.index,
        file,
        questionIndex,
        grade,
        this.nMaxPointsPerQuestion,
        status,
        pdfSource.version,
        pdfSource.annotations
    );
    return (validationResponse === "OK");
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

  async nextCopy(): Promise<boolean> {
    let tempIndex = this.nextCopyIndex();
    console.log("Next copy", tempIndex)
    if (tempIndex < this.examsList.length) {
      await this.changeCurrentExam(tempIndex);
      return true
    }
    return false
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

  managePdfs() {
    let dialogRef = this.dialog.open(PdfManagementDialogComponent, {
      width: '30%',
      height: '60%',
      data: {
        jobId: this.tasksService.getvalidatingTaskId(),
        index: this.index,
        jobName: this.job['job_name'],
        nPagesPerQuestion: this.job["n_pages_per_question"],
        examsList: this.subExamsList
      }
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async result => {
      if (result) {
        if (result.hasDownloadedZip) {
          this.hasDownloadedZip = true;
        } else if (result.hasUploadedZip) {
          this.hasUploadedZip = true;
          this.docService.clearPdfSources();
          this.loadCopy();
        }
      }
    }, (error) => {
      console.error(error);
    });
  }

  async correctOffline() {
    this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    this.offline = true;
    for (const exam of this.subExamsList) {
      const pdfSrc = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), exam['document_index']);
      if (!this.offline) {
        break;
      } 
      const copy: OfflineCopy = {
        pdfSrc: pdfSrc,
        status: exam['status'],
        questionIndex: exam['question_index']
      };
      this.offlineCopies.set(pdfSrc.index, copy);
      exam['offline'] = true;
    }
    await db.saveAllCopies(this.offlineCopies);
    this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
  }

  async uploadOffline() {
    this.notificationService.showInfo('Téléversement des copies en cours...', 'Information');
    for (const copy of this.offlineCopies.values()) {
      if (copy.file !== undefined) {
        let validationResponse = await this.saveCopy(
          copy.pdfSrc,
          copy.file,
          copy.grade,
          copy.status,
          copy.questionIndex);
        if (!validationResponse) {
          const index = copy.pdfSrc.index - this.subExamsList[0]['document_index'] + 1;
          this.notificationService.showError(`La copie ${index} n'a pu être sauvegardée.`, 'Error');
          return;
        } else {
          this.examsList[copy.pdfSrc.index]['offline'] = false;
        }
      }
    }
    this.notificationService.showSuccess('Téléversement terminé!', 'Success');
    await this.cleanOffline();
  }

  async cleanOffline() {
    for (const exam of this.subExamsList) {
      exam['offline'] = false;
    }
    this.docService.clearPdfSources();
    db.deleteAllCopies(this.offlineCopies);
    this.offlineCopies = new Map<number, OfflineCopy>();
    this.offline = false;
    await db.markOnline();
  }

  async loadOfflineCopies() {
    const allCopies = await db.getAllCopies();
    for (let copy of allCopies) {
      if (copy.grade) {
        this.examsList[copy.pdfSrc.index]["grade"] = copy.grade;
      }
      copy.pdfSrc = this.docService.loadPDFSource(copy.pdfSrc);
      this.examsList[copy.pdfSrc.index]['offline'] = true;
      this.examsList[copy.pdfSrc.index]['status'] = copy.status;
      this.offlineCopies.set(copy.pdfSrc.index, copy);
    }
  }

  cancelOffline() {
    let dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '40%',
      height: '50%',
      data: "Êtes-vous sur de vouloir annuler la correction?"
    })
    dialogRef.afterClosed().pipe(first()).subscribe(async result => {
      if (result !== undefined && result === true) {
        this.notificationService.showSuccess('Correction annulée!', 'Success');
        this.cleanOffline();
      }
    });
  }
}

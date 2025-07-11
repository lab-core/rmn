import { Component, HostListener, OnInit, OnDestroy, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { PdfManagementDialogComponent } from '../pdf-management/pdf-management-dialog.component'
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
  disabledValidationButton = true;
  disabledDropDown = false;
  shareAll: boolean = false;
  pdfLoading: boolean = false;
  disablePrevious: boolean = false;
  disableNext: boolean = false;
  isRestoreHiglighted: number = 0;
  hasDownloadedZip: boolean = false;
  hasUploadedZip: boolean = false;

  job: any;

  offline: boolean = false;
  downloadingOffline: boolean = false;
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
  currentTagModified: boolean = false;
  currentVersion: number = 0;
  currentGrade: number | null;
  currentTotal: number;
  currentGrades: Map<string, number>;
  currentStatus: string;
  currentTag: string;
  pdfUrl: string;

  colorChosen: string;

  examsList: Array<any>;
  subExamsList: Array<any>;
  group: string;
  groupsList: Array<string>;
  questionIndexes: Array<string> = [];
  formattedIndexes: Array<string> = [];
  availableTags: Array<string> = ["1", "2"]; // ["1", "2", "3"];
  tagFilter: string = "";

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

    if (this.route.snapshot.queryParams['all']) {
      this.shareAll = true;
    }

    try {
      this.job = await this.tasksService.getTask();
    } catch (err) {
      console.error(err);
    }
    if (!this.job || !this.job.job_id) {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche indisponible');
      this.router.navigate(['/tasks-history']);
    } else if (this.job.job_status === 'VALIDATED' ||
               this.job.job_status === 'FINALIZING' ||
               this.job.job_status === 'ARCHIVED') {
      this.notificationService.showWarning('Veuillez sélectionner une tâche active!', 'Tâche inactive');
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

    this.socketService.join(this.job.job_id);
    this.socketService.getSocket().on('document_ready', async (params: any) => {
      await this.getDocuments();
      if (this.currentCopy < 0 || this.currentExam()['status'] === "VALIDATED") {
        this.nextCopy();
      }
    });

    if (this.userService.loggued()) {
      this.socketService.join(this.userService.currentUsername);
      this.socketService.getSocket().on('job_status', async (params: any) => {
        const resp = JSON.parse(params);
        const jobId = resp.job_id;
        if (this.job.job_id === jobId) {
          this.job.job_status = resp.status;
          this.checkValidationButton();
        }
      });
    }
    this.generateFormattedIndexes();
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

  isScoreActive() {
    let el = document.activeElement;
    return el.id === 'score';
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownEnterHandler(event: KeyboardEvent) {
    if (!this.pdfViewer.isWriting() && !this.pdfLoading) {
      this.validateCurrentCopy();
    }
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  onKeydownArrowRightHandler(event: KeyboardEvent) {
    if (!this.pdfViewer.isWriting() && !this.isScoreActive()) {
      this.nextCopy();
    }
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  onKeydownArrowLeftHandler(event: KeyboardEvent) {
    if (!this.pdfViewer.isWriting() && !this.isScoreActive()) {
      this.previousCopy();
    }
  }

  @HostListener('document:keydown.arrowup', ['$event'])
  onKeydownArrowUpHandler(event: KeyboardEvent) {
    if (this.isScoreActive()) {
      return;
    }
    // move up (-> 4 copies)
    let tempIndex = this.previousCopyIndex();
    let i = 1;
    while (tempIndex >= 0 && i < 4) {
      tempIndex = this.previousCopyIndex(tempIndex);
      i ++;
    }
    if (tempIndex < 0) {
      tempIndex = this.nextCopyIndex(tempIndex);
    }
    if (tempIndex < this.examsList.length) {
      this.changeCurrentExam(tempIndex);
    }
  }

  @HostListener('document:keydown.arrowdown', ['$event'])
  onKeydownArrowDownHandler(event: KeyboardEvent) {
    if (this.isScoreActive()) {
      return;
    }

    // move down (-> 4 copies)
    let tempIndex = this.nextCopyIndex();
    let i = 1;
    while (tempIndex < this.examsList.length && i < 4) {
      tempIndex = this.nextCopyIndex(tempIndex);
      i ++;
    }
    if (tempIndex >= this.examsList.length) {
      tempIndex = this.previousCopyIndex(tempIndex);
    }
    if (tempIndex >= 0) {
      this.changeCurrentExam(tempIndex);
    }
  }

  toggleSidebar() {
    this.isSidebarHidden = !this.isSidebarHidden;
    if (this.isSidebarHidden) {
      const nextIndex = this.nextCopyIndexTagFilter(this.currentIndex() - 1);
      if (nextIndex != this.currentIndex() && nextIndex < this.examsList.length) {
        this.changeCurrentExam(nextIndex);
      }
    }
  }

  generateFormattedIndexes(): void {
    this.formattedIndexes = [];
    const maxIndex = this.examsList.length;
    const questionString = `Q1`;
    let subExamsListSize = this.examsList.filter(exam => exam.question === questionString).length;
    if (subExamsListSize === 0) {
      subExamsListSize = maxIndex;
    }

    for (let i = 1; i <= Math.ceil(maxIndex / subExamsListSize); i++) {
        for (let j = 1; j <= subExamsListSize; j++) {
            const index = `${j}|Q${i}`;
            if ((i - 1) * subExamsListSize + j <= maxIndex) {
                this.formattedIndexes.push(index);
            }
        }
    }
  }

  getExamClass(exam: any): string {
    let examClass: string;
    if (exam.status == 'VALIDATED') {
      examClass = 'validated-copy';
    } else if (exam.status == 'TO VALIDATE') {
      examClass = 'to-validate-copy';
      if (this.availableTags.includes(exam.tag)) {
        examClass += ' tag-color-' + exam.tag;
      }
    } else if (exam.status == 'HIGH ACCURACY') {
      examClass = 'high-precision-copy';
    } else if (exam.status == 'DELETED') {
      examClass = 'deleted-copy';
    }

    if (exam.document_index == this.currentCopy) {
        examClass += ' chosen-copy';
    }

    return examClass;
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
      return offlineCopy != undefined && offlineCopy.grade != undefined;
    }
    return false;
  }

  initializeQuestionIndexes(): void {
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // check then question
    this.questionIndexes = ["Tout sélectionner", ...Array.from({ length: this.nMaxPointsPerQuestion.size }, (_, i) => (i + 1).toString())];
    // if question index is provided in query params
    const questionIndex = this.route.snapshot.queryParams['question_index'];
    if (questionIndex) {
      this.index = questionIndex;
      this.onQuestionIndexChange({ value: questionIndex } as MatSelectChange);
      this.disabledDropDown = this.userService.shared() && !this.shareAll;
    } else {
      this.route.params.pipe(first()).subscribe(params => {
        const index = params['index'];
        if (index) {
          this.index = index;
          this.onQuestionIndexChange({ value: index } as MatSelectChange);
        } else if (this.checkForAvailableCopies()) {
          this.changeCurrentExam();
        }
      });
    }
  }

  onQuestionIndexChange(event: MatSelectChange): void {
    if (event.value === "Tout sélectionner") {
        this.subExamsList = this.examsList;
        this.generateFormattedIndexes();
    } else {
        this.filterExamsByQuestion(event.value);
    }
    if (this.subExamsList.length > 0) {
        const left = (this.currentCopy - this.initialCopyIndex) % this.subExamsList.length;
        let initExam = this.subExamsList[left >= 0 ? left : 0];
        this.changeCurrentCopy(initExam["document_index"], initExam["status"]);
    }
  }

  filterExamsByQuestion(questionIndex: number): void {
    const questionString = `Q${questionIndex}`;
    this.subExamsList = this.examsList.filter(exam => exam.question === questionString);

    this.formattedIndexes = this.subExamsList.map((_, i) => {
      const subIndex = (i % this.subExamsList.length) + 1;
      return `${subIndex}`;
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

  onTagChange(event: MatSelectChange): void {
    this.tagFilter = event.value;
    const nextIndex = this.nextCopyIndexTagFilter(this.initialCopyIndex - 1);
    if (nextIndex < this.examsList.length) {
      this.changeCurrentExam(nextIndex);
    }
  }

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId(), true);
    this.examsList = this.docService.documentsList;
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0 && this.initialCopyIndex < 0) {
      this.initialCopyIndex = this.examsList[0].document_index;
      this.initializeCopy();
    }
  }

  initializeCopy() {
    const copy = localStorage.getItem(`${this.tasksService.getvalidatingTaskId()}_copy`);
    if (copy != undefined) {
      this.currentCopy = parseInt(copy);
    } else {
      this.currentCopy = this.initialCopyIndex;
    }
  }

  setCurrentCopy(copy: number) {
    const jobId = this.tasksService.getvalidatingTaskId();
    localStorage.setItem(`${jobId}_copy`, copy.toString());
    this.currentCopy = copy;
  }

 getMaxPointsPerQuestion() {
    this.nMaxPointsPerQuestion = new Map<string, number>();
    this.job.n_max_points_per_question.forEach(e => {
      this.nMaxPointsPerQuestion.set(e[0], e[1]);
    });
  }

 getBonusEnabledMap() {
    this.bonusEnabledMap = new Map<string, boolean>();
    this.job.bonus_enabled_map.forEach(e => {
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

 addGradeToQuestion(validGrade: boolean): boolean {
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
    } else if (validGrade) {
      this.notificationService.showWarning('Veuillez saisir une note.', 'Note invalide');
      throw new Error('Note invalide');
    }
    return false;
  }

  async loadPdf(version: number = undefined): Promise<boolean> {
    if (this.currentExam()["status"] !== "NOT_READY") {
      this.checkNavigationArrows(false);
      this.pdfLoading = true;
      let pdfSource;
      if (this.offline) {
        pdfSource = this.docService.getAvailablePdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy)
      } else {
        pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, true, version);
      }
      this.pdfLoading = false;
      if (pdfSource) {
        if (this.pdfUrl != pdfSource.url) {
          this.currentPdfSrc = pdfSource;
          this.pdfUrl = pdfSource.url;
          this.pdfViewer.renderAnnotations(pdfSource.annotations, pdfSource.modified);
          this.currentVersion = pdfSource.version;
        }
        return true;
      } else {
        this.currentPdfSrc = undefined;
        this.pdfUrl = undefined;
        this.checkNavigationArrows(false);
        return false;
      }
    }
  }

  async restoreLatestPdf(): Promise<void> {
    // load latest pdf without annotations separated
    this.isRestoreHiglighted = 0;
    this.pdfLoading = true;
    let pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, false, undefined, -1);
    this.pdfLoading = false;
    if (pdfSource) {
      pdfSource.lastVersion = this.currentPdfSrc.lastVersion;
      this.currentPdfSrc = pdfSource;
      this.pdfUrl = pdfSource.url;
      this.currentVersion = pdfSource.version;
    } else {
      this.notificationService.showError('Échec de la récupération de la dernière version du PDF.', 'Erreur de restoration');
    }
  }

  checkNavigationArrows(pdfLoaded: boolean) {
    this.disablePrevious = !pdfLoaded || this.offline || (this.currentVersion == 0);
    this.disableNext = !pdfLoaded || this.offline || (this.currentVersion >= this.currentPdfSrc.lastVersion) || (this.currentVersion == undefined);
  }

  async changeCurrentCopy(copyIndex, status, updateScroll: boolean=true): Promise<void> {
    if (status !== "NOT_READY") {
      this.pdfLoading = true;
      if (await this.saveCurrentCopy()) {
        const exam = this.examsList[copyIndex-this.initialCopyIndex];
        console.log("Change current copy to", copyIndex)
        this.currentQuestionIndex = exam.question;
        this.currentCopyName = exam.basename;
        this.currentTag = exam.tag;
        this.setCurrentCopy(copyIndex);
        if (await this.loadCopy()) {
          if (updateScroll) {
            this.updateScrollPosition();
          }
          this.setChosenColor(status, this.currentTag);
          this.loadScore();
          this.verifyIfQuestionIsBonus();
        }
      } else {
          console.error('Erreur lors de l\'obtention du document PDF modifié.');
          this.notificationService.showError('Échec de la sauvegarde du document PDF modifié.', 'Erreur de validation');
      }
      this.pdfLoading = false;
    }
  }

  updateScrollPosition() {
    let e = document.getElementById('files-list-container');  // scrollTop + clientHeight = scrollHeight
    if (e) {
      let child = e.firstElementChild;
      if (child) {
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
  }

  async changeCurrentExam(examIndex: number = this.currentIndex()): Promise<void> {
    await this.changeCurrentCopy(this.initialCopyIndex + examIndex, this.examsList[examIndex].status);
  }

  async setNewVersion(event){
    await this.loadPdf(event.target.value);
  }

  async loadCopy(): Promise<boolean> {
    const pdfLoaded = await this.loadPdf();
    this.currentGradeModified = false;
    this.currentTagModified = false;
    this.getCurrentStatus();
    // try to load the following copy
    if (!this.offline) {
      let nextIndex = this.nextCopyIndex();
      if (nextIndex < this.examsList.length) {
        this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.initialCopyIndex + nextIndex);
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

  setChosenColor(status: string, tag): void {
    if(status === "TO VALIDATE") {
      this.colorChosen = "red";
      if (this.availableTags.includes(tag)) {
        this.colorChosen = 'tag-color-' + tag;
      }
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
    return exam != undefined;
  }

  getCurrentStatus() {
    this.currentStatus = this.currentExam()["status"];
  }

  setValidatedStatus(): boolean {
    if (this.currentStatus != "VALIDATED") {
      this.currentStatus = "VALIDATED";
      return true;
    } else {
      return false;
    }
  }

  async validateCurrentCopy() {
    const statusChanged = this.setValidatedStatus();
    if (statusChanged) {
      this.currentGradeModified = true;  // ensure that the copy will be saved
    }
    await this.updateCurrentCopy(true);
  }

  async skipCurrentCopy(tag) {
    this.currentTag = tag;
    const exam = this.currentExam();
    if (exam["tag"] != tag) {
      this.currentTagModified = true;  // ensure that the copy will be saved
    }
    this.currentStatus = "TO VALIDATE";
    exam["tag"] = tag;
    await this.updateCurrentCopy(false);
  }

  isRespectingTagFilter(exam) {
    // default current copy
    if (this.tagFilter === "") return true;
    if (exam.status === 'TO VALIDATE') {
      // default next copy to validate -> comment first line
      if (this.tagFilter === "") return true;
      if (this.tagFilter === exam.tag) return true;
      if (this.tagFilter === "0" && exam.tag == undefined) return true;
    } else if (exam.status === this.tagFilter) {
      return true;
    }
    return false;
  }

  nextCopyIndexTagFilter(currentIndex = undefined): number {
    let nextIndex = this.nextCopyIndex(currentIndex);
    while (nextIndex < this.examsList.length) {
      const exam = this.examsList[nextIndex - this.initialCopyIndex];
      if (this.isRespectingTagFilter(exam)) break;
      nextIndex = this.nextCopyIndex(nextIndex);
    }
    return nextIndex;
  }

  async updateCurrentCopy(checkValidGrade: boolean) {
    if (!this.offline && this.hasDownloadedZip && !this.hasUploadedZip && this.currentIndex() === this.examsList.length - 1) {
      this.notificationService.showWarning("Vous n'avez téléversé aucun nouveaux fichiers.", 'Attention!');
    }

    let hasNext = false;
    try {
        const gradeChanged = this.addGradeToQuestion(checkValidGrade);
        if (gradeChanged) {
          this.currentGradeModified = true;  // ensure that the copy will be saved
        }
        this.currentExam()["status"] = this.currentStatus;  // update status
        if (this.isSidebarHidden) {
          hasNext = await this.nextCopy(gradeChanged, () => { return this.nextCopyIndexTagFilter() });
        } else {
          hasNext = await this.nextCopy(gradeChanged);
        }
    } catch (error) {
        console.error('Erreur lors de la validation ou du téléchargement du fichier :', error);
        this.notificationService.showError('Échec de la validation ou du téléchargement du document.', 'Erreur de validation');
        this.pdfLoading = false;
        // this.changeCurrentExam(this.currentIndex());
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
      let file;
      try {
        file = await this.pdfViewer.getRenderedPdfFile(filename, !(this.currentGradeModified || this.currentTagModified));
        this.isRestoreHiglighted = 0;
      } catch(err) {
        console.error(err);
        this.notificationService.showError('Le document PDF semble corrompu. Essayer de le restorer.', 'PDF corrompu');
        this.isRestoreHiglighted += 1;
        setTimeout(() => { if (this.isRestoreHiglighted > 0) this.isRestoreHiglighted -= 1 }, 20000);
        return false;
      }
      if (file != undefined) {
        this.currentPdfSrc.annotations = this.pdfViewer.getAnnotations() || [];
        if (this.offline) {
          const copy = this.offlineCopies.get(this.currentCopy);
          copy.file64 = await PDFSource.readBlobSync(file);
          copy.status = this.currentStatus;
          if (this.currentTagModified) copy.tag = this.currentTag;
          copy.updated = false;
          if (this.currentGradeModified) {
            copy.grade = this.currentGrade;
          }
          db.updateCopy(copy);
        } else {
          let result = await this.saveCopy(
            this.currentPdfSrc,
            file,
            this.currentGradeModified ? this.currentGrade : undefined,
            this.currentStatus,
            this.currentQuestionIndex.slice(1),
            this.currentTagModified ? this.currentTag : undefined);
          if (result) {
            this.currentPdfSrc.lastVersion++;
            this.currentPdfSrc.version = this.currentPdfSrc.lastVersion;
          }
          return result;
        }
      }
    }
    return true;  // nothing to do -> true
  }

  async saveCopy(pdfSource, file, grade, status, questionIndex, tag = undefined): Promise<any> {
    const jobId = this.tasksService.getvalidatingTaskId();
    pdfSource.save(jobId);
    let validationResponse = await this.validationService.validateDocument(
        jobId,
        pdfSource.index,
        file,
        questionIndex,
        grade,
        this.nMaxPointsPerQuestion,
        status,
        pdfSource.version == undefined ? -1 : pdfSource.version,
        pdfSource.annotations,
        tag
    );
    console.log('Try to save current copy and obtained response:', validationResponse);
    if (validationResponse === "OK") {
      pdfSource.clear(jobId);
      return true;
    }

    return false;
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
    if (!this.examsList) {
      return undefined;
    }
    return this.examsList[this.currentCopy - this.initialCopyIndex];
  }

  async reroute() {
    if (await this.saveCurrentCopy()) {
      if (this.shareAll) {
        const queryParams = {
          job_id: this.job.job_id,
        }
        this.userService.addShareToken(queryParams);
        this.router.navigate([`/dashboard`], { queryParams: queryParams });
      } else {
        this.router.navigate(['/dashboard', this.job.job_id]);
      }
    }
  }

  async previousCopy(): Promise<boolean> {
    let tempIndex = this.previousCopyIndex();
    if (tempIndex >= 0) {
      await this.changeCurrentExam(tempIndex);
      return true
    }
    return false
  }

  previousCopyIndex(currentIndex = undefined): number {
    let tempIndex = currentIndex != undefined ? currentIndex : this.currentIndex();
    tempIndex--;
    while (tempIndex >= 0 && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex --;
    }
    return tempIndex;
  }

  async nextCopy(changeAnyway: boolean = false, indexFilter = () => { return this.nextCopyIndex() }): Promise<boolean> {
    let tempIndex = indexFilter();
    if (tempIndex < this.examsList.length) {
      await this.changeCurrentExam(tempIndex);
      return true
    } else if (changeAnyway) {
      await this.changeCurrentExam();
    }
    return false
  }

  nextCopyIndex(currentIndex = undefined): number {
    let tempIndex = currentIndex != undefined ? currentIndex : this.currentIndex();
    tempIndex++;
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
    return (this.loggued() || this.shareAll) && this.groupsList.length > 1;
  }

  filesListHeight(): string {
    let height = 80;
    if (!this.userService.shared()) height += 10;
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
        jobName: this.job.job_name,
        nPagesPerQuestion: this.job.n_pages_per_question,
        nMaxPointsPerQuestion: this.nMaxPointsPerQuestion,
        bonusEnabledMap: this.bonusEnabledMap,
        examsList: this.subExamsList,
        offlineCopies: this.offlineCopies
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
          this.loadScore();
        }
      }
    }, (error) => {
      console.error(error);
    });
  }

  async correctOffline() {
    this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    this.downloadingOffline = true;
    this.offline = true;
    for (const exam of this.subExamsList) {
      if (!this.offline) {
        break;
      }
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
      this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    }
    await db.saveAllCopies(this.offlineCopies);
    if (this.offline) {
      this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
    } else {
      this.cleanOffline()
    }
    this.downloadingOffline = false;
  }

  async uploadOffline(finalize: boolean) {
    this.notificationService.showInfo('Téléversement des copies en cours...', 'Information');
    this.downloadingOffline = true;
    for (const copy of this.offlineCopies.values()) {
      if (copy.file64 != undefined && !copy.updated) {
        let cFile: File = await fetch(copy.file64).then(res => res.blob()).then(blob => {
          const exam = this.examsList[copy.pdfSrc.index];
          return new File([blob], exam["filename"] + ".pdf", { type: "application/pdf" });
        })
        let result = await this.saveCopy(
          copy.pdfSrc,
          cFile,
          copy.grade,
          copy.status,
          copy.questionIndex);
        if (!result) {
          const index = copy.pdfSrc.index - this.subExamsList[0]['document_index'] + 1;
          this.notificationService.showError(`La copie ${index} n'a pu être sauvegardée.`, 'Error');
          return;
        }
        copy.updated = true;
        this.notificationService.showInfo('Téléversement des copies en cours...', 'Information');
      }
      if (finalize) this.examsList[copy.pdfSrc.index]['offline'] = false;
    }
    this.notificationService.showSuccess('Téléversement terminé!', 'Success');
    if (finalize) await this.cleanOffline();
    this.downloadingOffline = false;
  }

  async cleanOffline() {
    for (const exam of this.subExamsList) {
      exam['offline'] = false;
    }
    db.deleteAllCopies(this.offlineCopies);
    this.offline = false;
    this.downloadingOffline = false;
    await db.markOnline();
  }

  async loadOfflineCopies() {
    const allCopies = await db.getAllCopies();
    for (let copy of allCopies) {
      if (copy.grade != undefined) {
        this.examsList[copy.pdfSrc.index]["grade"] = copy.grade;
      }
      copy.pdfSrc = await this.docService.loadPDFSource(copy.pdfSrc);
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
      if (result != undefined && result === true) {
        this.notificationService.showSuccess('Correction annulée!', 'Success');
        this.cleanOffline();
      }
    });
  }
}

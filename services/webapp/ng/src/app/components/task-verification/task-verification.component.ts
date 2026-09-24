import { Component, HostListener, OnInit, OnDestroy, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { PdfManagementDialogComponent } from '../pdf-management/pdf-management-dialog.component'
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { TasksService } from 'src/app/services/tasks.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SocketHandler, SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { Router, ActivatedRoute } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { PDFViewerComponent } from 'src/app/components/pdf-viewer/pdf-viewer.component';
import { MatSelectChange } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { first } from 'rxjs/operators';
import { db, OfflineCopy } from 'src/app/services/offline-db';
import { DocumentStatus, JobStatus } from '../../generated/rmn-contracts';
import { selectedCopyIndex } from 'src/app/selected-copy';


@Component({
    providers: [PDFViewerComponent],
    selector: 'app-task-verification',
    templateUrl: './task-verification.component.html',
    styleUrls: ['./task-verification.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TaskVerificationComponent implements OnInit, OnDestroy {
  readonly DocumentStatus = DocumentStatus;

  constructor(private tasksService: TasksService,
    private validationService: ValidationService,
    private socketService: SocketService,
    private notificationService: NotificationService,
    public dialog: MatDialog,
    private router: Router,
    private route: ActivatedRoute,
    private userService: UserService,
    private docService: DocumentsService) {}

  // a window listener added in the constructor was never removed: each visit
  // pinned the destroyed component (and its pdf blobs) through the closure
  @HostListener('window:beforeunload', ['$event'])
  warnBeforeLeavingOffline(event: BeforeUnloadEvent) {
    if (this.offline) {
      event.preventDefault();
      event.returnValue = '';
    }
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
  currentCopy: number = -1;
  currentCopyName: string;
  currentDocumentIndex: number = -1;
  currentQuestionIndex: string;
  index: string = "Tout sélectionner";
  currentPdfSrc: PDFSource;
  currentGradeModified: boolean = false;
  currentTagModified: boolean = false;
  currentVersion: number = 0;
  currentGrade: number | null;
  // the grade shown came from the reader, not from a human, and has not been
  // confirmed yet
  currentGradeIsAuto: boolean = false;
  currentGradeConfidence: number | null = null;
  // what the reader is doing right now, straight from the executor
  readingInfo: string = '';
  // and where it has got to on the question being corrected, from POST /job
  autoGradeProgress: {[q: string]: {pending: number, running: number, done: number,
                                    graded: number, total: number}} = {};

  readingStateForQuestion(): string {
    const p = this.autoGradeProgress[String(this.currentQuestionIndex)];
    if (!p || !p.total) {
      return '';
    }
    // copies the teacher has already graded are not read, and are said so
    const toRead = p.total - (p.graded || 0);
    if (p.running) {
      const percent = toRead ? Math.round(100 * p.done / toRead) : 100;
      return `Lecture des notes en cours : ${percent} %`;
    }
    if (p.pending) {
      return `Lecture des notes à faire : ${p.done}/${toRead}`;
    }
    return `Notes lues automatiquement : ${p.done}/${toRead}`;
  }
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
  // copy label by document index: the tiles iterate the filtered list, so a
  // label stored by position pointed at another copy once a filter was on
  formattedIndexes: Record<number, string> = {};
  availableTags: Array<string> = ["1", "2"]; // ["1", "2", "3"];
  tagFilter: string = "";

  async ngOnInit(): Promise<any> {
    // fetch query entries
    const jobId = this.route.snapshot.queryParams['job_id'];
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
      this.autoGradeProgress = this.job.auto_grade_progress || {};
    } catch (err) {
      console.error(err);
    }
    // stop here after redirecting: the rest of the initialisation used to run
    // on an undefined job and throw
    if (!this.job || !this.job.job_id) {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche indisponible');
      this.router.navigate(['/tasks-history']);
      return;
    } else if (this.job.job_status === JobStatus.VALIDATED ||
               this.job.job_status === JobStatus.FINALIZING ||
               this.job.job_status === JobStatus.ARCHIVED) {
      this.notificationService.showWarning('Veuillez sélectionner une tâche active!', 'Tâche inactive');
      this.router.navigate(['/tasks-history']);
      return;
    }

    // set job parameters
    // this.groupsList = this.job['groups'];
    // this.groupsList.unshift("");
    this.getMaxPointsPerQuestion();
    this.getBonusEnabledMap();

    // fetch job and documents
    await this.getDocuments();

    // if no exam available -> reroute to the dashboard
    if (this.examsList.length === 0) {
      this.router.navigate(['/dashboard', this.tasksService.getvalidatingTaskId()]);
    }

    // create indexedDB store
    db.setCurrentJobId(this.tasksService.getvalidatingTaskId());

    // load offline information
    if (await db.isOffline()) {
      this.offline = true;
      await this.loadOfflineCopies();
    }

    this.socketService.join(this.job.job_id);
    this.onDocumentReady = async (params: any) => {
      // a reading pass emits this once, when it is done
      this.readingInfo = '';
      await this.getDocuments();
      if (this.currentCopy < 0 || this.currentExam()['status'] === DocumentStatus.VALIDATED) {
        this.nextCopy();
      }
    };
    this.socketService.on('document_ready', this.onDocumentReady);

    if (this.userService.loggued()) {
      this.socketService.join(this.userService.currentUsername);
      this.onJobStatus = async (params: any) => {
        const resp = JSON.parse(params);
        const jobId = resp.job_id;
        if (this.job.job_id === jobId) {
          this.job.job_status = resp.status;
          // the executor reports what it is doing here; the reading pass is
          // the only work that runs while a task is being corrected
          if (resp.job_infos) {
            this.readingInfo = resp.job_infos;
          }
          this.checkValidationButton();
        }
      };
      this.socketService.on('job_status', this.onJobStatus);
    }
    this.generateFormattedIndexes();
    this.initializeQuestionIndexes();
    this.checkValidationButton();
  }

  private onDocumentReady: SocketHandler;
  private onJobStatus: SocketHandler;

  async ngOnDestroy(): Promise<any> {
    this.docService.clearPdfSources();
    // this page's handlers and rooms only: the socket stays open for the next page
    if (this.onDocumentReady) {
      this.socketService.off('document_ready', this.onDocumentReady);
    }
    if (this.onJobStatus) {
      this.socketService.off('job_status', this.onJobStatus);
    }
    if (this.job) {
      this.socketService.leave(this.job.job_id);
    }
  }

  isScoreActive() {
    const el = document.activeElement;
    return el.id === 'score';
  }

  @HostListener('document:keydown.enter', ['$event'])
  async onKeydownEnterHandler(event: KeyboardEvent) {
    if (!this.pdfViewer.isWriting() && !this.pdfLoading) {
      await this.validateCurrentCopy();
      setTimeout(() => {
        const input = document.getElementById('score') as HTMLInputElement;
        input.focus();
        input.select();
      });
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
      const nextIndex = this.nextCopyIndexTagFilter(this.currentCopy - 1);
      if (nextIndex !== this.currentCopy && nextIndex < this.examsList.length) {
        this.changeCurrentExam(nextIndex);
      }
    }
  }

  generateFormattedIndexes(): void {
    this.formattedIndexes = {};
    const indices = {};
    for (const exam of this.examsList) {
      if (!(exam.question in indices)) {
        indices[exam.question] = 1;
      }
      this.formattedIndexes[exam.document_index] = `${indices[exam.question]}|${exam.question}`;
      indices[exam.question] += 1;
    }
  }

  getExamClass(exam: any): string {
    let examClass: string;
    if (exam.status === DocumentStatus.VALIDATED) {
      examClass = 'validated-copy';
    } else if (exam.status === DocumentStatus.TO_VALIDATE) {
      examClass = 'to-validate-copy';
      if (this.availableTags.includes(exam.tag)) {
        examClass += ' tag-color-' + exam.tag;
      }
    } else if (exam.status === DocumentStatus.HIGH_ACCURACY) {
      examClass = 'high-precision-copy';
    } else if (exam.status === DocumentStatus.DELETED) {
      examClass = 'deleted-copy';
    }

    if (exam.document_index === this.currentDocumentIndex) {
        examClass += ' chosen-copy';
    }

    return examClass;
  }

  loadScore(): void {
    // a confirmed grade always wins; otherwise offer what the reader made of
    // the page, marked as a suggestion so the teacher can see it is one
    const grade = this.currentExam()["grade"];
    const autoGrade = this.currentExam()["auto_grade"];
    this.currentGradeIsAuto = grade === null && autoGrade !== null && autoGrade !== undefined;
    this.currentGradeConfidence = this.currentGradeIsAuto
      ? this.currentExam()["auto_grade_confidence"] ?? null
      : null;
    this.currentGrade = this.currentGradeIsAuto ? autoGrade : grade;
  }

  autoGradeHint(): string {
    // the score box is 80px wide: this is a tooltip, not a caption
    if (!this.currentGradeIsAuto) {
      return '';
    }
    const confidence = this.currentGradeConfidence;
    return confidence === null
      ? 'Note lue automatiquement, à confirmer.'
      : `Note lue automatiquement (confiance ${Math.round(confidence * 100)} %), à confirmer.`;
  }

  gradeColor(): string {
    // the colours the copy tiles and the validate button already use: green
    // once a human has validated, blue when the machine is confident, red
    // when it is not
    if (this.currentStatus === DocumentStatus.VALIDATED) {
      return 'note-green';
    }
    if (this.currentStatus === DocumentStatus.HIGH_ACCURACY) {
      return 'note-blue';
    }
    return 'note-red';
  }

  saveCurrentGrade(): boolean {
    if (this.currentExam()["grade"] !== this.currentGrade) {
      this.currentExam()["grade"] = this.currentGrade;
      return true;
    } else if (this.offline) {
      const offlineCopy = this.offlineCopies.get(this.currentDocumentIndex);
      return offlineCopy !== undefined && offlineCopy.grade !== undefined;
    }
    return false;
  }

  initializeQuestionIndexes(): void {
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // check then question
    // only the questions that are corrected: an ignored question (0 page) has no copy
    const activeQuestions = (this.job.n_pages_per_question || [])
      .filter((element) => element[1] > 0)
      .map((element) => parseInt(element[0].slice(1), 10))
      .sort((a, b) => a - b)
      .map((n) => n.toString());
    this.questionIndexes = ["Tout sélectionner", ...activeQuestions];
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
      if (this.currentCopy >= 0) {
        // fetch previous exam base name. If not found, start from beginning with -1
        const previousExam = this.currentExam();
        const newExam = this.subExamsList.find((exam) => exam.basename === previousExam.basename);
        this.currentCopy = newExam ? this.examsList.indexOf(newExam) : -1;
      }
    }
    if (this.subExamsList.length > 0) {
      if (this.currentCopy < 0) {
        this.currentCopy = this.examsList.indexOf(this.subExamsList[0]);
      }
      this.currentDocumentIndex = -1;
      this.changeCurrentExam(this.currentCopy);
    }
  }

  filterExamsByQuestion(questionIndex: number): void {
    const questionString = `Q${questionIndex}`;
    this.subExamsList = this.examsList.filter(exam => exam.question === questionString);

    this.formattedIndexes = {};
    this.subExamsList.forEach((exam, i) => {
      this.formattedIndexes[exam.document_index] = `${i + 1}`;
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
    const nextIndex = this.nextCopyIndexTagFilter(-1);
    if (nextIndex < this.examsList.length) {
      this.changeCurrentExam(nextIndex);
    }
  }

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId(), true);
    this.examsList = this.docService.documentsList;
    // // sort examsList by question and then by document_index
    // this.examsList.sort((e1, e2) => {
    //   if (e1.question === e2.question) {
    //     return e1.document_index - e2.document_index;
    //   }
    //   const q1 = parseInt(e1.question.match(/\d+/)[0], 10);
    //   const q2 = parseInt(e2.question.match(/\d+/)[0], 10);
    //   return q1 - q2;
    // });
    // sort by copy number within each question
    const indexFirstExam = {};
    this.examsList.forEach((exam) => {
      if (!(exam.basename in indexFirstExam)) {
        indexFirstExam[exam.basename] = exam.document_index;
      }
    });
    this.examsList.sort((e1, e2) => {
      if (e1.basename === e2.basename) {
        return e1.document_index - e2.document_index;
      }
      return indexFirstExam[e1.basename] - indexFirstExam[e2.basename];
    });
    // initialize initialCopyIndex and currentCopy: the copy picked on the
    // dashboard wins, then the copy this page was left on, then the first
    if (this.examsList.length > 0 && this.currentCopy < 0) {
      const jobId = this.tasksService.getvalidatingTaskId();
      const selected = selectedCopyIndex(jobId, this.examsList);
      const copy = localStorage.getItem(`${jobId}_copy`);
      if (selected >= 0) {
        this.currentCopy = selected;
      } else if (copy !== null && this.examsList[parseInt(copy)]) {
        this.currentCopy = parseInt(copy);
      } else {
        this.currentCopy = 0;
      }
      this.currentDocumentIndex = this.examsList[this.currentCopy]['document_index'];
    }
  }

  setCurrentCopy(copy: number) {
    const jobId = this.tasksService.getvalidatingTaskId();
    localStorage.setItem(`${jobId}_copy`, copy.toString());
    this.currentCopy = copy;
    this.currentDocumentIndex = this.examsList[this.currentCopy]['document_index'];
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
    if (this.group) {
      const subExamsList = [];
      this.examsList.forEach((exam: any) => {
        if (exam['group'] == this.group) {
          subExamsList.push(exam);
        }
      })
      this.subExamsList = subExamsList;
    } else {
      this.subExamsList = this.examsList;
    }
  }

  loadSubExamsList(): void {
    this.getSubExamsList();
    // if any copy available
    if (this.checkForAvailableCopies()) {
      this.currentCopy = -1;
      this.currentDocumentIndex = -1;
      this.nextCopy();
    }
  }

 addGradeToQuestion(validGrade: boolean): boolean {
    if (this.currentGrade !== null) {
      if (this.currentGrade >= 0) {
        const max = this.nMaxPointsPerQuestion.get(this.currentQuestionIndex);
        if (max === undefined) {
          // a missing maximum used to disable the check silently
          this.notificationService.showWarning('Maximum de la question inconnu: la note est enregistrée sans vérification.', 'Attention!');
        } else if (this.currentGrade > max) {
          this.notificationService.showWarning(`Vous avez rajouté ${this.currentGrade - max} point(s) bonus`, 'Attention!');
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
    const exam = this.currentExam();
    if (exam && exam["status"] !== DocumentStatus.NOT_READY) {
      this.checkNavigationArrows(false);
      this.pdfLoading = true;
      let pdfSource;
      try {
        if (this.offline) {
          pdfSource = this.docService.getAvailablePdfSource(this.tasksService.getvalidatingTaskId(), this.currentDocumentIndex);
        } else {
          pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentDocumentIndex, true, version);
        }
      } finally {
        this.pdfLoading = false;  // a failed download used to leave the full-screen spinner on
      }
      if (pdfSource) {
        if (this.pdfUrl !== pdfSource.url) {
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
    const pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentDocumentIndex, false, undefined, -1);
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
    this.disablePrevious = !pdfLoaded || this.offline || (this.currentVersion === 0);
    this.disableNext = !pdfLoaded || this.offline || (this.currentVersion >= this.currentPdfSrc.lastVersion) || (this.currentVersion === undefined);
  }

  // examsList is re-sorted by student, so a server document_index is not a
  // position in it: every lookup by document index goes through here
  examByDocumentIndex(documentIndex: number) {
    return this.examsList.find(exam => exam.document_index === documentIndex);
  }

  async changeCurrentDocumentIndex(docIndex, status, updateScroll: boolean=true): Promise<void> {
    const copyIndex = this.examsList.findIndex(exam => exam.document_index === docIndex);
    await this.changeCurrentCopy(copyIndex, status, updateScroll);
  }
  async changeCurrentCopy(copyIndex, status, updateScroll: boolean=true): Promise<void> {
    if (status !== DocumentStatus.NOT_READY) {
      this.pdfLoading = true;
      if (await this.saveCurrentCopy()) {
        const exam = this.examsList[copyIndex];
        this.currentQuestionIndex = exam.question;
        this.currentCopyName = exam.basename;
        this.currentTag = exam.tag;
        this.setCurrentCopy(copyIndex);
        if (await this.loadCopy()) {
          if (updateScroll) {
            // ensure that the scroll height is updated after view update
            setTimeout(() => this.updateScrollPosition());
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
    // hide score keyboard
    document.getElementById('score')?.blur();
  }

  updateScrollPosition() {
    const e = document.getElementById('files-list-container');  // scrollTop + clientHeight = scrollHeight
    if (e) {
      const child = e.firstElementChild;
      if (child) {
        const nChildrenByRow = Math.floor(e.clientWidth / child.clientWidth);
        const nRows = Math.ceil(this.subExamsList.length / nChildrenByRow);
        const subIndex = 1 + this.subExamsList.findIndex(exam => exam.document_index === this.currentDocumentIndex);
        const currentRow = Math.ceil(subIndex / nChildrenByRow);  // start at 1
        const distanceTop = e.scrollHeight * currentRow / nRows;
        // goal is to be in the middle => clientHeight / 2
        const targetScrollTop = Math.floor(distanceTop - (e.clientHeight / 2));
        if (targetScrollTop > 0) {
          e.scrollTop = targetScrollTop;
        }
      }
    }
  }

  async changeCurrentExam(examIndex: number = this.currentCopy): Promise<void> {
    await this.changeCurrentCopy(examIndex, this.examsList[examIndex].status);
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
      const nextIndex = this.nextCopyIndex();
      if (nextIndex < this.examsList.length) {
        this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.examsList[nextIndex]['document_index']);
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
    if(status === DocumentStatus.TO_VALIDATE) {
      this.colorChosen = "red";
      if (this.availableTags.includes(tag)) {
        this.colorChosen = 'tag-color-' + tag;
      }
    }
    if(status === DocumentStatus.HIGH_ACCURACY) {
      this.colorChosen = "blue";
    }
    if(status === DocumentStatus.VALIDATED) {
      this.colorChosen = "green";
    }
  }

  checkForAvailableCopies(): boolean {
    if (this.subExamsList.length == 0) return false;
    const exam = this.subExamsList.find((exam: any) => exam["status"] != DocumentStatus.NOT_READY);
    return exam !== undefined;
  }

  getCurrentStatus() {
    this.currentStatus = this.currentExam()["status"];
  }

  setValidatedStatus(): boolean {
    if (this.currentStatus != DocumentStatus.VALIDATED) {
      this.currentStatus = DocumentStatus.VALIDATED;
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
    if (exam["tag"] !== tag) {
      this.currentTagModified = true;  // ensure that the copy will be saved
    }
    this.currentStatus = DocumentStatus.TO_VALIDATE;
    exam["tag"] = tag;
    await this.updateCurrentCopy(false);
  }

  isRespectingTagFilter(exam) {
    // default current copy
    if (this.tagFilter === '') return true;
    if (exam.status === DocumentStatus.TO_VALIDATE) {
      // default next copy to validate -> comment first line
      if (this.tagFilter === '') return true;
      if (this.tagFilter === exam.tag) return true;
      if (this.tagFilter === '0' && exam.tag === undefined) return true;
    } else if (exam.status === this.tagFilter) {
      return true;
    }
    return false;
  }

  nextCopyIndexTagFilter(currentIndex = undefined): number {
    let nextIndex = this.nextCopyIndex(currentIndex);
    while (nextIndex < this.examsList.length) {
      const exam = this.examsList[nextIndex];
      if (this.isRespectingTagFilter(exam)) break;
      nextIndex = this.nextCopyIndex(nextIndex);
    }
    return nextIndex;
  }

  async updateCurrentCopy(checkValidGrade: boolean) {
    if (!this.offline && this.hasDownloadedZip && !this.hasUploadedZip && this.currentCopy === this.examsList.length - 1) {
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
        // the status was set to VALIDATED before the grade was checked: back
        // to the stored one, or the next copy change saved VALIDATED with no grade
        this.getCurrentStatus();
        this.currentGradeModified = false;
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
      if (file !== undefined) {
        this.currentPdfSrc.annotations = this.pdfViewer.getAnnotations() || [];
        if (this.offline) {
          const copy = this.offlineCopies.get(this.currentDocumentIndex);
          copy.file64 = await PDFSource.readBlobSync(file);
          copy.status = this.currentStatus;
          if (this.currentTagModified) copy.tag = this.currentTag;
          copy.updated = false;
          if (this.currentGradeModified) {
            copy.grade = this.currentGrade;
          }
          await db.updateCopy(copy);  // a failed write used to lose the offline work silently
        } else {
          const result = await this.saveCopy(
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
    const validationResponse = await this.validationService.validateDocument(
        jobId,
        pdfSource.index,
        file,
        questionIndex,
        grade,
        this.nMaxPointsPerQuestion,
        status,
        pdfSource.version === undefined ? -1 : pdfSource.version,
        pdfSource.annotations,
        tag,
    );
    if (validationResponse === 'OK') {
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

  currentExam() {
    if (!this.examsList) {
      return undefined;
    }
    return this.examsList[this.currentCopy];
  }

  currentSubCopy() {
    const docIndex = this.currentDocumentIndex;
    return this.examsList.findIndex(exam => exam.document_index === docIndex);
  }

  async reroute() {
    if (await this.saveCurrentCopy()) {
      if (this.shareAll) {
        const queryParams = {
          job_id: this.job.job_id,
        }
        this.userService.addShareToken(queryParams);
        this.router.navigate([`/dashboard`], { queryParams });
      } else {
        this.router.navigate(['/dashboard', this.job.job_id]);
      }
    }
  }

  async previousCopy(): Promise<boolean> {
    const tempIndex = this.previousCopyIndex();
    if (tempIndex >= 0) {
      await this.changeCurrentExam(tempIndex);
      return true;
    }
    return false;
  }

  previousCopyIndex(currentIndex = undefined): number {
    let tempIndex = currentIndex !== undefined ? currentIndex : this.currentCopy;
    tempIndex--;
    while (tempIndex >= 0 && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex --;
    }
    return tempIndex;
  }

  async nextCopy(changeAnyway: boolean = false, indexFilter = () => { return this.nextCopyIndex() }): Promise<boolean> {
    // get next index according to filter
    const tempIndex = indexFilter();
    if (tempIndex < this.examsList.length) {
      await this.changeCurrentExam(tempIndex);
      return true;
    } else if (changeAnyway) {
      await this.changeCurrentExam();
    }
    return false;
  }

  nextCopyIndex(currentIndex = undefined): number {
    let tempIndex = currentIndex !== undefined ? currentIndex : this.currentCopy;
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
    return height + '%';
  }

  checkValidationButton(): void {
    // this.disabledValidationButton = !this.job || this.job["job_status"] !== 'VALIDATION';
    const disabledValidationButton = this.examsList.some((exam) => exam.status !== DocumentStatus.VALIDATED);
    const questionIndex = this.route.snapshot.queryParams.question_index;

    if (!this.disabledDropDown) {
      this.disabledValidationButton = disabledValidationButton;
    } else if (questionIndex) {
      // exact question, not a substring of the filename (Q1 matched Q10..Q19)
      const subExams = this.examsList.filter((exam) => exam.question === `Q${questionIndex}`);
      this.disabledValidationButton = subExams.some((exam) => exam.status !== DocumentStatus.VALIDATED);
    }
  }

  managePdfs() {
    const dialogRef = this.dialog.open(PdfManagementDialogComponent, {
      width: '80%',
      maxWidth: '400px',
      height: '60%',
      data: {
        jobId: this.tasksService.getvalidatingTaskId(),
        index: this.index,
        jobName: this.job.job_name,
        nPagesPerQuestion: this.job.n_pages_per_question,
        nMaxPointsPerQuestion: this.nMaxPointsPerQuestion,
        bonusEnabledMap: this.bonusEnabledMap,
        examsList: this.subExamsList,
        // the upload half works on every copy of the task: a zip may carry
        // several questions, and the server checks the right to each one it
        // finds before writing it
        allExamsList: this.examsList,
        offlineCopies: this.offlineCopies
      },
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
      if (result) {
        if (result.hasDownloadedZip) {
          this.hasDownloadedZip = true;
        } else if (result.hasUploadedZip) {
          this.hasUploadedZip = true;
          this.docService.clearPdfSources();
          await this.loadCopy();
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
        pdfSrc,
        status: exam.status,
        questionIndex: exam.question_index,
      };
      this.offlineCopies.set(pdfSrc.index, copy);
      exam.offline = true;
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
      const exam = this.examByDocumentIndex(copy.pdfSrc.index);
      if (exam === undefined) {
        this.notificationService.showError(`La copie ${copy.pdfSrc.index} ne fait plus partie de la tâche.`, 'Error');
        continue;
      }
      if (copy.file64 !== undefined && !copy.updated) {
        const cFile: File = await fetch(copy.file64).then((res) => res.blob()).then((blob) => {
          return new File([blob], exam.filename + '.pdf', { type: 'application/pdf' });
        });
        const result = await this.saveCopy(
          copy.pdfSrc,
          cFile,
          copy.grade,
          copy.status,
          copy.questionIndex);
        if (!result) {
          const index = copy.pdfSrc.index - this.subExamsList[0].document_index + 1;
          this.notificationService.showError(`La copie ${index} n'a pu être sauvegardée.`, 'Error');
          return;
        }
        copy.updated = true;
        this.notificationService.showInfo('Téléversement des copies en cours...', 'Information');
      }
      if (finalize) exam.offline = false;
    }
    this.notificationService.showSuccess('Téléversement terminé!', 'Success');
    if (finalize) await this.cleanOffline();
    this.downloadingOffline = false;
  }

  async cleanOffline() {
    for (const exam of this.subExamsList) {
      exam.offline = false;
    }
    await db.deleteAllCopies(this.offlineCopies);
    this.offline = false;
    this.downloadingOffline = false;
    await db.markOnline();
  }

  async loadOfflineCopies() {
    const allCopies = await db.getAllCopies();
    for (const copy of allCopies) {
      const exam = this.examByDocumentIndex(copy.pdfSrc.index);
      if (exam === undefined) {
        continue;  // stored for a copy that is no longer part of this task
      }
      if (copy.grade !== undefined) {
        exam.grade = copy.grade;
      }
      copy.pdfSrc = await this.docService.loadPDFSource(copy.pdfSrc, this.tasksService.getvalidatingTaskId());
      exam.offline = true;
      exam.status = copy.status;
      this.offlineCopies.set(copy.pdfSrc.index, copy);
    }
  }

  cancelOffline() {
    const dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '80%',
      maxWidth: '500px',
      height: '50%',
      data: "Êtes-vous sur de vouloir annuler la correction?"
    })
    dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
      if (result !== undefined && result === true) {
        this.notificationService.showSuccess('Correction annulée!', 'Success');
        await this.cleanOffline();
      }
    });
  }
}

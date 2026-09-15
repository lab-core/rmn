import { ChangeDetectorRef, Component, ElementRef, EventEmitter, HostListener, OnInit, Output, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SocketHandler, SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { HttpClient } from '@angular/common/http';
import { Router, ActivatedRoute } from '@angular/router';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService } from 'src/app/services/documents.service';
import { SERVER_URL } from 'src/app/utils';
import { NgxExtendedPdfViewerService } from 'ngx-extended-pdf-viewer';
import { MatSelectChange } from '@angular/material/select';
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { first } from 'rxjs/operators';
import { DocumentStatus, JobStatus } from '../../generated/rmn-contracts';
import { selectedCopyIndex } from 'src/app/selected-copy';


@Component({
    selector: 'app-matricule-verification',
    templateUrl: './matricule-verification.component.html',
    styleUrls: ['./matricule-verification.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class MatriculeVerificationComponent implements OnInit {
  readonly DocumentStatus = DocumentStatus;

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
              private ngxService: NgxExtendedPdfViewerService) {}

  pdfLoading: boolean = true;
  pdfDeleted: boolean = false;
  disabledValidationcontainer = true;
  disabledValidationButton = true;
  disabledDropDown = false;
  shareAll: boolean = false;
  horizontalValidation = true;
  preloadNCopies: number = 10;

  job: any;
  pdfUrl: string;

  initialCopyIndex: number = -1;
  currentCopy: number = -1;
  currentCopyName: string;
  currentMatricule: number;
  currentGrade: number | null;
  currentStatus: string;
  currentMatriculeSelection: string;
  currentMatriculeWarning: string;

  colorChosen: string;

  examsList: Array<any>;
  subExamsList: Array<any>;
  matriculeList: Array<any>;
  group: string;
  groupsList: Array<string> = [""];

  async ngOnInit(): Promise<any> {
    // fetch query entries
    const jobId = this.route.snapshot.queryParams['job_id'];
    if (jobId) {
      this.tasksService.setvalidatingTaskId(jobId);
    }
    this.group = this.route.snapshot.queryParams['group'] || "";
    if (this.route.snapshot.queryParams['all']) {
      this.shareAll = true;
    }

    // fetch job and documents
    this.job = await this.tasksService.getTask();
    if (!this.job || !this.job.job_id) {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche indisponible');
      this.router.navigate(['/tasks-history']);
    } else if (this.job.job_status === JobStatus.VALIDATED ||
              this.job.job_status === JobStatus.FINALIZING ||
              this.job.job_status === JobStatus.ARCHIVED) {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche active!', 'Tâche inactive');
      this.router.navigate(['/tasks-history']);
    } else {
      this.groupsList = this.job['groups'];
      if (this.groupsList.length === 0 || this.groupsList[0] !== '') {
        this.groupsList.unshift("");
      }
      this.getMatriculeList();
      await this.getDocuments();
      this.loadSubExamsList();

      this.socketService.join(this.job["job_id"]);
      this.onDocumentReady = async (params: any) => {
        await this.getDocuments();
        this.getSubExamsList();
        if (this.disabledValidationcontainer) {
          this.nextCopy();
        }
      };
      this.socketService.on('document_ready', this.onDocumentReady);

      if (this.userService.loggued()) {
        this.socketService.join(this.userService.currentUsername);
        this.onJobStatus = async (params: any) => {
          const resp = JSON.parse(params);
          const jobId = resp.job_id;
          if (this.job["job_id"] === jobId) {
            this.job["job_status"] = resp.status;
          }
        };
        this.socketService.on('job_status', this.onJobStatus);
      }
    }
  }

  private onDocumentReady: SocketHandler;
  private onJobStatus: SocketHandler;

  ngOnDestroy(): void {
    this.docService.clearPdfSources();
    // this page's handlers and rooms only: the socket stays open for the next page
    if (this.onDocumentReady) {
      this.socketService.off('document_ready', this.onDocumentReady);
    }
    if (this.onJobStatus) {
      this.socketService.off('job_status', this.onJobStatus);
    }
    if (this.job) {
      this.socketService.leave(this.job["job_id"]);
    }
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    if (!this.disabledValidationButton) {
      this.updateMatricule();
    }
  }

  // The arrow keys belong to the matricule search box while it has the
  // focus (caret in the text, option list navigation); the page-level
  // shortcuts used to fire at the same time and jump copies mid-typing.
  // Enter is left alone: selecting an option and validating with one key is
  // the intended flow.
  typingInAField(): boolean {
    const el = document.activeElement as HTMLElement | null;
    return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable
      || el.closest('.ng-select') !== null);
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  onKeydownArrowRightHandler(event: KeyboardEvent) {
    if (this.typingInAField()) {
      return;
    }
    this.nextCopy();
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  onKeydownArrowLeftHandler(event: KeyboardEvent) {
    if (this.typingInAField()) {
      return;
    }
    this.previousCopy();
  }

  @HostListener('document:keydown.arrowup', ['$event'])
  onKeydownArrowUpHandler(event: KeyboardEvent) {
    if (this.typingInAField()) {
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
    if (this.typingInAField()) {
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

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId(), false);
    this.examsList = this.docService.documentsList;
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0 && this.initialCopyIndex < 0) {
      this.initialCopyIndex = this.examsList[0].document_index;
      this.initializeCopy();
    }
    await this.updateStatusOfAllDuplicatedMatricules();
  }

  initializeCopy() {
    const jobId = this.tasksService.getvalidatingTaskId();
    // the copy picked on the dashboard wins, then the copy this page was left
    // on (its own key: the correction page counts differently), then the first
    const selected = selectedCopyIndex(jobId, this.examsList);
    const sCopy = localStorage.getItem(`${jobId}_matricule_copy`);
    if (selected >= 0) {
      this.currentCopy = selected + this.initialCopyIndex;
    } else if (sCopy != undefined) {
      const copy = parseInt(sCopy);
      this.currentCopy = copy % this.examsList.length + this.initialCopyIndex;
    } else {
      this.currentCopy = this.initialCopyIndex;
    }
  }

  setCurrentCopy(copy: number) {
    const jobId = this.tasksService.getvalidatingTaskId();
    this.currentCopy = copy;
    copy -= this.initialCopyIndex;
    localStorage.setItem(`${jobId}_matricule_copy`, copy.toString());
  }

  getSubExamsList(): void {
    if (this.group) {
      const subExamsList = [];
      this.examsList.forEach((exam: any) => {
        if (exam['group'] == this.group) {
          subExamsList.push(exam);
        }
      });
      this.subExamsList = subExamsList;
    } else {
      this.subExamsList = this.examsList;
    }
  }

  loadSubExamsList(): void {
    this.getSubExamsList();
    // if any copy available
    if (this.checkForAvailableCopies()) {
      this.currentCopy -= 1;
      this.nextCopy();
    } else {
      this.disabledValidationcontainer = true;
    }
  }

  async loadPdf(version: number = undefined): Promise<void> {
    const exam = this.currentExam();
    if (exam && exam["status"] !== DocumentStatus.NOT_READY) {
      this.pdfLoadStarts();
      try {
        const pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, false);
        if (pdfSource?.url) {
          this.pdfUrl = pdfSource.url;
        }
      } finally {
        this.pdfLoadEnds();  // a failed download used to leave the spinner on
      }
    }
  }

  async changeCurrentCopy(copyIndex: number, status: string, updateScroll: boolean=true) {
    const exam = this.examsList[copyIndex-this.initialCopyIndex];
    if (exam && status !== DocumentStatus.NOT_READY) {
        this.currentCopyName = exam.filename;
        this.setCurrentCopy(copyIndex);
        this.disabledValidationcontainer = false;
        await this.loadCopy();
        this.setChosenColor(status);
        if (updateScroll) {
          this.updateScrollPosition();
        }
    }
  }

  updateScrollPosition() {
    const e = document.getElementById('files-list-container');  // scrollTop + clientHeight = scrollHeight
    if (e && e.firstElementChild) {
      const child = e.firstElementChild;
      const r = e.clientWidth / child.clientWidth;
      const nChildrenByRow = Math.floor(e.clientWidth / child.clientWidth);
      const nRows = Math.ceil(this.subExamsList.length / nChildrenByRow);
      const subIndex = 1 + this.subExamsList.findIndex(exam => exam.document_index === this.currentCopy);
      const currentRow = Math.ceil(subIndex / nChildrenByRow);  // start at 1
      const distanceTop = e.scrollHeight * currentRow / nRows;
      // goal is to be in the middle => clientHeight / 2
      const targetScrollTop = Math.floor(distanceTop - (e.clientHeight / 2));
      if (targetScrollTop > 0) {
        e.scrollTop = targetScrollTop;
      }
    }
  }

  changeCurrentExam(examIndex: number) {
    const exam = this.examsList[examIndex];
    if (exam) {
      this.changeCurrentCopy(exam.document_index, exam.status);
    }
  }

  async loadCopy(): Promise<void> {
    await this.loadPdf();
    this.getCurrentMatricule();
    this.getCurrentStatus();
    // try to load the following copy
    let nextIndex = this.nextCopyIndex();
    let i = 0;
    while (i < this.preloadNCopies && nextIndex < this.examsList.length) {
      this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.initialCopyIndex + nextIndex, false);
      nextIndex = this.nextCopyIndex(nextIndex);
      i++;
    }
  }

  setChosenColor(status: string): void {
    if(status === DocumentStatus.TO_VALIDATE) {
      this.colorChosen = "red";
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
    return exam != undefined;
  }

  getMatriculeList() {
    let tempList = this.job["students_list"];
    tempList = tempList.map(x => {
      x = { matricule: x['matricule'], nom: x['Nom complet'], identifiant: x['matricule'] + ' - ' + x["Nom complet"] }; return x;
    });
    this.matriculeList = tempList;
  }

  currentExam() {
    return this.examsList[this.currentIndex()];
  }

  currentIndex(): number {
    return this.currentCopy - this.initialCopyIndex;
  }

  getCurrentMatricule() {
    const currentExam = this.currentExam();
    if (currentExam && currentExam["status"] !== DocumentStatus.NOT_READY && currentExam["status"] !== DocumentStatus.DELETED) {
      this.currentMatricule = currentExam["matricule"];
      this.getDuplicatedMatricules();
      const matriculeRow = this.matriculeList.find(
        x => x['matricule'] === String(this.currentMatricule)
      );
      if (matriculeRow) {
        this.currentMatriculeSelection = matriculeRow['identifiant'];
      } else {
        this.currentMatriculeSelection = undefined;
      }
    } else {
      this.currentMatriculeSelection = undefined;
    }
  }

  getCurrentStatus() {
    const currentExam = this.currentExam();
    if (currentExam) {
      this.currentStatus = currentExam["status"];
    } else {
      console.error("Document not found for index:", this.currentCopy);
    }
  }

  setValidatedStatus() {
    const currentExam = this.currentExam();
    if (currentExam) {
        currentExam.status = DocumentStatus.VALIDATED;
    } else {
        console.error("Document not found for index:", this.currentCopy);
    }
  }

  async updateMatricule(): Promise<string> {
    if (!this.currentMatriculeSelection) {
      this.notificationService.showWarning('Veuillez fournir un matricule!', 'Matricule manquante');
      return;
    }
    this.getCurrentMatricule();
    await this.updateStatusOfAllDuplicatedMatricules(this.currentMatricule);
    this.pdfLoadStarts();
    const formdata: FormData = new FormData();
    formdata.append('job_id', this.job.job_id);
    formdata.append('document_index', this.currentCopy.toString());
    formdata.append('matricule', this.currentMatricule.toString());
    this.userService.addTokens(formdata);
    try {
      const response = await this.http.post(`${SERVER_URL}matricule/update`, formdata).toPromise();
      if (response['response'] === 'OK') {
        this.setValidatedStatus();
        this.nextCopy(true);
      }
    } catch (error) {
      console.error('Erreur lors de la mise à jour du matricule:', error);
      this.notificationService.showError('Erreur lors de la mise à jour du matricule.', 'Erreur de validation');
    }
    this.pdfLoadEnds();
  }

  pdfLoadStarts() {
    this.pdfLoading = true;
    this.disabledValidationButton = true;
  }

  pdfLoadEnds() {
    this.pdfLoading = false;
    if (this.currentExam().status == DocumentStatus.DELETED) {
      this.disabledValidationButton = true;
      this.pdfDeleted = true;
    } else {
      this.disabledValidationButton = false;
      this.pdfDeleted = false;
    }
  }

  async validateMatricules() {
    let uncheckedcopy = 0;
    this.examsList.forEach((exam: any) => {
      if (exam["status"] === DocumentStatus.TO_VALIDATE) {
        uncheckedcopy += 1;
      }
    });

    if (uncheckedcopy > 0) {
      this.openwarningDialog();
    } else if (!this.hasQuestionsToGrade()) {
      // matricules were the only thing to check: finalize, as the
      // confirmation dialog does. This branch used to navigate away with a
      // success toast and no request, leaving the task in VALIDATION.
      await this.finalizeJob();
    } else {
      // every matricule is saved already; grading comes next
      this.disabledValidationcontainer = true;
      this.pdfLoadEnds();
      this.router.navigate(['/tasks-history']);
      const message = "Les matricules ont été validés avec succès!";
      this.notificationService.showInfo(message, "Alerte!")
    }
  }

  hasQuestionsToGrade(): boolean {
    return (this.job?.n_max_points_per_question ?? []).length > 0;
  }

  async finalizeJob(): Promise<void> {
    this.disabledValidationcontainer = true;
    this.pdfLoadStarts();
    const response = await this.validationService.validateJob(
      this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
    if (response === 'OK') {
      this.router.navigate(['/tasks-history']);
      this.notificationService.showInfo('La tâche est en cours de finalisation!', 'Alerte!');
    } else {
      this.pdfLoadEnds();
      this.disabledValidationcontainer = false;
    }
  }

  async deletePdf(): Promise<void> {
    this.pdfDeleted = true;
    this.disabledValidationButton = true;
    await this.updateExamStatus(DocumentStatus.DELETED);
    this.nextCopy();
  }

  restorePdf(): void {
    this.pdfDeleted = false;
    this.disabledValidationButton = false;
    this.updateExamStatus(DocumentStatus.TO_VALIDATE);
  }

  async updateExamStatus(examStatus, copy = this.currentCopy) {
    const formdata: FormData = new FormData();
    formdata.append('job_id', this.job.job_id);
    formdata.append('document_index', copy.toString());
    formdata.append('status', examStatus);
    this.userService.addTokens(formdata);
    try {
      await this.http.post(`${SERVER_URL}matricule/status/update`, formdata).toPromise();
      if (copy === this.currentCopy) {
        this.currentExam().status = examStatus;
        this.getCurrentMatricule();
      }
    } catch (error) {
      console.error('Erreur lors de la mise à jour du status:', error);
      this.notificationService.showError('Erreur lors de la mise à jour du status.', 'Erreur de validation');
    }
  }

  openwarningDialog(): void {
    const dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '80%',
      maxWidth: '400px',
      height: '40%',
      data: "Êtes-vous sûr de vouloir finaliser même si toutes les copies n'ont pas été validées ?"
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
        if (result !== undefined && result === true) {
          await this.finalizeJob();
        }

      }, (error) => {
        console.error(error);

      });
  }

  changeMatricule(selection): void {
    this.currentMatricule = Number(selection.matricule);
    // currentCopy is a document index; the list position is currentIndex()
    const exam = this.currentExam();
    if (exam) {
      exam.matricule = String(this.currentMatricule);
    }
    this.getDuplicatedMatricules();
  }

  getDuplicatedMatricules(): void {
    // search for duplicated matricules
    const mat = String(this.currentMatricule);
    let counter = 0;
    let warning = '';
    this.examsList.forEach((exam: any) => {
      if (exam.status !== DocumentStatus.DELETED &&
          exam.status !== DocumentStatus.NOT_READY &&
          exam.matricule === mat &&
          exam.document_index !== this.currentCopy) {
        if (counter < 3) {
          if (counter > 0) {
            warning += ', ';
          }
          warning += exam.document_index - this.initialCopyIndex + 1;
        } else if (counter === 3) {
          warning += ' ..';
        }
        counter += 1;
      }
    });
    // update warning message for matricule
    if (counter === 0) {
      this.currentMatriculeWarning = undefined;
    } else {
      this.currentMatriculeWarning = warning;
    }
  }

  async updateStatusOfAllDuplicatedMatricules(matricule = undefined): Promise<void> {
    // exams carry the matricule as a string, callers may pass a number
    const wanted = matricule === undefined || matricule === null ? undefined : String(matricule);
    const matricules = new Map<string, Array<any>>();
    this.examsList.forEach((exam: any) => {
      if (exam.status !== DocumentStatus.DELETED &&
        exam.status !== DocumentStatus.NOT_READY &&
        (!wanted || String(exam.matricule) === wanted)) {
        if (!matricules[exam.matricule]) {
          matricules[exam.matricule] = [];
        }
        matricules[exam.matricule].push(exam);
      }
    });

    for (const exams of Object.values(matricules)) {
      if (exams.length > 1) {
        for (const exam of exams) {
          if (exam.status !== DocumentStatus.TO_VALIDATE) {
            exam.status = DocumentStatus.TO_VALIDATE;
            await this.updateExamStatus(exam.status, exam.document_index);
          }
        }
      }
    }
  }

  reroute() {
    if (this.shareAll) {
      const queryParams = {
        job_id: this.job["job_id"],
      }
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/dashboard`], { queryParams: queryParams });
    } else {
      this.router.navigate(['/dashboard', this.job["job_id"]]);
    }
  }

  previousCopy(): void {
    const tempIndex = this.previousCopyIndex();
    if (tempIndex >= 0) {
      this.changeCurrentExam(tempIndex);
    }
  }

  previousCopyIndex(currentIndex = undefined): number {
    let tempIndex = currentIndex != undefined ? currentIndex : this.currentIndex();
    tempIndex--;
    while (tempIndex >= 0 && (!this.subExamsList.includes(this.examsList[tempIndex]) || this.examsList[tempIndex].status == DocumentStatus.NOT_READY)) {
      tempIndex --;
    }
    return tempIndex;
  }

  nextCopy(notValidated: boolean = false): void {
    const tempIndex = this.nextCopyIndex(this.currentIndex(), notValidated);
    if (tempIndex < this.examsList.length) {
      this.changeCurrentExam(tempIndex);
    }
  }

  nextCopyIndex(currentIndex: number = this.currentIndex(), notValidated: boolean = false): number {
    currentIndex++;
    while (currentIndex < this.examsList.length && (
      !this.subExamsList.includes(this.examsList[currentIndex])
      || this.examsList[currentIndex].status === DocumentStatus.NOT_READY
      || (notValidated && this.examsList[currentIndex].status === DocumentStatus.VALIDATED)
    )) {
      currentIndex++;
    }
    return currentIndex;
  }

  loggued(): boolean {
    return this.userService.loggued();
  }

  showFilter(): boolean {
    return (this.loggued() || this.shareAll) && this.groupsList.length > 1;
  }

  filesListHeight(): string {
    let height = 80;
    if (!this.userService.shared()) height += 10;
    if (!this.showFilter()) height += 10;
    return height + "%";
  }
}

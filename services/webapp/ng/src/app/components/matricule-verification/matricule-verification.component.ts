import { ChangeDetectorRef, Component, ElementRef, EventEmitter, HostListener, OnInit, Output, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TasksService } from 'src/app/services/tasks.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SocketService } from 'src/app/services/socket.service';
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


@Component({
  selector: 'app-matricule-verification',
  templateUrl: './matricule-verification.component.html',
  styleUrls: ['./matricule-verification.component.css']
})
export class MatriculeVerificationComponent implements OnInit {

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
  currentTotal: number;
  currentGrades: Map<string, number>;
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
    } else if (this.job.job_status === 'VALIDATED' ||
              this.job.job_status === 'FINALIZING' ||
              this.job.job_status === 'ARCHIVED') {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche active!', 'Tâche inactive');
      this.router.navigate(['/tasks-history']);
    } else {
      this.groupsList = this.job['groups'];
      if (this.groupsList[0] !== '') {
        this.groupsList.unshift("");
      }
      this.getMatriculeList();
      await this.getDocuments();
      this.loadSubExamsList();

      this.socketService.join(this.job["job_id"]);
      this.socketService.getSocket().on('document_ready', async (params: any) => {
        await this.getDocuments();
        this.getSubExamsList();
        if (this.disabledValidationcontainer) {
          this.nextCopy();
        }
      });

      if (this.userService.loggued()) {
        this.socketService.join(this.userService.currentUsername);
        this.socketService.getSocket().on('job_status', async (params: any) => {
          const resp = JSON.parse(params);
          const jobId = resp.job_id;
          if (this.job["job_id"] === jobId) {
            this.job["job_status"] = resp.status;
          }
        });
      }
    }
  }


  ngOnDestroy(): void {
    this.docService.clearPdfSources();
    if (this.socketService.getSocket()){
      this.socketService.getSocket().off('document_ready');
      this.socketService.getSocket().off('job_status');
      this.socketService.disconnectSocket();
    }
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    if (!this.disabledValidationButton) {
      this.updateMatricule();
    }
  }

  @HostListener('document:keydown.arrowright', ['$event'])
  onKeydownArrowRightHandler(event: KeyboardEvent) {
    this.nextCopy();
  }

  @HostListener('document:keydown.arrowleft', ['$event'])
  onKeydownArrowLeftHandler(event: KeyboardEvent) {
    this.previousCopy();
  }

  @HostListener('document:keydown.arrowup', ['$event'])
  onKeydownArrowUpHandler(event: KeyboardEvent) {
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
    const sCopy = localStorage.getItem(`${this.tasksService.getvalidatingTaskId()}_copy`);
    if (sCopy != undefined) {
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
    localStorage.setItem(`${jobId}_copy`, copy.toString());
  }

  getSubExamsList(): void {
    console.log("group", this.group);
    if (this.group) {
      const subExamsList = [];
      this.examsList.forEach((exam: any) => {
        if (exam['group'] == this.group) {
          subExamsList.push(exam);
        }
      });
      this.subExamsList = subExamsList;
      console.log("sub exam list size for group", this.group, subExamsList.length, "/", this.examsList.length);
    } else {
      console.log("sub exam list is the full list of size", this.examsList.length);
      this.subExamsList = this.examsList;
    }
  }

  loadSubExamsList(): void {
    this.getSubExamsList();
    console.log("Group:", this.group, this.subExamsList.length, "exams");
    // if any copy available
    if (this.checkForAvailableCopies()) {
      this.currentCopy -= 1;
      this.nextCopy();
    } else {
      this.disabledValidationcontainer = true;
    }
  }

  async loadPdf(version: number = undefined): Promise<void> {
    if (this.currentExam()["status"] !== "NOT_READY") {
      this.pdfLoadStarts();
      const pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy, false);
      if (pdfSource.url) {
        this.pdfUrl = pdfSource.url;
      }
      this.pdfLoadEnds();
    }
  }

  async changeCurrentCopy(copyIndex: number, status: string, updateScroll: boolean=true) {
    if (status !== "NOT_READY") {
        const exam = this.examsList[copyIndex-this.initialCopyIndex];
        console.log("Change current copy to", copyIndex);
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
    const exam = this.subExamsList.find((exam: any) => exam["status"] != "NOT_READY");
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
    if (currentExam && currentExam["status"] !== "NOT_READY" && currentExam["status"] !== "DELETED") {
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
        currentExam.status = "VALIDATED";
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
    if (this.currentExam().status == 'DELETED') {
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
      if (exam["status"] === "TO VALIDATE") {
        uncheckedcopy += 1;
      }
    });

    if (uncheckedcopy > 0) {
      this.openwarningDialog();
    } else {
      this.disabledValidationcontainer = true;
      this.pdfLoadEnds();
      this.router.navigate(['/tasks-history']);
      const message = "Les matricules ont été validés avec succès!";
      this.notificationService.showInfo(message, "Alerte!")
      // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());
    }
  }

  async deletePdf(): Promise<void> {
    this.pdfDeleted = true;
    this.disabledValidationButton = true;
    await this.updateExamStatus('DELETED');
    this.nextCopy();
  }

  restorePdf(): void {
    this.pdfDeleted = false;
    this.disabledValidationButton = false;
    this.updateExamStatus('TO VALIDATE');
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
          this.disabledValidationcontainer = true;
          this.pdfLoadStarts();
          const response = await this.validationService.validateJob(
            this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
          if (response === 'OK') {
            this.router.navigate(['/tasks-history']);
            const message = 'La tâche est en cours de finalisation!';
            this.notificationService.showInfo(message, 'Alerte!');
            // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());
          }
        }

      }, (error) => {
        console.error(error);

      });
  }

  changeMatricule(selection): void {
    this.currentMatricule = Number(selection.matricule);
    const exam = this.examsList[this.currentCopy];
    exam.matricule = String(this.currentMatricule);
    this.getDuplicatedMatricules();
  }

  getDuplicatedMatricules(): void {
    // search for duplicated matricules
    const mat = String(this.currentMatricule);
    let counter = 0;
    let warning = '';
    this.examsList.forEach((exam: any) => {
      if (exam.status !== 'DELETED' &&
          exam.status !== 'NOT_READY' &&
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
    const matricules = new Map<string, Array<any>>();
    this.examsList.forEach((exam: any) => {
      if (exam.status !== 'DELETED' &&
        exam.status !== 'NOT_READY' &&
        (!matricule || exam.matricule === matricule)) {
        if (!matricules[exam.matricule]) {
          matricules[exam.matricule] = [];
        }
        matricules[exam.matricule].push(exam);
      }
    });

    for (const exams of Object.values(matricules)) {
      if (exams.length > 1) {
        for (const exam of exams) {
          if (exam.status !== 'TO VALIDATE') {
            exam.status = 'TO VALIDATE';
            await this.updateExamStatus(exam.status, exam.document_index);
          }
        }
      }
    }
  }

  updateTotal(gradeKey, gradeValue): void {
    this.currentGrades[gradeKey] = gradeValue;
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
    while (tempIndex >= 0 && (!this.subExamsList.includes(this.examsList[tempIndex]) || this.examsList[tempIndex].status == "NOT_READY")) {
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
      || this.examsList[currentIndex].status === "NOT_READY"
      || (notValidated && this.examsList[currentIndex].status === "VALIDATED")
    )) {
      currentIndex++;
    }
    return currentIndex;
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
    return height + "%";
  }
}

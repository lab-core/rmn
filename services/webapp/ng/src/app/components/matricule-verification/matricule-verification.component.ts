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
import { ValidationWarningDialogComponent } from '../task-verification/validation-warning-dialog/validation-warning-dialog.component';

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

  pictureLoading: boolean = true;
  pdfLoading: boolean = true;
  disabledValidationcontainer = true;
  disabledValidationButton = true;
  disabledDropDown = false;

  validating: boolean = false;

  job: Map<string, any>;
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
    let jobId = this.route.snapshot.queryParams['job_id'];
    if (jobId) {
      this.tasksService.setvalidatingTaskId(jobId);
    }
    this.group = this.route.snapshot.queryParams['group'] || "";

    // fetch job and documents
    this.job = await this.tasksService.getTask();
    if (this.job && this.job["job_id"]) {
      this.groupsList = this.job['groups'];
      this.groupsList.unshift("");
      this.getMatriculeList();
      await this.getDocuments();
      this.getSubExamsList();
      this.nextCopy();
      this.checkValidationButton();

      this.socketService.join(this.job["job_id"]);
      this.socketService.getSocket().on('document_ready', async (params: any) => {
        await this.getDocuments();
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
            this.checkValidationButton();
          }
        });
      }
    } else {
      // reroute page
      this.notificationService.showWarning('Veuillez sélectionner une tâche valide!', 'Tâche non disponible');
      this.router.navigate(['/tasks-history']);
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
    this.updateMatricule();
  }

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId(), false);
    this.examsList = this.docService.documentsList;
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0 && this.initialCopyIndex < 0) {
      this.initialCopyIndex = this.examsList[0].document_index;
      this.currentCopy = this.initialCopyIndex - 1;
    }
  }

  getSubExamsList(): void {
    console.log("group", this.group);
    if (this.group) {
      let subExamsList = [];
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
      this.currentCopy = this.initialCopyIndex - 1;
      this.nextCopy();
    } else {
      this.disabledValidationcontainer = true;
    }
  }

  async loadPdf(version: number = undefined): Promise<void> {
    if (this.currentExam()["status"] !== "NOT_READY") {
      this.pdfLoading = true;
      const pdfSource = await this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), this.currentCopy);
      if (pdfSource.url) {
        this.pdfUrl = pdfSource.url;
        // this.pdfModified = false;
        // // initialize pdf viewer options
        // if (!this.pdfViewerInitialized)
        //  setTimeout(() => { this.initializePdfViewer(); }, 1000);
        // console.log("Current Exam: ", this.examsList[this.currentIndex()])
      }
      this.pdfLoading = false;
    }
  }

  async changeCurrentCopy(copyIndex: number, status: string, updateScroll: boolean=true) {
    if (status !== "NOT_READY") {
        let exam = this.examsList[copyIndex-this.initialCopyIndex];
        console.log("Change current copy to", copyIndex);
        this.currentCopyName = exam.filename;
        this.currentCopy = copyIndex;
        console.log("Current copy", this.currentCopy);
        this.disabledValidationcontainer = false;
        await this.loadCopy();
        this.setChosenColor(status);
        if (updateScroll) {
          this.updateScrollPosition();
        }
    }
  }

  updateScrollPosition() {
    let e = document.getElementById('files-list-container');  // scrollTop + clientHeight = scrollHeight
    if (e) {
      let child = e.firstElementChild;
      let r = e.clientWidth / child.clientWidth;
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
    if (nextIndex < this.examsList.length) {
      this.docService.getPdfSource(this.tasksService.getvalidatingTaskId(), nextIndex);
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
    if (currentExam && currentExam["status"] !== "NOT_READY") {
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
    const formdata: FormData = new FormData();
    formdata.append('job_id', this.job["job_id"]);
    formdata.append('document_index', this.currentCopy.toString());
    this.getCurrentMatricule();
    formdata.append('matricule', this.currentMatricule.toString());
    this.userService.addTokens(formdata);

    try {
      const response = await this.http.post(`${SERVER_URL}matricule/update`, formdata).toPromise();
      if (response["response"] === "OK") {
        this.setValidatedStatus();
        this.nextCopy();
      }
      this.checkValidationButton();
      return response["response"];
    } catch (error) {
      console.error('Erreur lors de la mise à jour du matricule :', error);
      this.notificationService.showError('Erreur lors de la mise à jour du matricule.', 'Erreur de validation');
      return 'Error';
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
      this.validating = true;
      this.router.navigate(['/tasks-history']);
      let message = "Les matricules ont été validés avec succès!";
      this.notificationService.showInfo(message, "Alerte!")
      // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());

    }
  }

  openwarningDialog(): void {
    let dialogRef = this.dialog.open(ValidationWarningDialogComponent, {
      width: '30%',
      height: '40%',
    });
    dialogRef.afterClosed().subscribe(async result => {
        if (result !== undefined && result === true) {
          this.disabledValidationcontainer = true;
          this.validating = true;
          let response = await this.validationService.validateJob(
            this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
          if (response === "OK") {
            this.router.navigate(['/tasks-history']);
            const message = "La tâche est en cours de finalisation!";
            this.notificationService.showInfo(message, "Alerte!")
            // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());
          }
        }
      }, (error) => {
        console.error(error);
      });
  }

  changeMatricule(selection): void {
    this.currentMatricule = Number(selection.matricule);
    let exam = this.examsList[this.currentCopy];
    exam["matricule"] = String(this.currentMatricule);
    this.getDuplicatedMatricules();
  }

  getDuplicatedMatricules(): void {
    // search for duplicated matricules
    let mat = String(this.currentMatricule);
    let counter = 0;
    let warning = "";
    this.examsList.forEach((exam: any) => {
      if (exam["matricule"] === mat && exam["document_index"] !== this.currentCopy) {
        if (counter < 3) {
          if (counter > 0) {
            warning += ", ";
          }
          warning += exam["document_index"];
        } else if (counter == 3) {
          warning += " ..";
        }
        counter += 1;
      }
    });
    // update warning message for matricule
    if (counter == 0) {
      this.currentMatriculeWarning = undefined;
    } else {
      this.currentMatriculeWarning = warning;
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
    this.router.navigate(['/dashboard', this.job["job_id"]]);
  }

  previousCopy(): void {
    let tempIndex = this.currentIndex() - 1;
    while (tempIndex >= 0 && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex --;
    }
    console.log("Previous copy", tempIndex)
    if (tempIndex >= 0) {
      this.changeCurrentExam(tempIndex);
    }
  }

  nextCopy(): void {
    let tempIndex = this.nextCopyIndex();
    console.log("Next copy", tempIndex)
    if (tempIndex < this.examsList.length) {
      this.changeCurrentExam(tempIndex);
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
    return height + "%";
  }

  checkValidationButton(): void {
    const disabledValidationButton = this.examsList.some(exam => exam.status !== 'VALIDATED');
    if (!this.disabledDropDown) {
      this.disabledValidationButton = disabledValidationButton;
    }
  }
}

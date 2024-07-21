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
  pdfSrc: string;

  copiesInformations: Map<string, Map<string, number>> = new Map();
  initialCopyIndex: number = 0;
  currentCopy: number = 0;
  currentCopyName: string;
  currentQuestionIndex: string;
  currentMatricule: number;
  currentScore: number | null;
  currentTotal: number;
  currentPredictions: Map<string, number>;
  currentStatus: string;
  currentMatriculeSelection: string;
  currentMatriculeWarning: string;

  colorChosen: string;

  examsList: Array<any>;
  subExamsList: Array<number>;
  matriculeList: Array<any>;
  group: string;
  groupsList: Array<string>;

  async ngOnInit(): Promise<any> {
    // fetch query entries
    let token = this.route.snapshot.queryParams['token'];
    if (token) {
      this.userService.setShareToken(token);
    }
    let jobId = this.route.snapshot.queryParams['job'];
    if (jobId) {
      this.tasksService.setvalidatingTaskId(jobId);
    }
    this.group = this.route.snapshot.queryParams['group'];
    if (this.group == null) {
      this.group = "";
    }
    this.groupsList = [this.group];
    // fetch job and documents
    this.job = await this.tasksService.getTask();
    if (this.job && this.job["job_id"]) {
      this.getMatriculeList();
      await this.getDocuments();
      this.getSubExamsList();
      if (this.checkForAvailableCopies()) {
        this.initialCopyIndex = 0;
        this.currentCopy = this.initialCopyIndex;
        this.changeCurrentExam(this.currentCopy);
      }
      this.checkValidationButton();

      this.socketService.join(this.job["job_id"]);
      this.socketService.getSocket().on('document_ready', async (params: any) => {
        await this.getDocuments();
        if (this.disabledValidationcontainer) {
          this.nextCopy();
        }
      });

      if (this.userService.token) {
        this.socketService.join(this.userService.currentUsername);
        this.socketService.getSocket().on('jobs_status', async (params: any) => {
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
    this.checkValidationButton();
  }


  ngOnDestroy(): void {
    this.socketService.getSocket().off('document_ready');
    this.socketService.getSocket().off('jobs_status');
    this.socketService.disconnectSocket();
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    this.updateMatricule();
  }

  async getDocuments() {
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId());
    this.examsList = this.docService.coversList;
    this.groupsList = this.docService.groupsList;
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0) {
      this.initialCopyIndex = 0;
      this.currentCopy = this.initialCopyIndex;
    }
  }

  async getCopiesInformations() {
    let exam = this.examsList[this.currentIndex()];
    this.currentCopyName = exam["filename"];
    await this.docService.getJobInfos(this.tasksService.getvalidatingTaskId());
    this.copiesInformations = this.docService.copiesInformations;
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
      this.currentCopy = this.initialCopyIndex;
      this.nextCopy();
    } else {
      this.disabledValidationcontainer = true;
    }
  }

  loadPdf(): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.tasksService.getvalidatingTaskId());
    formdata.append('document_index', this.examsList[this.currentCopy].document_index);

    this.pdfLoading = true;

    // find the document in examsList based on the filename (currentIndex)
    const currentFilename = this.currentIndex();
    const currentExam = this.examsList.find((exam: any) => exam.filename === currentFilename);
    console.log("Current Exam: ", currentExam);

    if (currentExam && currentExam.status !== "NOT_READY") {
      this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).subscribe(
        (data) => {
          let url = window.URL.createObjectURL(data);
          this.pdfSrc = url;
          this.pdfLoading = false;
          console.log("PDF loaded successfully for: ", currentFilename);
        }, (error) => {
          console.error(error);
          this.pdfLoading = false;
        });
    } else {
      this.pdfLoading = false;
      if (!currentExam) {
        console.error("Document not found for filename:", currentFilename);
      }
    }
  }

  changeCurrentCopy(copyIndex: string, status: string) {
    if (status !== "NOT_READY") {
        let exam = this.examsList.find((e) => e.document_index === copyIndex);
        console.log("Change current copy to", copyIndex);
        this.currentQuestionIndex = this.getQuestionIndex(copyIndex);
        this.currentCopyName = exam.filename;
        this.currentCopy = this.examsList.indexOf(exam);
        console.log("Current copy", this.currentCopy);
        this.disabledValidationcontainer = false;
        this.loadCopy();
        this.setChosenColor(status);
    }
  }

  changeCurrentExam(examIndex: number) {
    const exam = this.examsList[examIndex];
    if (exam) {
      this.changeCurrentCopy(exam.document_index, exam.status);
    }
  }

  getExamIndex(exam: any): number {
    return this.subExamsList.indexOf(exam) + 1;
  }

  loadCopy(): void {
    this.loadPdf();
    this.getCurrentMatricule();
    this.getCurrentStatus();
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

  getQuestionIndex(filename: string): string {
    const baseName = filename.substring(0, filename.lastIndexOf('.'));
    const underscoreIndex = baseName.lastIndexOf('_');
    const result = baseName.substring(underscoreIndex + 1);
    return result;
  }

  getBaseNameWithExtension(filename: string): string {
    const underscoreIndex = filename.lastIndexOf('_');
    const baseNameWithExtension = filename.substring(0, underscoreIndex) + filename.substring(filename.lastIndexOf('.'));
    return baseNameWithExtension;
  }

  checkForAvailableCopies(): boolean {
    if (this.subExamsList.length == 0) return false;
    let exam = this.subExamsList.find((exam: any) => exam["status"] != "NOT_READY");
    console.log("Found ready exam", exam);
    return exam != undefined;
  }

  getMatriculeList() {
    let tempList = JSON.parse(this.job["students_list"]);
    tempList = tempList.map(x => {
      x = { matricule: x['matricule'], nom: x['Nom complet'], identifiant: x['matricule'] + ' - ' + x["Nom complet"] }; return x;
    });
    this.matriculeList = tempList;
  }

  getCurrentMatricule() {
    const currentFilename = this.currentIndex();
    const currentExam = this.examsList.find((exam: any) => exam.filename === currentFilename);
    if (currentExam && currentExam["status"] !== "NOT_READY") {
      this.currentMatricule = currentExam["matricule"];
      this.getDuplicatedMatricule();
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
    const currentFilename = this.currentIndex();
    const currentExam = this.examsList.find((exam: any) => exam.filename === currentFilename);
    if (currentExam) {
      this.currentStatus = currentExam["status"];
    } else {
      console.error("Document not found for filename:", currentFilename);
    }
  }

  setValidatedStatus() {
    const currentFilename = this.currentIndex();
    const currentExam = this.examsList.find((exam: any) => exam.filename === currentFilename);

    if (currentExam) {
        currentExam.status = "VALIDATED";
    } else {
        console.error("Document not found for filename:", currentFilename);
    }
  }

  async updateMatricule(): Promise<string> {
    if (!this.currentMatriculeSelection) {
      this.notificationService.showWarning('Veuillez fournir un matricule!', 'Matricule manquante');
      return;
    }
    this.getCurrentMatricule();
    const formdata: FormData = new FormData();
    formdata.append('job_id', this.job["job_id"]);
    formdata.append('document_index', this.currentIndex());
    this.getCurrentMatricule();
    formdata.append('matricule', this.currentMatricule.toString());
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);

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
    exam["total"] = this.currentTotal;
    exam["matricule"] = String(this.currentMatricule);
    this.getDuplicatedMatricule();
  }

  getDuplicatedMatricule(): void {
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

  updateTotal(predictionKey, predictionValue): void {
    this.currentPredictions[predictionKey] = predictionValue;
    this.currentTotal = this.getTotal();
  }

  getTotal(): number {
    let sum = 0;
    for (const prediction of Object.keys(this.currentPredictions)) {
      sum += this.currentPredictions[prediction];
    }
    return sum;
  }

  trackByIndex(index, _): number {
    return index;
  }

  currentIndex(): string {
    if (this.examsList && this.examsList[this.currentCopy]) {
      return this.examsList[this.currentCopy].filename;
    }
    return '';
  }

  reroute() {
    this.router.navigate(['/dashboard', this.job["job_id"]]);
  }

  previousCopy(): void {
    let tempIndex = this.currentCopy - 1;
    while (tempIndex >= 0 && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex--;
    }
    console.log("Previous copy", tempIndex);
    if (tempIndex >= 0) {
      this.changeCurrentExam(tempIndex);
    }
  }

  nextCopy(): void {
    let tempIndex = this.nextCopyIndex();
    console.log("Next copy", tempIndex);
    if (tempIndex < this.examsList.length) {
      this.changeCurrentExam(tempIndex);
    }
  }

  nextCopyIndex(): number {
    let tempIndex = this.currentCopy + 1;
    while (tempIndex < this.examsList.length && !this.subExamsList.includes(this.examsList[tempIndex])) {
      tempIndex++;
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
    const questionIndex = this.route.snapshot.queryParams['question_index'];

    if (!this.disabledDropDown) {
      this.disabledValidationButton = disabledValidationButton;
    } else if (questionIndex) {
      const subExams = this.examsList.filter(exam => exam.filename.includes(`Q${questionIndex}`));
      this.disabledValidationButton = subExams.some(exam => exam["status"] !== 'VALIDATED');
    }
  }
}

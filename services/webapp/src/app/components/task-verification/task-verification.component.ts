import { ChangeDetectorRef, Component, ElementRef, EventEmitter, OnInit, Output, ViewChild } from '@angular/core';
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
import { NgxExtendedPdfViewerService } from 'ngx-extended-pdf-viewer';
import { MatSelectChange } from '@angular/material/select';
import * as saveAs from 'file-saver';
import * as JSZip from 'jszip';
import { PDFDocument } from 'pdf-lib';

@Component({
  selector: 'app-task-verification',
  templateUrl: './task-verification.component.html',
  styleUrls: ['./task-verification.component.css']
})
export class TaskVerificationComponent implements OnInit {

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
  
  isSidebarHidden: boolean = false;
  isIndexProvided: boolean = false;
  pictureLoading: boolean = true;
  pdfLoading: boolean = true;
  disabledValidationcontainer = true;
  disabledValidationButton = true;
  disabledDropDown = false;
  validating: boolean = false;
  hasDownloadedZip: boolean = false;
  hasUploadedZip: boolean = false;

  job: Map<string, any>;
  pdfSrc: string;
  
  copiesInformations: Map<string, Map<string, number>> = new Map();
  nMaxPointsPerQuestion = new Map<string, number>();
  initialCopyIndex: number = -1;
  currentCopy: number = -1;
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
  questionIndexes: Array<number | "Tout sélectionner"> = [];
  formattedIndexes: Array<string> = [];

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
      await this.getMaxPointsPerQuestion();
      if (this.checkForAvailableCopies()) {
        this.nextCopy();
      }
      this.checkValidationButton();

      this.socketService.join(this.job["job_id"]);
      this.socketService.getSocket().on('document_ready', async (params: any) => {
        await this.getDocuments();
        await this.getMaxPointsPerQuestion();
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
      this.reroute();
    }
    this.formattedIndexes = this.generateFormattedIndexes();
    this.initializeQuestionIndexes();
    this.checkValidationButton();
  }

  ngOnDestroy(): void {
    this.socketService.getSocket().off('document_ready');
    this.socketService.getSocket().off('jobs_status');
    this.socketService.disconnectSocket();
  }
  
  toggleSidebar() {
    this.isSidebarHidden = !this.isSidebarHidden;
  }

  generateFormattedIndexes(): Array<string> {
    const formattedIndexes: Array<string> = [];
    const maxIndex = this.examsList.length;
    const questionString = `Q1`;
    const subExamsListSize = this.examsList.filter(exam => exam.filename.includes(questionString)).length;
    
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

  initializeQuestionIndexes(): void {
    this.questionIndexes = ["Tout sélectionner", ...Array.from({ length: this.nMaxPointsPerQuestion.size }, (_, i) => i + 1)];
    // if question index is provided in query params
    const questionIndex = this.route.snapshot.queryParams['question_index'];
    if (questionIndex) {
      this.currentQuestionIndex = questionIndex;
      this.onQuestionIndexChange({ value: questionIndex } as MatSelectChange);
      this.disabledDropDown = true;
      this.isIndexProvided = true;
    } else {
      this.route.params.subscribe(params => {
        const index = params['index'];
        if (index) {
          this.currentQuestionIndex = index;
          this.onQuestionIndexChange({ value: index } as MatSelectChange);
        }
      });
    }
  }

  onQuestionIndexChange(event: MatSelectChange): void {
    this.currentQuestionIndex = event.value;
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
    this.subExamsList = this.examsList.filter(exam => exam.filename.includes(questionString));

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
    await this.docService.getDocuments(this.tasksService.getvalidatingTaskId());
    this.examsList = this.docService.documentsList;
    this.groupsList = this.docService.groupsList;
    // compute sub exams list if any selected group
    this.getSubExamsList();
    // initialize initialCopyIndex and currentCopy
    if (this.examsList.length > 0 && this.initialCopyIndex < 0) {
      this.initialCopyIndex = this.examsList[0].document_index;
      this.currentCopy = this.initialCopyIndex - 1;
    }
  }

  async getMaxPointsPerQuestion() {
    await this.docService.getJobInfos(this.tasksService.getvalidatingTaskId());
    this.nMaxPointsPerQuestion = this.docService.nMaxPointsPerQuestion;
  }

  async getCopiesInformations() {
    let exam = this.examsList[this.currentIndex()];
    this.currentCopyName = exam["filename"];
    await this.docService.getCopiesInformations(this.tasksService.getvalidatingTaskId(), this.currentCopyName);
    this.copiesInformations = this.docService.copiesInformations;
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

  async addScoreToQuestion(): Promise<void> {
    await this.getMaxPointsPerQuestion();
    await this.getCopiesInformations();
  
    const fullCopyName = this.getBaseNameWithExtension(this.currentCopyName);
    if (fullCopyName && this.currentScore !== null) {
      if (this.currentScore <= this.nMaxPointsPerQuestion.get(this.currentQuestionIndex) && this.currentScore >= 0) {
        this.addOrUpdateInnerMap(fullCopyName, this.currentQuestionIndex, this.currentScore);
        this.currentScore = null;
      } else if (this.currentScore > this.nMaxPointsPerQuestion.get(this.currentQuestionIndex) && this.currentScore >= 0) {
        const excessPoints = this.currentScore - this.nMaxPointsPerQuestion.get(this.currentQuestionIndex);
        this.notificationService.showWarning(`Vous avez rajouté ${excessPoints} point(s) bonus`, 'Attention!');
        this.addOrUpdateInnerMap(fullCopyName, this.currentQuestionIndex, this.currentScore);
        this.currentScore = null;
      }else {
        this.notificationService.showWarning('Veuillez saisir une note valide.', 'Note invalide');
        throw new Error('Note invalide');
      }
    } else {
      this.notificationService.showWarning('Veuillez saisir une note.', 'Note invalide');
    }
  }

  addOrUpdateInnerMap(copieName: string, questionIndex: string, score: number) {
    if (!this.copiesInformations.has(copieName)) {
        let copieInformations = new Map<string, number>();
        copieInformations.set(questionIndex, score);
        this.copiesInformations.set(copieName, copieInformations);
    } else {
        let existingMap = this.copiesInformations.get(copieName);
        if (existingMap) {
          existingMap.set(questionIndex, score);
      }
    }
  }

  loadPdf(): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', this.tasksService.getvalidatingTaskId());
    formdata.append('document_index', this.currentCopy.toString());

    this.pdfLoading = true;
    if (this.examsList[this.currentIndex()]["status"] !== "NOT_READY") {
      this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).subscribe(
        (data) => {
          let url = window.URL.createObjectURL(data);
          this.pdfSrc = url;
          this.pdfLoading = false;
          // console.log("Current Exam: ", this.examsList[this.currentIndex()])
        }, (error) => {
          console.error(error);
        });
    }
  }

  // loadCopyInCanvas() {
  //   const formdata: FormData = new FormData();
  //   this.userService.addTokens(formdata);
  //   formdata.append('job_id', this.tasksService.getvalidatingTaskId());
  //   formdata.append('document_index', this.currentCopy.toString());

  //   this.pictureLoading = true;

  //   if (this.examsList[this.currentIndex()]["status"] !== "NOT_READY") {
  //     this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' }).subscribe(
  //       (data) => {
  //         let url = window.URL.createObjectURL(data);
  //         let img = new Image();
  //         img.src = url;
  //         this.pictureLoading = false;
  //         img.onload = this.drawImageScaled.bind(null, img);
  //       }, (error) => {
  //         console.error(error);
  //       });
  //   }
  // }

  // drawImageScaled(img) {

  //   let canvas = document.getElementById('cv') as HTMLCanvasElement;
  //   let ctx = canvas.getContext('2d');

  //   canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;

  //   ctx.clearRect(0, 0, canvas.width, canvas.height);

  //   ctx.imageSmoothingEnabled = false;
  //   ctx.drawImage(img, 0, 0, img.width, img.height,     // source rectangle
  //     0, 0, canvas.width, canvas.height); // destination rectangle
  // }

  changeCurrentCopy(copyIndex, status) {
    if (status !== "NOT_READY") {
      let exam = this.examsList[copyIndex-1];
      console.log("Change current copy to", copyIndex)
      this.currentQuestionIndex = this.getQuestionIndex(exam["filename"]);
      this.currentCopyName = this.getBaseNameWithExtension(exam["filename"]);
      this.currentCopy = copyIndex;
      console.log("Current copy", this.currentCopy);
      this.disabledValidationcontainer = false;
      this.loadCopy();
      this.setChosenColor(status);
    }
  }

  changeCurrentExam(examIndex) {
    this.changeCurrentCopy(this.initialCopyIndex + examIndex, this.examsList[examIndex].status);
  }

  loadCopy(): void {
    this.loadPdf();
    // this.loadCopyInCanvas();
    this.getCurrentMatricule();
    // this.getCurrentTotal();
    // this.getCurrentPredictions();
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
    })
    this.matriculeList = tempList;
  }


  getCurrentMatricule() {
    let exam = this.examsList[this.currentIndex()];
    if (exam["status"] !== "NOT_READY") {
      this.currentMatricule = exam["matricule"];
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

  // getCurrentTotal() {
  //   this.currentTotal = this.examsList[this.currentIndex()]["total"];
  // }

  // getCurrentPredictions() {
  //   this.currentPredictions = this.examsList[this.currentIndex()]["subquestion_predictions"];
  // }

  getCurrentStatus() {
    this.currentStatus = this.examsList[this.currentIndex()]["status"];
  }

  setValidatedStatus() {
    this.examsList[this.currentIndex()]["status"] = "VALIDATED";
  }


  async validateCurrentCopy() {
    if (!this.currentMatriculeSelection) {
        this.notificationService.showWarning('Veuillez fournir un matricule!', 'Matricule manquante');
        return;
    }

    if (this.hasDownloadedZip && !this.hasUploadedZip) {
      this.notificationService.showWarning("Vous n'avez téléversé aucun nouveaux fichiers.", 'Attention!');
    }

    this.examsList[this.currentIndex()]["total"] = this.currentTotal;
    const currentExam = this.examsList[this.currentIndex()];
    const filename = currentExam["filename"];

    try {
        await this.addScoreToQuestion();
        const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
        if (editedPdfData) {
            const file = new File([editedPdfData], filename, { type: editedPdfData.type });
            this.getCurrentMatricule();
            let validationResponse = await this.validationService.validateDocument(
                this.tasksService.getvalidatingTaskId(),
                this.currentCopy,
                file,
                this.copiesInformations,
                0,
                this.nMaxPointsPerQuestion,
                this.currentStatus
            );

            if (validationResponse === "OK") {
                this.setValidatedStatus();
                this.nextCopy();
            }
        } else {
            console.error('Erreur lors de l\'obtention du document PDF modifié.');
            this.notificationService.showError('Échec de l\'obtention du document PDF modifié.', 'Erreur de validation');
        }
    } catch (error) {
        console.error('Erreur lors de la validation ou du téléchargement du fichier :', error);
        this.notificationService.showError('Échec de la validation ou du téléchargement du document.', 'Erreur de validation');
    }
    this.checkValidationButton();
}



  async validateJob() {
    if (!this.disabledDropDown) {
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
        let response = await this.validationService.validateJob(this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
        if (response === "OK") {
          this.router.navigate(['/dashboard', this.job["job_id"]]);
          let message = "La tâche est en cours de finalisation!";
          this.notificationService.showInfo(message, "Alerte!")
          // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());
        }
      }
    } else {
      this.router.navigate(['/dashboard', this.job["job_id"]]);
      let message = "Les copies pour la question " + this.currentQuestionIndex + " ont été corrigées!";
      this.notificationService.showInfo(message, "Alerte!")
    }
  }

  openwarningDialog(): void {
    let dialogRef = this.dialog.open(ValidationWarningDialogComponent, {
      width: '30%',
      height: '40%',
    })
    dialogRef.afterClosed().subscribe(async result => {
        if (result !== undefined && result === true) {
          this.disabledValidationcontainer = true;
          this.validating = true;
          let response = await this.validationService.validateJob(
            this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
          if (response === "OK") {
            this.router.navigate(['/dashboard', this.job["job_id"]]);
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
    let exam = this.examsList[this.currentIndex()];
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

  currentIndex(): number {
    return this.currentCopy - this.initialCopyIndex;
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
    const mergedDocs: { [key: string]: PDFDocument } = {};
  
    for (const exam of this.subExamsList) {
      if (exam["status"] !== 'NOT_READY') {
        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('job_id', this.tasksService.getvalidatingTaskId());
        formdata.append('document_index', exam["document_index"].toString());
  
        await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' })
          .toPromise()
          .then(async (data: Blob) => {
            const arrayBuffer = await data.arrayBuffer();
            const pdfDoc = await PDFDocument.load(arrayBuffer);
            const fileName = exam["filename"];
            const questionIndex = this.verifyQuestionIndex(fileName);
            if (!mergedDocs[questionIndex]) {
              mergedDocs[questionIndex] = await PDFDocument.create();
            }
            const copiedPages = await mergedDocs[questionIndex].copyPages(pdfDoc, pdfDoc.getPageIndices());
            copiedPages.forEach((page) => {
              mergedDocs[questionIndex].addPage(page);
            });
          })
          .catch((error) => {
            console.error(`Error downloading file ${exam["filename"]}:`, error);
            this.notificationService.showError(`Erreur lors du téléchargement du fichier ${exam["filename"]}`, 'Erreur de téléchargement');
          });
      }
    }
  
    for (const questionIndex of Object.keys(mergedDocs)) {
      const mergedPdfBytes = await mergedDocs[questionIndex].save();
      const blob = new Blob([mergedPdfBytes], { type: 'application/pdf' });
      zip.file(`Q${questionIndex}.pdf`, blob);
    }
  
    zip.generateAsync({ type: 'blob' })
      .then((content) => {
        saveAs(content, `${this.job['job_name']}.zip`);
      });
  
    this.hasDownloadedZip = true;
    this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
  }
  
  verifyQuestionIndex(filename: string): string {
    const match = filename.match(/Q(\d+)/);
    return match ? match[1] : 'Unknown';
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
  
      for (const mergedFile of mergedFiles) {
        const pdfData = await zipContent.file(mergedFile).async('arraybuffer');
        const pdfDoc = await PDFDocument.load(pdfData);
  
        const questionIndex = this.verifyQuestionIndex(mergedFile);
        const originalDocs = this.subExamsList.filter(exam => exam["filename"].includes(`Q${questionIndex}`));
        const pagesPerQuestion = nPagesPerQuestion.get(`Q${questionIndex}`) || 1;
  
        let startPage = 0;
        for (const originalDoc of originalDocs) {
          const singlePagePdf = await PDFDocument.create();
          const endPage = startPage + pagesPerQuestion;
          const copiedPages = await singlePagePdf.copyPages(pdfDoc, Array.from({ length: pagesPerQuestion }, (_, k) => startPage + k));
          copiedPages.forEach((page) => {
            singlePagePdf.addPage(page);
          });
  
          const pdfBytes = await singlePagePdf.save();
          const blob = new Blob([pdfBytes], { type: 'application/pdf' });
          const fileName = originalDoc["filename"];
          zip.file(fileName, blob);
  
          startPage = endPage;
        }
      }
  
      const finalZipBlob = await zip.generateAsync({ type: 'blob' });
      const finalZipFile = new File([finalZipBlob], 'split_documents.zip', { type: 'application/zip' });
  
      const uploadFormData = new FormData();
      this.userService.addTokens(uploadFormData);
      uploadFormData.append('job_id', jobId);
      uploadFormData.append('file', finalZipFile);
  
      await this.http.post(`${SERVER_URL}/documents/replace`, uploadFormData).toPromise()
        .then((response) => {
          console.log('Files replaced successfully', response);
          this.hasUploadedZip = true;
          this.notificationService.showSuccess('Fichiers remplacés avec succès!', 'Succès');
        })
        .catch((error) => {
          console.error('Error replacing files:', error);
          this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
        });
  
    } catch (error) {
      console.error('Error processing zip file:', error);
      this.notificationService.showError('Erreur lors du traitement du fichier zip', 'Erreur');
    }
  }
}


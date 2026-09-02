import { HttpClient } from '@angular/common/http';
import { Component, Input } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router } from '@angular/router';
import { first } from 'rxjs/operators';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketService } from 'src/app/services/socket.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SERVER_URL } from 'src/app/utils';
import { TaskFilesDialogComponent } from '../task-files-dialog/task-files-dialog.component';
import { TaskRetryDialogComponent } from '../task-retry-dialog/task-retry-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { CsvUpdateDialogComponent } from '../csv-update/csv-update-dialog.component';

interface Question {
  name: string;
  index: number;
  bonus: boolean;
  max: number;
  validatedCount: number;
  count: number;
  total: number;
  average: number;
  stdDev: number;
  grades: number[];
  histogram: Array<{value: number, count: number}>;
  validatedFilenames: Set<string>;
}

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css'],
})
export class DashboardPageComponent {
  public task: any;
  public taskId: string;
  public taskName: string;
  public taskStats: boolean;
  public examsList: Array<any> = [];
  public questionsDocList: Array<any> = [];
  public examsCount = 0;
  public questions: Question[] = [];
  public totalVerifiedMatricules = 0;
  public ongoingTask = true;
  public disableButtons = false;
  public copySelection: any;
  public copiesList: any;

  constructor(
    private router: Router,
    private route: ActivatedRoute,
    private tasksService: TasksService,
    private userService: UserService,
    private http: HttpClient,
    public dialog: MatDialog,
    private socketService: SocketService,
    private docService: DocumentsService,
    private notificationService: NotificationService,
    private validationService: ValidationService,
  ) {}

  public async ngOnInit() {
    this.taskId = this.route.snapshot.queryParams.job_id;
    if (this.taskId === undefined) {
      this.route.params.pipe(first()).subscribe((params) => {
        this.taskId = params.taskId;
      });
    }
    if (this.taskId) {
      await this.loadTask();
    } else {
      this.router.navigate(['/tasks-history']);
    }

    this.socketService.join(this.taskId);
    this.socketService.getSocket().on('doc_validated', async (params: any) => {
      const resp = JSON.parse(params);
      const questions: boolean = resp.questions;
      const matricule: boolean = resp.matricule;
      const docIndices: number[] = [resp.document_index];
      try {
        // matricule has been validated
        if (matricule) {
          await this.docService.getDocuments(this.taskId, false, docIndices);
          this.examsList[resp.document_index] = this.docService.documentsList[0];
          this.computeTotalMatricules();
        }
        // if question has been validated
        if (questions) {
          await this.docService.getDocuments(this.taskId, true, docIndices);
          this.questionsDocList[resp.document_index] = this.docService.documentsList[0];
          this.computeQuestions();
        }
        // check if can be finalized
        this.checkIfTaskFinished();
      } catch (error) {
        console.error(error);
      }
    });
    this.socketService.getSocket().on('job_status', async (params: any) => {
      const resp = JSON.parse(params);
      const statusChanged = this.task.job_status !== resp.status;
      if (statusChanged) {
        const message = 'Le status de la tâche a changé à: ' + resp.status + ' !';
        this.notificationService.showInfo(message, 'Alerte!');
      }
      this.task.job_status = resp.status;
      this.updateViewOnStatus();
      if (resp.job_infos) {
        const message = 'Voici les nouvelles infos de la tâche: ' + resp.job_infos;
        this.notificationService.showInfo(message, 'Infos');
      }
      if (statusChanged || resp.job_infos) {
        this.loadTask();  // reload the counters (e.g. copies were added)
      }
    });
  }

  public ngOnDestroy(): void {
    // remove the socket listeners and leave the room so revisiting the
    // dashboard does not stack duplicate handlers on the shared socket
    const socket = this.socketService.getSocket();
    if (socket) {
      socket.off('doc_validated');
      socket.off('job_status');
      if (this.taskId) {
        socket.emit('leave', this.taskId);
      }
    }
  }

  private async loadTask(): Promise<void> {
    // fetch informations and documents
    await this.getTask();
    await this.getDocuments(this.taskId);
    if (this.examsCount > 0) {
      await this.getQuestions(this.taskId);
      // compute copies list
      this.getCopiesList();
    }
    // update metrics
    this.computeTotalMatricules();
    this.computeQuestions();
    // check if can be finalized
    this.checkIfTaskFinished();
  }

  public loggued(): boolean {
    return this.userService.loggued();
  }

  public shared(): boolean {
    return this.userService.shared();
  }

  public getCopiesList(): void {
    const tempDict = {};
    this.task.students_list.forEach((x) => {
      tempDict[x.matricule] = { identifiant: x.matricule + ' - ' + x['Nom complet'] };
    });
    let copy = 0;
    this.examsList.forEach((exam) => {
      if (exam.matricule && tempDict[exam.matricule]) {
        tempDict[exam.matricule].index = exam.document_index;
        tempDict[exam.matricule].copy = copy;
        copy += 1;
      }
    });
    this.copiesList = Object.values(tempDict).map((x) => {
      // x['identifiant'] = (x['index'] || 'N/A') + ' -> ' + x['identifiant'];
      return x;
    });
  }

  public selectCopy() {
    localStorage.setItem(`${this.taskId}_copy`, this.copySelection.copy);
  }

  public async getTask() {
    this.task = await this.tasksService.getTaskById(this.taskId);
    this.taskStats = this.task.statistics_for_students;
    if (this.task.copies_errors) {
        const cleanedInfos = this.task.copies_errors.slice(1, -1).replace(/['",]/g, '');
        this.task.copies_errors = cleanedInfos.split(/(?<=[.?!])\s+/).map(err => err.trim());
    }
    this.updateViewOnStatus();
  }

  public taskStatsChange(): void {
    this.tasksService.updateTaskStats(this.taskId, this.taskStats);
  }

  public questionBonusChange(question: Question): void {
    this.task.bonus_enabled_map[question.index][1] = question.bonus;
    const nQ = this.questions.length - 1;
    this.questions[nQ].max += question.bonus ? -question.max : question.max;
    this.tasksService.updateTaskBonus(this.taskId, this.task.bonus_enabled_map);
  }

  public updateViewOnStatus() {
    if (this.task.job_status === 'IGNORED' ||
             this.task.job_status === 'QUEUED' ||
             this.task.job_status === 'RUN' ||
             this.task.job_status === 'VALIDATION' ||
             this.task.job_status === 'VALIDATED' ||
             this.task.job_status === 'FINALIZING' ||
             this.task.job_status === 'ARCHIVED') {
      this.taskName = this.task.job_name;
      if (this.task.job_status === 'ARCHIVED') { this.taskName += ' (Archivée)'; }
      this.disableButtons = this.task.job_status === 'VALIDATED' ||
                            this.task.job_status === 'FINALIZING' ||
                            this.task.job_status === 'ARCHIVED';
    } else {
      if (this.task.job_status === 'ERROR') {
        this.notificationService.showWarning('La tâche n\'est pas accessible.', 'Attention');
      } else {
        this.notificationService.showWarning('La tâche n\'est pas encore accessible.', 'Attention');
      }
      this.router.navigate(['/tasks-history']);
    }
  }

  public async getDocuments(jobId: string) {
    await this.docService.getDocuments(jobId, false);
    this.examsList = this.docService.documentsList;
    this.examsCount = this.examsList.length;
  }

  public async getQuestions(jobId: string) {
    await this.docService.getDocuments(jobId, true);
    this.questionsDocList = this.docService.documentsList;
  }

  public computeTotalMatricules() {
    this.totalVerifiedMatricules = 0;
    this.examsList.forEach((doc) => {
      if (doc.status === 'VALIDATED' || doc.status === 'DELETED') {
        this.totalVerifiedMatricules++;
      }
    });
    this.checkIfTaskFinished();
  }

  public computeQuestions(): void {
    // if the task defines no question (correction disabled), stop right here;
    // a task without any copy yet still displays its question rows
    if (!this.task.n_max_points_per_question || this.task.n_max_points_per_question.length === 0) {
      this.questions = Array<Question>(0);
      return;
    }

    // initialize stats
    const questionsStats = new Map<string, Question>();
    this.task.n_max_points_per_question.forEach((element) => {
      const question_index: number = parseInt(element[0].slice(1));
      questionsStats[element[0]] = {
        name: element[0],
        index: question_index - 1,
        bonus: false,
        max: element[1],
        count: 0,
        validatedCount: 0,
        total: 0,
        average: 0,
        stdDev: 0,
        grades: [],
        histogram: [],
        validatedFilenames: new Set<string>(),
      };
    });
    this.task.bonus_enabled_map.forEach((element) => {
      questionsStats[element[0]].bonus = element[1];
    });

    // populate stats
    this.questionsDocList.forEach((doc) => {
      const stats = questionsStats[doc.question];
      stats.count++;
      if (doc.status === 'VALIDATED') {
        stats.validatedCount++;
        stats.grades.push(doc.grade);
        stats.total += doc.grade;
        stats.validatedFilenames.add(doc.basename);
      }
    });

    // put the questions in an array
    this.questions = Array<Question>(Object.keys(questionsStats).length);
    Object.values(questionsStats).forEach((question) => {
      this.questions[question.index] = question;
    });

    // compute the total
    if (this.questions.length > 1) {
      this.computeTotalQuestion();
    }

    // compute the averages
    this.questions.forEach((question) => {
      this.computeStats(question);
    });
  }

  public computeStats(question: Question): void {
    if (question.validatedCount > 0) {
      const average = question.total / question.validatedCount;
      question.average = Number(average.toFixed(2));
      const variance = question.grades.reduce(
        (sum, val) => sum + Math.pow(val - question.average, 2), 0
      ) / question.validatedCount;
      question.stdDev = Math.sqrt(variance);
      question.histogram = this.computeHistogram(question);
    } else {
      question.average = 0;
      question.stdDev = 0;
      question.histogram = [];
    }
  }

  public getMaxCount(question: Question): number {
    return Math.max(...question.histogram.map(bin => bin.count), 1);
  }

  // Compute histogram bins
  private computeHistogram(question: Question, maxBins = 10): Array<{value: number, count: number}> {
    // Prepare histogram bins
    const maxGrade = Math.max(...question.grades, question.max)
    const binRange = Math.ceil(maxGrade / maxBins);
    const nBins = Math.ceil(maxGrade / binRange);
    const bins = [];
    for (let i = 0; i <= nBins; i++) {
      bins.push({value: i * binRange, count: 0});
    }
    question.grades.forEach(value => {
      const binIndex = Math.floor(value / binRange);
      bins[binIndex].count++;
    });
    return bins;
  }

  public computeTotalQuestion() {
    const totalQuestion: Question = {
      name: 'Total',
      index: this.questions.length,
      bonus: false,
      max: 0,
      count: this.examsCount,
      validatedCount: 0,
      total: 0,
      average: 0,
      stdDev: 0,
      grades: [],
      histogram: [],
      validatedFilenames: null,
    };

    // find copies that are totally corrected/validated
    // count also max
    this.questions.forEach((question) => {
      if (totalQuestion.validatedFilenames) {
        const intersectionSet = new Set<string>();
        for (const name of question.validatedFilenames) {
          if (totalQuestion.validatedFilenames.has(name)) {
            intersectionSet.add(name);
          }
        }
        totalQuestion.validatedFilenames = intersectionSet;
      } else {
        totalQuestion.validatedFilenames = question.validatedFilenames;
      }
      // for max
      if (!question.bonus) {
        totalQuestion.max += question.max;
      }
    });
    totalQuestion.validatedCount = totalQuestion.validatedFilenames.size;

    // compute the total for those copies
    const totalGradesMap = new Map<string, number>();
    this.questionsDocList.forEach((doc) => {
      if (totalQuestion.validatedFilenames.has(doc.basename)) {
        totalQuestion.total += doc.grade;
        totalGradesMap.set(doc.basename, (totalGradesMap.get(doc.basename) || 0) + doc.grade);
      }
    });
    totalQuestion.grades = Array.from(totalGradesMap.values());
    this.questions.push(totalQuestion);
  }

  public checkIfTaskFinished() {
    this.ongoingTask = this.totalVerifiedMatricules < this.examsCount
          || (this.questions.length > 0 &&
              this.getTotalQuestion().validatedCount < this.examsCount);
  }

  public getTotalQuestion() {
    return this.questions[this.questions.length - 1];
  }

  public isQuestionBonus(questionName) {
    let bonus = false;
    this.task.bonus_enabled_map.every((element) => {
      if (element[0] !== questionName) { return true; }  // continue
      bonus = element[1];
      return false;  // stop
    });
    return bonus;
  }

  public getQuestionMax(questionName) {
    let qMax = 0;
    this.task.n_max_points_per_question.every((element) => {
      if (element[0] !== questionName) { return true; }  // continue
      qMax = element[1];
      return false;  // stop
    });
    return qMax;
  }

  public async reroute() {
    this.router.navigate(['/task-history']);
  }

  public openTaskFilesDialog(): void {
    const jobId = this.task.job_id;
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).pipe(first()).subscribe(
      (data) => {
        const dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '80%',
          maxWidth: '600px',
          height: '90%',
          data: { taskId: jobId, nbZipFile: data.nZips, stats: data.stats, share: this.userService.shared() },
        });
        dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
          if (result) {
            this.task.job_status = result;
            this.updateViewOnStatus();
          }
        }, (error) => {
          console.error(error);
        });
      }, (error) => {
        console.error(error);
      });
  }

  async restore() {
    await this.tasksService.updateTaskStatus(this.task.job_id, 'VALIDATION');
    this.task.job_status = 'VALIDATION';
  }

  public correctQuestion(index) {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    if (this.shared()) {
      const queryParams = {
        job_id: this.task.job_id,
        all: true,
      };
      if (index < this.questions.length - 1) {  // if not last question i.e. total
        queryParams['questionIndex'] = index + 1;
      }
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/task-validation`], { queryParams });
    } else {
      if (index < this.questions.length - 1) {  // if not last question i.e. total
        this.router.navigate([`/task-validation`, this.taskId, index + 1]);
      } else {
        this.router.navigate([`/task-validation`, this.taskId]);
      }
    }
  }

  public verifyMatricules() {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    if (this.shared()) {
      const queryParams = {
        job_id: this.task.job_id,
        all: true,
      };
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/matricule-validation`], { queryParams });
    } else {
      this.router.navigate([`/matricule-validation`, this.taskId]);
    }
  }

  public shareMatricule() {
    this.shareTask(false);
  }

  public shareQuestion(questionIndex= undefined) {
    this.shareTask(true, questionIndex);
  }

  public shareTask(job, questionIndex= undefined) {
    const data = { taskId: this.taskId, taskName: this.taskName, shareType: job ? 'job' : 'matricule'};
    if (questionIndex !== undefined) {
      data['questionIndex'] = questionIndex + 1;
    }
    this.dialog.open(TaskShareDialogComponent, {
      width: '80%',
      maxWidth: '300px',
      height: '40%',
      data,
    }).afterClosed().pipe(first()).subscribe((resp) => {
      if (resp !== undefined) {
        if (resp.success) {
          if (resp.message) {
            this.notificationService.showSuccess(resp.message, 'Succès!');
          }
        } else if (resp.message) {
            this.notificationService.showError(resp.message, 'Erreur!');
        }
      }
    }, (error) => {
      console.error(error);
    });
  }

  public updateCsv() {
    this.dialog.open(CsvUpdateDialogComponent, {
      width: '80%',
      maxWidth: '400px',
      height: '40%',
      data: { jobId: this.taskId },
    });
  }

  public addCopies(): void {
    const dialogRef = this.dialog.open(TaskRetryDialogComponent, {
      data: {taskId: this.taskId, taskName: this.taskName, taskMessages: this.task.copies_errors},
      height: '90%',
      width: '80%',
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
        if (result === false) {
          const message = 'Une erreur est intervenue lors de l\'ajout de nouvelles copies !';
          this.notificationService.showError(message, 'Erreur!');
        } else if (result) {
          this.task.copies_errors = '';
        }
      }, (error) => {
        console.error(error);
      });
  }

  public async validateJob() {
    if (this.totalVerifiedMatricules < this.examsCount) {
      this.notificationService.showError('Veuillez vérifier tous les matricules avant de valider la tâche!', 'Erreur!');
    } else if (this.questions.length > 0 &&
               this.getTotalQuestion().validatedCount < this.examsCount) {
      this.notificationService.showError('Veuillez corriger toutes les copies avant de valider la tâche!', 'Erreur!');
    } else {
      this.disableButtons = true;
      this.tasksService.setvalidatingTaskId(this.task.job_id);
      const response = await this.validationService.validateJob(this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
      if (response === 'OK') {
        // this.router.navigate(['/tasks-history']);
        const message = 'La tâche est en cours de finalisation!';
        this.notificationService.showInfo(message, 'Alerte!');
        // clear local storage
        localStorage.removeItem(`${this.task.job_id}_copy`);
        PDFSource.clearAll(this.task.job_id, this.questionsDocList.length);
      }
    }
  }

}

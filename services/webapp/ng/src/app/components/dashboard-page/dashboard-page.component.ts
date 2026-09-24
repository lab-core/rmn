import { HttpClient } from '@angular/common/http';
import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router } from '@angular/router';
import { first } from 'rxjs/operators';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { NotificationService } from 'src/app/services/notification.service';
import { SocketHandler, SocketService } from 'src/app/services/socket.service';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { ValidationService } from 'src/app/services/validation.service';
import { SERVER_URL } from 'src/app/utils';
import { TaskFilesDialogComponent } from '../task-files-dialog/task-files-dialog.component';
import { TaskRetryDialogComponent } from '../task-retry-dialog/task-retry-dialog.component';
import { TaskShareDialogComponent } from '../task-share-dialog/task-share-dialog.component';
import { CsvUpdateDialogComponent } from '../csv-update/csv-update-dialog.component';
import { TaskSettingsDialogComponent } from '../task-settings/task-settings-dialog.component';
import { DocumentStatus, JobStatus } from '../../generated/rmn-contracts';
import { SELECTED_COPY_SUFFIX, selectedCopy, selectedCopyKey } from 'src/app/selected-copy';

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
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class DashboardPageComponent {
  readonly JobStatus = JobStatus;
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
    this.onDocValidated = async (params: any) => {
      const resp = JSON.parse(params);
      const questions: boolean = resp.questions;
      const matricule: boolean = resp.matricule;
      const docIndices: number[] = [resp.document_index];
      try {
        // matricule has been validated
        if (matricule) {
          await this.docService.getDocuments(this.taskId, false, docIndices);
          this.replaceDocument(this.examsList, this.docService.documentsList[0]);
          this.computeTotalMatricules();
        }
        // if question has been validated
        if (questions) {
          await this.docService.getDocuments(this.taskId, true, docIndices);
          this.replaceDocument(this.questionsDocList, this.docService.documentsList[0]);
          this.computeQuestions();
        }
        // check if can be finalized
        this.checkIfTaskFinished();
      } catch (error) {
        console.error(error);
      }
    };
    this.socketService.on('doc_validated', this.onDocValidated);
    this.onJobStatus = async (params: any) => {
      const resp = JSON.parse(params);
      const statusChanged = this.task.job_status !== resp.status;
      if (statusChanged) {
        const message = 'Le status de la tâche a changé à: ' + resp.status + ' !';
        this.notificationService.showInfo(message, 'Alerte!');
      }
      this.task.job_status = resp.status;
      this.updateViewOnStatus();
      if (resp.job_infos) {
        // progress arrives here every few copies while the grades are being
        // read, so it is shown on the page rather than as a toast per update
        this.taskInfo = resp.job_infos;
        if (!this.isProgress(resp.job_infos)) {
          this.notificationService.showInfo(
            'Voici les nouvelles infos de la tâche: ' + resp.job_infos, 'Infos');
        }
      }
      if (statusChanged || (resp.job_infos && !this.isProgress(resp.job_infos))) {
        this.loadTask();  // reload the counters (e.g. copies were added)
      }
    };
    this.socketService.on('job_status', this.onJobStatus);
  }

  private onDocValidated: SocketHandler;
  private onJobStatus: SocketHandler;

  // what the executor is doing right now, shown while it does it
  taskInfo: string = '';
  // how far the grade reading has got, per question index, from POST /job
  autoGradeProgress: {[q: string]: {pending: number, running: number, done: number,
                                    graded: number, total: number}} = {};

  private readingOf(question: any) {
    // The rows carry a 0-based index while the reading is keyed by the
    // question number the rest of the system uses, so the name is what they
    // are matched on: it says "Q3" and means it. Keying on the index showed
    // every question the state of the one before it, and nothing on Q1.
    const name: string = question?.name || '';
    const match = /^Q(\d+)$/.exec(name);
    return match ? this.autoGradeProgress[match[1]] : undefined;
  }

  readingState(question: any): string {
    const p = this.readingOf(question);
    if (!p || !p.total) {
      return '';
    }
    // a copy the teacher has already graded is never read, so it is counted
    // out loud rather than left to make the total look short
    const toRead = p.total - p.graded;
    const skipped = p.graded ? ` (${p.graded} déjà notée${p.graded > 1 ? 's' : ''})` : '';
    if (p.running) {
      const percent = toRead ? Math.round(100 * p.done / toRead) : 100;
      return `Lecture en cours : ${percent} %${skipped}`;
    }
    if (p.pending) {
      return `Lecture à faire : ${p.done}/${toRead}${skipped}`;
    }
    return `Notes lues : ${p.done}/${toRead}${skipped}`;
  }

  readingClass(question: any): string {
    const p = this.readingOf(question);
    if (!p || !p.total) {
      return '';
    }
    if (p.running) {
      return 'reading-running';
    }
    return p.pending ? 'reading-waiting' : 'reading-done';
  }

  isProgress(info: string): boolean {
    return typeof info === 'string' && info.includes('%');
  }

  public ngOnDestroy(): void {
    // remove this page's socket listeners (only these) and leave the room so
    // revisiting the dashboard does not stack duplicate handlers
    if (this.onDocValidated) {
      this.socketService.off('doc_validated', this.onDocValidated);
    }
    if (this.onJobStatus) {
      this.socketService.off('job_status', this.onJobStatus);
    }
    if (this.taskId) {
      this.socketService.leave(this.taskId);
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

  /** One entry per student of the class list. A student whose copy was
   *  recognised carries the copy's document index and file name (the name is
   *  shared with its per-question documents) and its position among the
   *  recognised copies; without a copy the entry shows N/A and cannot be
   *  selected. */
  public getCopiesList(): void {
    const tempDict = {};
    this.task.students_list.forEach((x) => {
      tempDict[x.matricule] = { identifiant: x.matricule + ' - ' + x['Nom complet'] };
    });
    let copy = 0;
    this.examsList.forEach((exam) => {
      if (exam.matricule && tempDict[exam.matricule]) {
        tempDict[exam.matricule].index = exam.document_index;
        tempDict[exam.matricule].basename = exam.filename;
        tempDict[exam.matricule].copy = copy;
        copy += 1;
      }
    });
    this.copiesList = Object.values(tempDict);
    // restore the selection the correction pages are pointed at
    const selected = selectedCopy(this.taskId);
    this.copySelection = selected
      ? this.copiesList.find((c) => c.index === selected.document_index) ?? null
      : null;
  }

  /** Point the correction and matricule pages at the selected student's copy:
   *  they open on it the next time a question is loaded (see
   *  task-verification's selectedCopyIndex). The key is the copy's identity,
   *  not a position: the pages order their lists differently. */
  public selectCopy() {
    if (!this.copySelection || this.copySelection.copy === undefined) {
      return;  // N/A: the student has no recognised copy
    }
    localStorage.setItem(
      selectedCopyKey(this.taskId),
      JSON.stringify({ document_index: this.copySelection.index, basename: this.copySelection.basename }),
    );
    this.notificationService.showInfo(
      `Les pages de correction s'ouvriront sur la copie ${this.copySelection.copy + 1}.`, 'Copie sélectionnée');
  }

  public async getTask() {
    this.task = await this.tasksService.getTaskById(this.taskId);
    this.taskStats = this.task.statistics_for_students;
    this.autoGradeProgress = this.task.auto_grade_progress || {};
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
    // the map holds every question of the template, by key
    const entry = this.task.bonus_enabled_map.find((e) => e[0] === question.name);
    if (entry) {
      entry[1] = question.bonus;
    }
    // the Total row only exists with more than one question: a single-question
    // task used to add its own max to itself
    const total = this.questions[this.questions.length - 1];
    if (this.questions.length > 1 && total.name === 'Total') {
      total.max += question.bonus ? -question.max : question.max;
    }
    this.tasksService.updateTaskBonus(this.taskId, this.task.bonus_enabled_map);
  }

  public updateViewOnStatus() {
    if (this.task.job_status === JobStatus.IGNORED ||
             this.task.job_status === JobStatus.QUEUED ||
             this.task.job_status === JobStatus.RUN ||
             this.task.job_status === JobStatus.VALIDATION ||
             this.task.job_status === JobStatus.VALIDATED ||
             this.task.job_status === JobStatus.FINALIZING ||
             this.task.job_status === JobStatus.ARCHIVED) {
      this.taskName = this.task.job_name;
      if (this.task.job_status === JobStatus.ARCHIVED) { this.taskName += ' (Archivée)'; }
      this.disableButtons = this.task.job_status === JobStatus.VALIDATED ||
                            this.task.job_status === JobStatus.FINALIZING ||
                            this.task.job_status === JobStatus.ARCHIVED;
    } else {
      if (this.task.job_status === JobStatus.ERROR) {
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
      if (doc.status === DocumentStatus.VALIDATED || doc.status === DocumentStatus.DELETED) {
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

    // initialize stats; an ignored question (0 page) has no copy to correct
    // and is not displayed, but keeps its index for the bonus map
    const questionsStats: Record<string, Question> = {};
    this.task.n_max_points_per_question.forEach((element) => {
      if (this.isQuestionIgnored(element[0])) { return; }
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
      if (questionsStats[element[0]]) { questionsStats[element[0]].bonus = element[1]; }
    });

    // populate stats
    this.questionsDocList.forEach((doc) => {
      const stats = questionsStats[doc.question];
      if (!stats) { return; }
      stats.count++;
      if (doc.status === DocumentStatus.VALIDATED) {
        stats.validatedCount++;
        stats.grades.push(doc.grade);
        stats.total += doc.grade;
        stats.validatedFilenames.add(doc.basename);
      }
    });

    // put the questions in an array, in numeric order (compacted: the array
    // position is not the question number once a question is ignored)
    this.questions = Object.values(questionsStats);
    this.questions.sort((a, b) => a.index - b.index);

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
    // a max of 0 gave NaN bins (and threw inside the socket handler); a
    // negative grade indexed bins[-1]
    const maxGrade = Math.max(...question.grades, question.max, 0);
    const binRange = Math.max(Math.ceil(maxGrade / maxBins), 1);
    const nBins = Math.ceil(maxGrade / binRange);
    const bins = [];
    for (let i = 0; i <= nBins; i++) {
      bins.push({value: i * binRange, count: 0});
    }
    question.grades.forEach(value => {
      const binIndex = Math.min(Math.max(Math.floor(value / binRange), 0), nBins);
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

  public isQuestionIgnored(questionName): boolean {
    const pages = this.task.n_pages_per_question || [];
    const entry = pages.find((element) => element[0] === questionName);
    return entry !== undefined && !entry[1];
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
    this.router.navigate(['/tasks-history']);
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
    await this.tasksService.updateTaskStatus(this.task.job_id, JobStatus.VALIDATION);
    this.task.job_status = JobStatus.VALIDATION;
    // /job/update/status emits no socket event, so refresh the view here:
    // re-enable the buttons and drop the "(Archivée)" suffix of the title
    this.updateViewOnStatus();
  }

  public correctQuestion(question: Question) {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    // the question number comes from its index, not from its position in the
    // table: an ignored question leaves a hole in the numbering
    const isTotal = question.name === 'Total';
    if (this.shared()) {
      const queryParams = {
        job_id: this.task.job_id,
        all: true,
      };
      if (!isTotal) {
        // task-verification and the share-token payload read question_index
        queryParams['question_index'] = question.index + 1;
      }
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/task-validation`], { queryParams });
    } else {
      if (!isTotal) {
        this.router.navigate([`/task-validation`, this.taskId, question.index + 1]);
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

  /** Rename the task, or change its points per question until it is validated. */
  public editSettings(): void {
    const dialogRef = this.dialog.open(TaskSettingsDialogComponent, {
      width: '80%',
      maxWidth: '500px',
      data: {
        taskId: this.taskId,
        taskName: this.task.job_name,
        status: this.task.job_status,
        nPagesPerQuestion: this.task.n_pages_per_question,
        nMaxPointsPerQuestion: this.task.n_max_points_per_question,
      },
    });
    dialogRef.afterClosed().pipe(first()).subscribe(async (result) => {
      if (result) {
        await this.loadTask();  // new title, maxima, and the grades flagged again
      }
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
        for (const key of ['_copy', '_matricule_copy', SELECTED_COPY_SUFFIX]) {
          localStorage.removeItem(`${this.task.job_id}${key}`);
        }
        PDFSource.clearAll(this.task.job_id, this.questionsDocList.length);
      }
    }
  }

  // the lists are indexed by position while document_index is a server id;
  // the two only coincide for a single-question task with no copies added later
  private replaceDocument(list: any[], doc: any): void {
    if (!doc) {
      return;
    }
    const position = list.findIndex(d => d.document_index === doc.document_index);
    if (position >= 0) {
      list[position] = doc;
    } else {
      list.push(doc);
    }
  }

}

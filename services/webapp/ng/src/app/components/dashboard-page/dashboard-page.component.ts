import { HttpClient } from '@angular/common/http';
import { Component, Input } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router } from '@angular/router';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { TaskFilesDialogComponent } from '../tasks-history/task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from '../tasks-history/task-share-dialog/task-share-dialog.component';
import { SocketService } from 'src/app/services/socket.service';
import { NotificationService } from 'src/app/services/notification.service';
import { DocumentsService } from 'src/app/services/documents.service';
import { ValidationService } from 'src/app/services/validation.service';
import { first } from 'rxjs/operators';


interface Question {
  name: string;
  index: number;
  bonus: boolean;
  max: number;
  validatedCount: number;
  count: number;
  total: number;
  average: number;
  validatedFilenames: Set<string>;
}

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css']
})
export class DashboardPageComponent {
  task: any;
  taskId: string;
  taskName: string;
  taskStats: boolean;
  examsList: Array<any> = [];
  questionsDocList: Array<any> = [];
  examsCount: number = 0;
  questions: Question[] = [];
  totalVerifiedMatricules: number = 0;
  ongoingTask: boolean = true;
  disableButtons: boolean = false;

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
    private validationService: ValidationService
  ) {}

  async ngOnInit() {
    this.taskId = this.route.snapshot.queryParams['job_id'];
    if (this.taskId == undefined) {
      this.route.params.pipe(first()).subscribe(params => {
        this.taskId = params['taskId'];
      });
    }
    if (this.taskId) {
      // fetch informations and documents
      await this.getTask();
      await this.getDocuments(this.taskId);
      if (this.examsCount > 0) {
        await this.getQuestions(this.taskId);
        // update metrics
        this.computeTotalMatricules();
        this.computeQuestions();
      }
    } else {
      this.router.navigate(['/tasks-history']);
    }

    this.socketService.join(this.taskId)
    this.socketService.getSocket().on('doc_validated', async (params: any) => {
      const resp = JSON.parse(params)
      const questions: boolean = resp.questions;
      const matricule: boolean = resp.matricule;
      const docIndices: number[] = [resp.document_index]
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
      } catch (error) {
        console.error(error);
      }
    });
    this.socketService.getSocket().on('job_status', async (params: any) => {
      let resp = JSON.parse(params)
      this.task.job_status = resp.status;
      this.updateViewOnStatus();
    });
  }

  loggued(): boolean {
    return this.userService.loggued();
  }

  shared(): boolean {
    return this.userService.shared();
  }

  async getTask() {
    this.task = await this.tasksService.getTaskById(this.taskId);
    this.taskStats = this.task.statistics_for_students;
    this.updateViewOnStatus();
  }

  taskStatsChange(): void {
    this.tasksService.updateTaskStats(this.taskId, this.taskStats);
  }

  updateViewOnStatus() {
    if (this.task.job_status === 'IGNORED' ||
             this.task.job_status === 'QUEUED' ||
             this.task.job_status === 'RUN' ||
             this.task.job_status === 'VALIDATION' ||
             this.task.job_status === 'VALIDATED' ||
             this.task.job_status === 'FINALIZING' ||
             this.task.job_status === 'ARCHIVED') {
      this.taskName = this.task.job_name;
      if (this.task.job_status === 'ARCHIVED') this.taskName += ' (Archivée)';
      this.disableButtons = this.task.job_status === 'VALIDATED' ||
                            this.task.job_status === 'FINALIZING' ||
                            this.task.job_status === 'ARCHIVED';
    } else {
      if (this.task.job_status === 'ERROR') {
        this.notificationService.showWarning("La tâche n'est pas accessible.", "Attention");
      } else {
        this.notificationService.showWarning("La tâche n'est pas encore accessible.", "Attention");
      }
      this.router.navigate(['/tasks-history']);
    }
  }

  async getDocuments(jobId: string) {
    await this.docService.getDocuments(jobId, false);
    this.examsList = this.docService.documentsList;
    this.examsCount = this.examsList.length;
  }

  async getQuestions(jobId: string) {
    await this.docService.getDocuments(jobId, true);
    this.questionsDocList = this.docService.documentsList;
  }

  computeTotalMatricules() {
    this.totalVerifiedMatricules = 0;
    this.examsList.forEach(doc => {
      if (doc.status === 'VALIDATED' || doc.status === 'DELETED') {
        this.totalVerifiedMatricules++;
      }
    });
    this.checkIfTaskFinished();
  }

  computeQuestions() {
    const questionsStats = new Map<string, Question>();
    this.questionsDocList.forEach(doc => {
      if (questionsStats[doc.question] === undefined) {
        let question: Question = {
          name: doc.question,
          index: doc.question_index - 1,
          bonus: this.isQuestionBonus(doc.question),
          max: this.getQuestionMax(doc.question),
          count: 0,
          validatedCount: 0,
          total: 0,
          average: 0,
          validatedFilenames: new Set<string>()
        };
        questionsStats[doc.question] = question;
      }

      let stats = questionsStats[doc.question];
      stats.count++;
      if (doc.status === 'VALIDATED') {
        stats.validatedCount++;
        stats.total += doc.grade;
        stats.validatedFilenames.add(doc.basename);
      }
    });

    // put the questions in an array
    this.questions = Array<Question>(Object.keys(questionsStats).length);
    Object.values(questionsStats).forEach(question => {
      this.questions[question.index] = question;
    });

    // compute the total
    this.computeTotalQuestion();

    // compute the averages
    this.questions.forEach(question => {
      this.computeAverage(question);
    });
  }

  computeAverage(question: Question) {
    if (question.validatedCount > 0) {
      const average = question.total / question.validatedCount;
      question.average = Number(average.toFixed(2));
    } else {
      question.average = 0;
    }
  }

  computeTotalQuestion() {
    const totalQuestion: Question = {
      name: "Total",
      index: this.questions.length,
      bonus: false,
      max: 0,
      count: this.examsCount,
      validatedCount: 0,
      total: 0,
      average: 0,
      validatedFilenames: null
    }

    // find copies that are totally corrected/validated
    // count also max
    this.questions.forEach(question => {
      if (totalQuestion.validatedFilenames) {
        let intersectionSet = new Set<string>();
        for (let name of question.validatedFilenames) {
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
    this.questionsDocList.forEach(doc => {
      if (totalQuestion.validatedFilenames.has(doc.basename)) {
        totalQuestion.total += doc.grade;
      }
    })
    this.questions.push(totalQuestion);

    this.checkIfTaskFinished();
  }

  checkIfTaskFinished() {
    this.ongoingTask = this.totalVerifiedMatricules < this.examsCount
          || this.getTotalQuestion() == null
          || this.getTotalQuestion().validatedCount < this.examsCount;
  }

  getTotalQuestion() {
    if (this.questions.length > 0) {
      return this.questions[this.questions.length - 1];
    }
    return null;
  }

  isQuestionBonus(questionName) {
    let bonus = false;
    this.task["bonus_enabled_map"].every(element => {
      if (element[0] !== questionName) return true;  // continue
      bonus = element[1];
      return false;  // stop
    });
    return bonus;
  }

  getQuestionMax(questionName) {
    let qMax = 0;
    this.task["n_max_points_per_question"].every(element => {
      if (element[0] !== questionName) return true;  // continue
      qMax = element[1];
      return false;  // stop
    });
    return qMax;
  }

  async reroute() {
    this.router.navigate(['/task-history']);
  }

  openTaskFilesDialog(): void {
    const jobId = this.task.job_id;
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).pipe(first()).subscribe(
      (data) => {
        let dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '30%',
          height: '60%',
          data: { taskId: jobId, nbZipFile: data['nZips'], stats: data['stats'], share: this.userService.shared() }
        })
        dialogRef.afterClosed().pipe(first()).subscribe(async result => {
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

  correctQuestion(index) {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    if (this.shared()) {
      const queryParams = {
        job_id: this.task.job_id,
        all: true
      }
      if (index < this.questions.length - 1) {  // if not last question i.e. total
        queryParams['question_index'] = index + 1;
      }
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/task-validation`], { queryParams: queryParams });
    } else {
      if (index < this.questions.length - 1) {  // if not last question i.e. total
        this.router.navigate([`/task-validation`, this.taskId, index + 1]);
      } else {
        this.router.navigate([`/task-validation`, this.taskId]);
      }
    }
  }

  verifyMatricules() {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    if (this.shared()) {
      const queryParams = {
        job_id: this.task.job_id,
        all: true
      }
      this.userService.addShareToken(queryParams);
      this.router.navigate([`/matricule-validation`], { queryParams: queryParams });
    } else {
      this.router.navigate([`/matricule-validation`, this.taskId]);
    }
  }

  shareMatricule() {
    this.shareTask(false);
  }

  shareQuestion(questionIndex=undefined) {
    this.shareTask(true, questionIndex);
  }

  shareTask(job, questionIndex=undefined) {
    let data = { taskId: this.taskId, taskName: this.taskName, shareType: job ? 'job' : 'matricule'}
    if (questionIndex !== undefined) {
      data["questionIndex"] = questionIndex + 1;
    }
    this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: data
    }).afterClosed().pipe(first()).subscribe(resp => {
      if (resp !== undefined) {
        if (resp.success) {
          if (resp.message)
            this.notificationService.showSuccess(resp.message, "Succès!");
        } else if (resp.message) {
            this.notificationService.showError(resp.message, "Erreur!");
        }
      }
    }, (error) => {
      console.error(error);
    });
  }

  async validateJob() {
    if (this.totalVerifiedMatricules < this.examsCount) {
      this.notificationService.showError("Veuillez vérifier tous les matricules avant de valider la tâche!", "Erreur!");
    } else if (this.getTotalQuestion().validatedCount < this.examsCount) {
      this.notificationService.showError("Veuillez corriger toutes les copies avant de valider la tâche!", "Erreur!");
    } else {
      this.disableButtons = true;
      this.tasksService.setvalidatingTaskId(this.task.job_id);
      const response = await this.validationService.validateJob(this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
      if (response === "OK") {
        // this.router.navigate(['/tasks-history']);
        const message = "La tâche est en cours de finalisation!";
        this.notificationService.showInfo(message, "Alerte!")
      }
    }
  }

}

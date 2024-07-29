import { HttpClient } from '@angular/common/http';
import { Component, Input } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router } from '@angular/router';
import { TasksService } from 'src/app/services/tasks.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { TaskFilesDialogComponent } from '../tasks-history/task-files-dialog/task-files-dialog.component';
import { TaskShareDialogComponent } from '../tasks-history/task-share-dialog/task-share-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { DocumentsService } from 'src/app/services/documents.service';
import { ValidationService } from 'src/app/services/validation.service';
import { ValidationWarningDialogComponent } from '../task-verification/validation-warning-dialog/validation-warning-dialog.component';

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css']
})
export class DashboardPageComponent {
  task: any;
  taskId: string;
  taskName: string;
  examsList: Array<any> = [];
  questionsDocList: Array<any> = [];
  examsCount: number = 0;
  questions: { corrected: number, total: number }[] = [];
  maxQuestionIndex: number;
  averages: number[] = [];
  nMaxPointsPerQuestion: Map<string, number>;
  bonusEnabledMap = new Map<string, boolean>();
  totalCorrectedCopies: number = 0;
  totalVerifiedMatricules: number = 0;
  totalPoints: number = 0;
  totalCopies: number = 0;
  totalMean: number = 0;
  maxPossiblePoints: number = 0;
  validating: boolean = false;

  constructor(
    private router: Router,
    private route: ActivatedRoute,
    private tasksService: TasksService,
    private userService: UserService,
    private http: HttpClient,
    public dialog: MatDialog,
    private docService: DocumentsService,
    private notificationService: NotificationService,
    private validationService: ValidationService
  ) {
  }

  async ngOnInit() {
    this.route.params.subscribe(params => {
      this.taskId = params['taskId'];
    });
    if (this.taskId) {
      // fetch informations and documents
      await this.getTask();
      await this.getDocuments(this.taskId);
      await this.getQuestions(this.taskId);
      // update metrics
      this.computeTotals();
      this.updateQuestions();
    } else {
      this.router.navigate(['/tasks-history']);
    }
  }

  loggued(): boolean {
    return this.userService.loggued();
  }

  async getTask() {
    this.task = await this.tasksService.getTaskById(this.taskId);
    this.taskName = this.task.job_name;
    if (this.task['copies_informations'] && this.task['n_max_points_per_question']) {
      this.averages = this.computeAverage();
    } else {
      console.error('Missing required task properties: copies_informations or n_max_points_per_question');
    }
  }

  getTaskInfo() {
    if (this.task.job_status === 'ARCHIVED') {
      this.openTaskFilesDialog(this.task.job_id);
    } else if (this.task.job_status === 'VALIDATION' || this.task.job_status === 'RUN') {
      this.tasksService.setvalidatingTaskId(this.task.job_id);
      this.router.navigate(['/task-validation']);
    }
  }

  async getDocuments(jobId: string) {
    try {
      const formdata: FormData = new FormData();
      formdata.append('user_id', this.userService.currentUsername);
      formdata.append('token', this.userService.token);
      formdata.append('job_id', jobId);
      const response = await this.http.post<any>(`${SERVER_URL}/documents`, formdata).toPromise();
      if (response && response.response) {
        this.examsList = response.response || [];
        this.examsCount = this.examsList.length;
      } else {
        console.error('Invalid response format:', response);
      }
    } catch (error) {
      console.error('Error fetching documents:', error);
    }
  }

  async getQuestions(jobId: string) {
    try {
      const formdata: FormData = new FormData();
      formdata.append('user_id', this.userService.currentUsername);
      formdata.append('token', this.userService.token);
      formdata.append('job_id', jobId);
      formdata.append('questions', "true");
      const response = await this.http.post<any>(`${SERVER_URL}/documents`, formdata).toPromise();
      if (response && response.response) {
        this.questionsDocList = response.response || [];
      } else {
        console.error('Invalid response format:', response);
      }
    } catch (error) {
      console.error('Error fetching documents:', error);
    }
  }

  updateQuestions() {
    const validatedCounts: { [key: string]: number } = {};
    this.questionsDocList.forEach(doc => {
      if (doc.status === 'VALIDATED') {
        if (!validatedCounts[doc.question]) {
          validatedCounts[doc.question] = 0;
        }
        validatedCounts[doc.question]++;
      }
    });

    this.questions = [];
    this.task['n_max_points_per_question'].forEach(([question, _]: [string, number]) => {
      this.questions.push({
        corrected: validatedCounts[question] || 0,
        total: this.examsCount
      });
    });
  }

  computeTotals() {
    const bonusEnabledArray = this.task['bonus_enabled_map'];
    this.bonusEnabledMap = new Map<string, boolean>(
      bonusEnabledArray.map((item: [string, boolean]) => [item[0], item[1]])
    );
    const fullyCorrectedCopies = this.computeFullyCorrectedCopies();
    this.totalCorrectedCopies = fullyCorrectedCopies.length;

    this.totalVerifiedMatricules = 0;
    this.examsList.forEach((exam: any) => {
      if (exam["status"] === "VALIDATED") {
        this.totalVerifiedMatricules += 1;
      }
    });

    let totalPoints = 0;
    let totalCopies = 0;
    let maxPossiblePoints = 0;

    // compute the maximum possible points excluding bonus questions
    this.nMaxPointsPerQuestion.forEach((maxPoints, question) => {
      if (!this.bonusEnabledMap.get(question)) {
        maxPossiblePoints += maxPoints;
      }
    });

    fullyCorrectedCopies.forEach(copy => {
      let copyPoints = 0;

      this.task['copies_informations'].forEach(([copyId, questions]) => {
        if (copyId === copy) {
          questions.forEach(([question, points]) => {
            copyPoints += points;
          });
        }
      });

      if (maxPossiblePoints > 0) {
        totalPoints += copyPoints;
        totalCopies++;
      }
    });

    this.totalPoints = totalPoints;
    this.totalCopies = totalCopies;
    this.totalMean = totalCopies > 0 ? totalPoints / totalCopies : 0;
    this.maxPossiblePoints = maxPossiblePoints;
  }

  computeFullyCorrectedCopies(): string[] {
    const correctedCopiesMap: { [filename: string]: number } = {};

    this.questionsDocList.forEach(doc => {
      if (!correctedCopiesMap[doc.basename]) {
        correctedCopiesMap[doc.basename] = 0;
      }
      if (doc.status === 'VALIDATED') {
        correctedCopiesMap[doc.basename]++;
      }
    });

    return Object.keys(correctedCopiesMap).filter(filename => {
      return correctedCopiesMap[filename] === this.task['n_max_points_per_question'].length;
    });
  }

  openTaskFilesDialog(jobId: string): void {
    const formdata: FormData = new FormData();
    formdata.append('user_id', this.userService.currentUsername);
    formdata.append('token', this.userService.token);
    formdata.append('job_id', jobId);
    this.http.post<any>(`${SERVER_URL}job/batch/info`, formdata).subscribe(
      (data) => {
        let nbZipFile = data['response']
        let dialogRef = this.dialog.open(TaskFilesDialogComponent, {
          width: '30%',
          height: '60%',
          data: { taskId: jobId, nbZipFile: nbZipFile }
        })
      }, (error) => {
        console.error(error);
      });
  }

  computeAverage(): number[] {
    const copiesInformationsArray = this.task['copies_informations'];

    const copiesInformations = new Map<string, Map<string, number>>(
      copiesInformationsArray.map((item: [string, Array<[string, number]>]) =>
        [item[0], new Map<string, number>(item[1].map(innerItem => [innerItem[0], innerItem[1]]))]
      )
    );

    const nMaxPointsPerQuestionArray = this.task['n_max_points_per_question'];
    this.nMaxPointsPerQuestion = new Map<string, number>(
      nMaxPointsPerQuestionArray.map((item: [string, number]) => [item[0], item[1]])
    );

    // initializing an object to store the total points and count for each question
    const totals = new Map<string, { totalPoints: number, count: number }>();

    copiesInformations.forEach((studentScores) => {
      studentScores.forEach((score, question) => {
        if (!totals.has(question)) {
          totals.set(question, { totalPoints: 0, count: 0 });
        }
        const questionTotals = totals.get(question)!;
        questionTotals.totalPoints += score;
        questionTotals.count += 1;
      });
    });

    // computing averages
    const averages: number[] = [];

    this.nMaxPointsPerQuestion.forEach((_, question) => {
      const questionTotals = totals.get(question);
      if (questionTotals) {
        const average = questionTotals.totalPoints / questionTotals.count;
        averages.push(Number(average.toFixed(2)));
      } else {
        averages.push(0);
      }
    });

    return averages;
  }

  correctQuestion(index=undefined) {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    if (index) {
      this.router.navigate([`/task-validation`, this.taskId, index + 1]);
    } else {
      this.router.navigate([`/task-validation`, this.taskId]);
    }
  }

  verifyMatricules() {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    this.router.navigate([`/matricule-validation`, this.taskId]);
  }

  shareQuestion(index=undefined) {
    let data = { taskId: this.taskId, taskName: this.taskName, shareType: 'job' }
    if (index) {
      data["questionIndex"] = index + 1;
    }
    let dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: data
    });
    dialogRef.afterClosed().subscribe(async result => {
      if (result === false) {
        const message = "Une erreur est intervenue lors du partage de la question !";
        this.notificationService.showError(message, "Erreur!");
      }
    }, (error) => {
      console.error(error);
    });
  }

  shareTask() {
    let dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: { taskId: this.taskId, taskName: this.taskName, shareType: 'matricule' }
    });
    dialogRef.afterClosed().subscribe(async result => {
      if (result === false) {
        const message = "Une erreur est intervenue lors du partage de la tâche !";
        this.notificationService.showError(message, "Erreur!");
      }
    }, (error) => {
      console.error(error);
    });
  }

  async validateJob() {
    // // workaround to grade all the copies at once
    // const copiesInformations = {'asgqwasvbnrydh':{'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4, 'Q5': 5}, 'eqghqrafdz':{'Q1': 8, 'Q2': 8, 'Q3': 8, 'Q4': 8, 'Q5': 8}, 'ghnfdbxfdc':{'Q1': 3, 'Q2': 5, 'Q3': 1, 'Q4': 2, 'Q5': 4}, 'knm__vqead ':{'Q1': 1, 'Q2': 1, 'Q3': 3, 'Q4': 7, 'Q5': 2}, 'mdh xgvc.pdf':{'Q1': 6, 'Q2': 8, 'Q3': 4, 'Q4': 4, 'Q5': 5}, 'mffytdhgc':{'Q1': 2, 'Q2': 2, 'Q3': 5, 'Q4': 9, 'Q5': 8}, 'mtodjhisnjrbifs': {'Q1': 1, 'Q2': 6, 'Q3': 9, 'Q4': 4, 'Q5': 1}, 'wqref bw g':{'Q1': 7, 'Q2': 7, 'Q3': 8, 'Q4': 6, 'Q5': 7}, 'wvdzcs':{'Q1': 5, 'Q2': 9, 'Q3': 0, 'Q4': 6, 'Q5': 5}}
    // const formData: FormData = new FormData();
    // this.userService.addTokens(formData);
    // formData.append('job_id', this.task.job_id);
    // const serializedCopiesInformations = JSON.stringify(
    //   Object.entries(copiesInformations).map(([key, value]) => [key, Object.entries(value)])
    // );
    // formData.append('copies_informations', serializedCopiesInformations);
    //
    // let response;
    // try {
    //     const promise = await this.http.post<any>(`${SERVER_URL}documents/grade_all`, formData).toPromise();
    //     response = promise['response'];
    //     console.log(response);
    // } catch (error) {
    //     console.error(error);
    // }
    //
    // // workaround to validate all the copies at once
    // this.examsList.forEach((exam: any) => {
    //   if (exam["status"] === "TO VALIDATE") {
    //     exam["status"] = "VALIDATED";
    //   }
    // });

    if (this.totalVerifiedMatricules < this.examsCount) {
      this.notificationService.showError("Veuillez vérifier tous les matricules avant de valider la tâche!", "Erreur!");
    } else if (this.totalCorrectedCopies < this.examsCount) {
      this.notificationService.showError("Veuillez corriger toutes les copies avant de valider la tâche!", "Erreur!");
    } else {
      this.validating = true;
      this.tasksService.setvalidatingTaskId(this.task.job_id);
      let response = await this.validationService.validateJob(this.tasksService.getvalidatingTaskId(), this.userService.moodleStructureInd);
      if (response === "OK") {
        this.router.navigate(['/tasks-history']);
        let message = "La tâche est en cours de finalisation!";
        this.notificationService.showInfo(message, "Alerte!")
        // this.openTaskFilesDialog(this.tasksService.getvalidatingTaskId());
      }
    }
  }

}

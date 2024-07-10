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
  uniqueFileCount: number = 0;
  questions: { corrected: number, total: number }[] = [];
  validatedCounts: { [key: string]: number } = {};
  maxQuestionIndex: number;
  averages: number[] = [];
  nMaxPointsPerQuestion: Map<string, number>;
  totalCorrectedCopies: number = 0;
  totalAverage: number = 0;

  constructor(
    private router: Router,
    private route: ActivatedRoute, 
    private tasksService: TasksService, 
    private userService: UserService, 
    private http: HttpClient, 
    public dialog: MatDialog,
    private docService: DocumentsService, 
    private notificationService: NotificationService
  ) { 
  }

  async ngOnInit() {
    this.route.params.subscribe(params => {
      this.taskId = params['taskId'];
    });
    if (this.taskId) {
      await this.getTask();
      await this.getDocuments(this.taskId);
    }
  }

  async getTask() {
    this.task = await this.tasksService.getTaskById(this.taskId);
    this.taskName = this.task.job_name;
    if (this.task['copies_informations'] && this.task['n_max_points_per_question']) {
      this.averages = this.computeAverage();
      this.computeTotals();
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
        this.uniqueFileCount = this.getUniqueFilenames(this.examsList).length;
        this.countValidatedByQuestion();
        this.updateQuestions();
        this.computeTotals();
      } else {
        console.error('Invalid response format:', response);
      }
    } catch (error) {
      console.error('Error fetching documents:', error);
    }
  }  

  getUniqueFilenames(examsList: Array<any>): Array<string> {
    if (!examsList) {
      console.error('examsList is undefined');
      return [];
    }

    const filenames = examsList.map(doc => doc.filename.replace(/_Q\d+/, ''));
    return Array.from(new Set(filenames));
  }

  countValidatedByQuestion() {
    const validatedCounts: { [key: string]: number } = {};

    this.validatedCounts = {};

    this.examsList.forEach(doc => {
      if (doc.status === 'VALIDATED') {
        const questionIndexMatch = doc.filename.match(/_Q(\d+)/);
        if (questionIndexMatch) {
          const questionIndex = questionIndexMatch[1];
          if (!validatedCounts[questionIndex]) {
            validatedCounts[questionIndex] = 0;
          }
          validatedCounts[questionIndex]++;
        }
      }
    });

    this.validatedCounts = validatedCounts;
  }

  updateQuestions() {
    this.questions = [];

    if (!this.validatedCounts) {
      this.validatedCounts = {};
    }

    this.task['n_max_points_per_question'].forEach(([question, _]: [string, number]) => {
      const questionIndex = question.replace('Q', '');
      this.questions.push({
        corrected: this.validatedCounts[questionIndex] || 0,
        total: this.uniqueFileCount
      });
    });
  }

  computeTotals() {
    const fullyCorrectedCopies = this.computeFullyCorrectedCopies();
    this.totalCorrectedCopies = fullyCorrectedCopies.length;

    let totalPoints = 0;
    let totalCopies = 0;

    fullyCorrectedCopies.forEach(copy => {
      let copyPoints = 0;
      let questionsCount = 0;

      this.task['copies_informations'].forEach(([copyId, questions]) => {
        if (copyId === copy) {
          questions.forEach(([question, points]) => {
            copyPoints += points;
            questionsCount++;
          });
        }
      });

      if (questionsCount > 0) {
        totalPoints += copyPoints;
        totalCopies++;
      }
    });

    this.totalAverage = totalCopies > 0 ? totalPoints / (totalCopies * this.nMaxPointsPerQuestion.size) : 0;
  }

  computeFullyCorrectedCopies(): string[] {
    const correctedCopiesMap: { [filename: string]: number } = {};

    this.examsList.forEach(doc => {
      const filename = doc.filename.replace(/_Q\d+/, '');
      if (!correctedCopiesMap[filename]) {
        correctedCopiesMap[filename] = 0;
      }
      if (doc.status === 'VALIDATED') {
        correctedCopiesMap[filename]++;
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

  correctQuestion(index: number) {
    this.tasksService.setvalidatingTaskId(this.task.job_id);
    this.router.navigate([`/task-validation`, this.taskId, index + 1]);
  }

  shareQuestion(index: number) {
    let dialogRef = this.dialog.open(TaskShareDialogComponent, {
      width: '30%',
      height: '40%',
      data: { taskId: this.taskId, taskName: this.taskName, questionIndex: index + 1 }
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
}

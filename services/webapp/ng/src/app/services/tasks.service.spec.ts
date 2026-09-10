import { TestBed } from '@angular/core/testing';
import { HttpClient, HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { TasksService } from './tasks.service';
import { UserService } from './user.service';
import { NotificationService } from './notification.service';

const userStub = {
  addTokens: (form: FormData) => {
    form.append('user_id', 'alice');
    form.append('token', 'tok');
  }
};

describe('TasksService', () => {
  let service: TasksService;
  let http: HttpTestingController;
  let notification: jasmine.SpyObj<NotificationService>;

  beforeEach(() => {
    localStorage.clear();
    notification = jasmine.createSpyObj('NotificationService', ['showInfo', 'showError']);
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: UserService, useValue: userStub },
        { provide: NotificationService, useValue: notification },
      ]
    });
    service = TestBed.inject(TasksService);
    http = TestBed.inject(HttpTestingController);
    spyOn(console, 'log');
  });

  afterEach(() => http.verify());

  it('remembers the task being validated across reloads', () => {
    expect(service.getvalidatingTaskId()).toBeNull();
    service.setvalidatingTaskId('job-1');
    expect(service.getvalidatingTaskId()).toBe('job-1');
    expect(localStorage.getItem('job_id')).toBe('job-1');

    localStorage.setItem('job_id', 'job-2');
    const fresh = new TasksService(
      TestBed.inject(Router), TestBed.inject(HttpClient), userStub as any, notification);
    expect(fresh.getvalidatingTaskId()).toBe('job-2');
  });

  it('getTask is null without a remembered task, otherwise fetches it', async () => {
    expect(await service.getTask()).toBeNull();

    service.setvalidatingTaskId('job-1');
    const pending = service.getTask();
    const req = http.expectOne('/api/job');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job-1');
    expect(form.get('user_id')).toBe('alice');
    req.flush({ response: { job_id: 'job-1', job_name: 'Exam' } });
    expect(await pending).toEqual({ job_id: 'job-1', job_name: 'Exam' });
  });

  it('sends the status, stats and bonus updates with the credentials', async () => {
    const status = service.updateTaskStatus('job', 'ARCHIVED');
    let req = http.expectOne('/api/job/update/status');
    expect((req.request.body as FormData).get('job_status')).toBe('ARCHIVED');
    expect((req.request.body as FormData).get('token')).toBe('tok');
    req.flush({ response: 'OK' });
    await status;

    const stats = service.updateTaskStats('job', 'true');
    req = http.expectOne('/api/job/update/stats');
    expect((req.request.body as FormData).get('statistics_for_students')).toBe('true');
    req.flush({ response: 'OK' });
    await stats;

    const bonus = service.updateTaskBonus('job', [['Q1', true]]);
    req = http.expectOne('/api/job/update/bonus');
    expect((req.request.body as FormData).get('bonus_enabled_map')).toBe('[["Q1",true]]');
    req.flush({ response: 'OK' });
    await bonus;
  });

  it('addTask serialises the maps, reports progress and resolves on the response', async () => {
    const pending = service.addTask(
      new File([''], 'copies.zip'), new File([''], 'notes.csv'), 'front', 'regular',
      new Map([['Q1', 2], ['Q2', 1]]), new Map([['Q1', 10], ['Q2', 5]]), new Map([['Q1', false], ['Q2', true]]),
      'Exam', 'Front', 'Regular', 'true', true);

    const req = http.expectOne('/api/evaluate');
    const form = req.request.body as FormData;
    expect(form.get('n_pages_per_question')).toBe('[["Q1",2],["Q2",1]]');
    expect(form.get('n_max_points_per_question')).toBe('[["Q1",10],["Q2",5]]');
    expect(form.get('bonus_enabled_map')).toBe('[["Q1",false],["Q2",true]]');
    expect(form.get('job_name')).toBe('Exam');
    expect(form.get('validate_matricule')).toBe('true');
    expect(form.get('statistics_for_students')).toBe('true');
    expect(form.get('user_id')).toBe('alice');
    expect(req.request.reportProgress).toBeTrue();

    expect(service.getpercentageDone()).toBe(0);
    req.event({ type: HttpEventType.UploadProgress, loaded: 50, total: 200 });
    expect(service.getpercentageDone()).toBe(25);
    expect(service.getUploadPart1State()).toBeTrue();

    req.flush({ response: 'OK' });
    await pending;
    expect(service.getpercentageDone()).toBe(100);
    expect(notification.showInfo).toHaveBeenCalled();
  });

  it('addTask rejects when the upload fails', async () => {
    spyOn(console, 'error');
    const pending = service.addTask(
      new File([''], 'copies.zip'), new File([''], 'notes.csv'), 'front', 'regular',
      new Map(), new Map(), new Map(), 'Exam', 'Front', 'Regular', 'false', false);
    http.expectOne('/api/evaluate').flush({ response: 'bad' }, { status: 400, statusText: 'Bad Request' });
    await expectAsync(pending).toBeRejected();
    expect(notification.showInfo).not.toHaveBeenCalled();
  });
});

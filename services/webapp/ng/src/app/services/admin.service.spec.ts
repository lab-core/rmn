import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { AdminService } from './admin.service';
import { UserService } from './user.service';
import { userServiceStub } from '../testing/helpers';

describe('AdminService', () => {
  let service: AdminService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: UserService, useValue: userServiceStub({ currentUsername: 'root' }) },
      ],
    });
    service = TestBed.inject(AdminService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  const sent = (url: string) => {
    const req = http.expectOne(url);
    req.flush({ response: 'OK' });
    return req.request;
  };

  it('names the account in username, the caller in user_id', () => {
    service.resetPassword('bob').subscribe();
    const form = sent('/api/users/reset_password').body as FormData;
    expect(form.get('user_id')).toBe('alice');  // the stub's addTokens
    expect(form.get('username')).toBe('bob');

    service.setRole('bob', 'Gestionnaire').subscribe();
    expect((sent('/api/users/role').body as FormData).get('role')).toBe('Gestionnaire');

    service.closeSessions('bob').subscribe();
    expect((sent('/api/users/sessions/close').body as FormData).get('username')).toBe('bob');

    service.deleteUser('bob').subscribe();
    expect((sent('/api/users/delete').body as FormData).get('username')).toBe('bob');
  });

  it('sends every manager, and none for an empty list', () => {
    service.setManagers('bob', ['chef', 'autre']).subscribe();
    expect((sent('/api/users/managers').body as FormData).getAll('managers')).toEqual(['chef', 'autre']);
    service.setManagers('bob', []).subscribe();
    expect((sent('/api/users/managers').body as FormData).getAll('managers')).toEqual([]);
  });

  it('reports the storage before it cleans it', () => {
    service.storageSweep(false).subscribe();
    let form = sent('/api/manage/storage/clean').body as FormData;
    expect(form.get('dry_run')).toBe('true');
    expect(form.get('usage')).toBe('true');

    service.storageSweep(true, true, false).subscribe();
    form = sent('/api/manage/storage/clean').body as FormData;
    expect(form.get('dry_run')).toBe('false');
    expect(form.get('include_strays')).toBe('true');
    expect(form.get('include_empty_jobs')).toBe('false');
  });

  it('reaches the operator commands', () => {
    service.status().subscribe();
    expect(sent('/api/manage/status').method).toBe('GET');
    service.deleteJobs(365).subscribe();
    expect((sent('/api/manage/delete/jobs').body as FormData).get('n_days_old')).toBe('365');
    service.deleteTokens(30).subscribe();
    expect((sent('/api/manage/delete/tokens').body as FormData).get('n_days_old')).toBe('30');
  });
});

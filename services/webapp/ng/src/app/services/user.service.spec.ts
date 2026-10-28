import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { ToastrService } from 'ngx-toastr';

import { UserService } from './user.service';
import { NotificationService } from './notification.service';
import { db } from './offline-db';

describe('UserService', () => {
  let http: HttpTestingController;
  let router: Router;
  let toastr: jasmine.SpyObj<ToastrService>;

  // the service reads localStorage in its constructor, so build it on demand
  const fresh = () => new UserService(
    TestBed.inject(HttpClient), TestBed.inject(Router), TestBed.inject(NotificationService));

  const session = () => {
    localStorage.setItem('user_id', 'alice');
    localStorage.setItem('role', 'Utilisateur');
    localStorage.setItem('token', 'tok');
  };

  beforeEach(() => {
    localStorage.clear();
    toastr = jasmine.createSpyObj('ToastrService', ['success', 'error', 'info', 'warning']);
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ToastrService, useValue: toastr },
      ]
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(console, 'log');
  });

  afterEach(() => http.verify());

  it('starts logged out when localStorage is empty', () => {
    const service = fresh();
    expect(service.loggued()).toBeFalse();
    expect(service.shared()).toBeFalse();
    // the server's own default, until a session says otherwise
    expect(service.saveVerifiedImages).toBeTrue();
    expect(service.moodleStructureInd).toBeFalse();
    const form = new FormData();
    service.addTokens(form);
    expect(Array.from(form.keys())).toEqual([]);
  });

  it('restores the session from localStorage', () => {
    session();
    localStorage.setItem('saveVerifiedImages', 'true');
    localStorage.setItem('moodleStructureInd', 'undefined');
    const service = fresh();

    expect(service.loggued()).toBeTrue();
    expect(service.currentUsername).toBe('alice');
    expect(service.role).toBe('Utilisateur');
    expect(service.saveVerifiedImages).toBeTrue();
    expect(service.moodleStructureInd).toBeFalse();

    const form = new FormData();
    service.addTokens(form);
    expect(form.get('user_id')).toBe('alice');
    expect(form.has('token')).toBeFalse();
    expect(service.authHeader()).toBe('Bearer tok');
    expect(service.getSocketAuth()).toEqual({ user_id: 'alice', token: 'tok' });
  });

  it('login stores the session and logout clears it', async () => {
    const service = fresh();
    const pending = service.login('alice', 'pw');
    const req = http.expectOne('/api/users/login');
    expect(req.request.method).toBe('POST');
    expect((req.request.body as FormData).get('username')).toBe('alice');
    expect((req.request.body as FormData).get('password')).toBe('pw');
    req.flush({ response: {
      username: 'alice', role: 'Administrateur', token: 'tok',
      saveVerifiedImages: true, moodleStructureInd: false,
    } });
    await pending;

    expect(service.loggued()).toBeTrue();
    expect(service.role).toBe('Administrateur');
    expect(service.saveVerifiedImages).toBeTrue();
    expect(localStorage.getItem('token')).toBe('tok');
    expect(localStorage.getItem('saveVerifiedImages')).toBe('true');
    expect(service.warningShown).toBeFalse();

    service.logout();
    expect(service.loggued()).toBeFalse();
    expect(service.currentUsername).toBeUndefined();
    expect(localStorage.getItem('token')).toBeNull();
  });

  it('a share link takes precedence in forms and on the socket handshake', () => {
    session();
    const service = fresh();
    const route = { queryParams: { token: 'share-1', question_index: 'Q2' } } as any;

    expect(service.canActivateShared(route, null)).toBeTrue();
    expect(service.shared()).toBeTrue();
    const form = new FormData();
    service.addTokens(form);
    expect(form.get('share_token')).toBe('share-1');
    expect(form.get('question_index')).toBe('Q2');
    expect(form.has('token')).toBeFalse();
    expect(service.authHeader()).toBeUndefined();  // the link's scope, not the user's
    expect(service.getSocketAuth()).toEqual({ share_token: 'share-1' });
    const params: any = {};
    service.addShareToken(params);
    expect(params.token).toBe('share-1');

    // entering a logged-in page drops the share token again
    expect(service.canActivateLoggued(null, null)).toBeTrue();
    expect(service.shared()).toBeFalse();
  });

  it('the guards send anonymous visitors to the login page and warn once', () => {
    const service = fresh();
    service.warningShown = false;

    const result = service.canActivateLoggued(null, null);
    expect(result instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(result as UrlTree)).toBe('/login');
    expect(toastr.warning).toHaveBeenCalledTimes(1);

    service.canActivateLoggued(null, null);
    expect(toastr.warning).toHaveBeenCalledTimes(1);

    const shared = service.canActivateShared({ queryParams: {} } as any, null);
    expect(shared instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(shared as UrlTree)).toBe('/login');
  });

  it('profile flags are sent as 0/1 with the credentials', () => {
    session();
    const service = fresh();

    service.updateSaveVerifiedImagesValue(true).subscribe();
    let req = http.expectOne('/api/users/updateSaveVerifiedImages');
    expect(req.request.method).toBe('PUT');
    expect((req.request.body as FormData).get('saveVerifiedImages')).toBe('1');
    expect((req.request.body as FormData).get('username')).toBe('alice');
    expect((req.request.body as FormData).has('token')).toBeFalse();
    req.flush({ response: 'ok' });
    expect(service.saveVerifiedImages).toBeTrue();

    service.updateMoodleStructureInd(false).subscribe();
    req = http.expectOne('/api/users/updateMoodleStructureInd');
    expect((req.request.body as FormData).get('moodleStructureInd')).toBe('0');
    req.flush({ response: 'ok' });
    expect(service.moodleStructureInd).toBeFalse();
  });

  it('signup carries the admin credentials and the new account', () => {
    session();
    const service = fresh();
    service.signup('bob', 'S3cret', 'Utilisateur').subscribe();
    const req = http.expectOne('/api/users/signup');
    const form = req.request.body as FormData;
    expect(form.get('user_id')).toBe('alice');
    expect(form.get('username')).toBe('bob');
    expect(form.get('password')).toBe('S3cret');
    expect(form.get('role')).toBe('Utilisateur');
    req.flush({ response: 'Utilisateur Créé' });
  });

  const adminSession = () => {
    localStorage.setItem('user_id', 'root');
    localStorage.setItem('role', 'Administrateur');
    localStorage.setItem('token', 'admin-tok');
    // switching user empties the offline copies: keep the real database out of it
    spyOn(db, 'clearAll').and.resolveTo();
  };
  const borrowed = (username: string, token: string) => ({ response: {
    username, role: 'Utilisateur', token, saveVerifiedImages: false,
    moodleStructureInd: true, impersonatedBy: 'root',
  } });

  it('impersonate becomes the user and stopImpersonating comes back', async () => {
    adminSession();
    const service = fresh();
    let left = 0;
    service.loggedOut$.subscribe(() => left++);

    const pending = service.impersonate('alice');
    const req = http.expectOne('/api/users/impersonate');
    expect((req.request.body as FormData).get('user_id')).toBe('root');
    expect((req.request.body as FormData).get('username')).toBe('alice');
    req.flush(borrowed('alice', 'alice-tok'));
    await pending;

    expect(service.currentUsername).toBe('alice');
    expect(service.role).toBe('Utilisateur');
    expect(service.impersonatedBy).toBe('root');
    expect(service.authHeader()).toBe('Bearer alice-tok');
    expect(left).toBe(1);
    // a reload keeps both sessions
    const reloaded = fresh();
    expect(reloaded.currentUsername).toBe('alice');
    expect(reloaded.impersonatedBy).toBe('root');

    service.stopImpersonating();
    const drop = http.expectOne('/api/users/logout');
    expect(drop.request.headers.get('Authorization')).toBe('Bearer alice-tok');
    drop.flush({ response: 'OK' });
    expect(service.currentUsername).toBe('root');
    expect(service.role).toBe('Administrateur');
    expect(service.impersonatedBy).toBeUndefined();
    expect(service.authHeader()).toBe('Bearer admin-tok');
    expect(localStorage.getItem('admin_session')).toBeNull();
    expect(localStorage.getItem('impersonated_by')).toBeNull();
    expect(left).toBe(2);
  });

  it('impersonating again drops the borrowed session but keeps the admin one', async () => {
    adminSession();
    const service = fresh();
    let pending = service.impersonate('alice');
    http.expectOne('/api/users/impersonate').flush(borrowed('alice', 'alice-tok'));
    await pending;

    pending = service.impersonate('bob');
    http.expectOne('/api/users/impersonate').flush(borrowed('bob', 'bob-tok'));
    await pending;
    const drop = http.expectOne('/api/users/logout');
    expect(drop.request.headers.get('Authorization')).toBe('Bearer alice-tok');
    drop.flush({ response: 'OK' });
    expect(service.currentUsername).toBe('bob');

    service.stopImpersonating();
    http.expectOne('/api/users/logout').flush({ response: 'OK' });
    expect(service.currentUsername).toBe('root');
  });

  it('a refused impersonation leaves the session alone', async () => {
    adminSession();
    const service = fresh();
    const pending = service.impersonate('nobody');
    http.expectOne('/api/users/impersonate').flush(
      { response: 'Error: user nobody does not exist.' }, { status: 404, statusText: 'Not Found' });
    await expectAsync(pending).toBeRejected();
    expect(service.currentUsername).toBe('root');
    expect(localStorage.getItem('admin_session')).toBeNull();
  });

  it('logging out of a borrowed session deletes its token', async () => {
    adminSession();
    const service = fresh();
    const pending = service.impersonate('alice');
    http.expectOne('/api/users/impersonate').flush(borrowed('alice', 'alice-tok'));
    await pending;

    service.logout();
    const drop = http.expectOne('/api/users/logout');
    expect(drop.request.headers.get('Authorization')).toBe('Bearer alice-tok');
    drop.flush({ response: 'OK' });
    expect(service.impersonatedBy).toBeUndefined();
    expect(localStorage.getItem('admin_session')).toBeNull();
  });

  it('listUsers asks the server', () => {
    adminSession();
    fresh().listUsers().subscribe();
    const req = http.expectOne('/api/users/all');
    expect(req.request.method).toBe('GET');
    req.flush({ response: [] });
  });

  it('logout ends the whole session: storage, share token, offline copies, and tells the others', async () => {
    session();
    localStorage.setItem('newTask', 'roster');
    const service = fresh();
    service.canActivateShared({ queryParams: { token: 'share-1', question_index: '2' } } as any, {} as any);
    const clearAll = spyOn(db, 'clearAll').and.resolveTo();
    let notified = 0;
    service.loggedOut$.subscribe(() => notified++);

    service.logout();

    expect(service.loggued()).toBeFalse();
    expect(service.shared()).toBeFalse();
    expect(localStorage.getItem('newTask')).toBeNull();
    expect(clearAll).toHaveBeenCalled();
    expect(notified).toBe(1);
  });
});

import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, HttpRequest, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { firstValueFrom } from 'rxjs';

import { CacheInterceptor, ErrorInterceptor, FreshHttpInterceptor } from './interceptor.service';
import { UserService } from './user.service';

function setup(interceptor: any, extraProviders: any[] = []) {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptorsFromDi()),
      provideHttpClientTesting(),
      provideRouter([]),
      // useExisting: the same instance as TestBed.inject(interceptor)
      { provide: HTTP_INTERCEPTORS, useExisting: interceptor, multi: true },
      ...extraProviders,
    ]
  });
  return {
    http: TestBed.inject(HttpClient),
    backend: TestBed.inject(HttpTestingController),
  };
}

describe('ErrorInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let router: Router;
  let toastr: jasmine.SpyObj<ToastrService>;
  const user = { loggued: () => true, logout: jasmine.createSpy('logout') };

  beforeEach(() => {
    toastr = jasmine.createSpyObj('ToastrService', ['success', 'error', 'info', 'warning']);
    user.loggued = () => true;
    user.logout.calls.reset();
    ({ http, backend } = setup(ErrorInterceptor, [
      { provide: ToastrService, useValue: toastr },
      { provide: UserService, useValue: user },
    ]));
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(console, 'warn');
    spyOn(console, 'log');
  });

  afterEach(() => backend.verify());

  it('notifies, sends a logged-in user home and rethrows on 401', async () => {
    const pending = firstValueFrom(http.get('/api/jobs')).catch(e => e);
    backend.expectOne('/api/jobs').flush(
      { response: 'Error: token not valid.' }, { status: 401, statusText: 'Unauthorized' });

    const error = await pending;
    expect(error.status).toBe(401);
    expect(toastr.error).toHaveBeenCalledWith('Error: token not valid.', 'Erreur !', {});
    expect(router.navigate).toHaveBeenCalledWith(['/']);
    expect(user.logout).not.toHaveBeenCalled();
  });

  it('logs out and goes to the login page when the server flags a dead session', async () => {
    const pending = firstValueFrom(http.post('/api/jobs', {})).catch(e => e);
    backend.expectOne('/api/jobs').flush(
      { response: 'Error: token not valid. Please login.', code: 'token_invalid' },
      { status: 401, statusText: 'Unauthorized' });

    expect((await pending).status).toBe(401);
    expect(user.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(router.navigate).not.toHaveBeenCalledWith(['/']);
  });

  it('leaves a share-link visitor alone on a dead-session 401', async () => {
    user.loggued = () => false;
    const pending = firstValueFrom(http.post('/api/jobs', {})).catch(e => e);
    backend.expectOne('/api/jobs').flush({ response: 'nope', code: 'token_invalid' }, { status: 401, statusText: 'Unauthorized' });
    await pending;
    expect(user.logout).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('does not redirect a share-link visitor on 404', async () => {
    user.loggued = () => false;
    const pending = firstValueFrom(http.get('/api/job')).catch(e => e);
    backend.expectOne('/api/job').flush({ response: 'not here' }, { status: 404, statusText: 'Not Found' });

    expect((await pending).status).toBe(404);
    expect(toastr.error).toHaveBeenCalledWith('not here', 'Erreur !', {});
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('reads the message out of a Blob error body', async () => {
    const body = new Blob([JSON.stringify({ Error: 'Fichier introuvable' })], { type: 'application/json' });
    const pending = firstValueFrom(http.get('/api/file/download', { responseType: 'blob' })).catch(e => e);
    backend.expectOne('/api/file/download').flush(body, { status: 404, statusText: 'Not Found' });
    await pending;
    // Blob.text() resolves a few tasks later than the error itself
    for (let i = 0; i < 50 && toastr.error.calls.count() === 0; i++) {
      await new Promise(resolve => setTimeout(resolve, 5));
    }

    expect(toastr.error).toHaveBeenCalledWith('Fichier introuvable', 'Erreur !', {});
  });

  it('leaves other errors to the caller and passes successes through', async () => {
    const failing = firstValueFrom(http.get('/api/jobs')).catch(e => e);
    backend.expectOne('/api/jobs').flush('boom', { status: 500, statusText: 'Error' });
    expect((await failing).status).toBe(500);
    expect(toastr.error).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();

    const ok = firstValueFrom(http.get('/api/jobs'));
    backend.expectOne('/api/jobs').flush({ response: [] });
    expect(await ok).toEqual({ response: [] });
  });
});

describe('CacheInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;

  beforeEach(() => ({ http, backend } = setup(CacheInterceptor)));
  afterEach(() => backend.verify());

  it('serves a repeated GET from memory and never caches a POST', async () => {
    const first = firstValueFrom(http.get('/api/config'));
    backend.expectOne('/api/config').flush({ v: 1 });
    expect(await first).toEqual({ v: 1 });

    const second = await firstValueFrom(http.get('/api/config'));
    backend.expectNone('/api/config');
    expect(second).toEqual({ v: 1 });

    for (const value of [2, 3]) {
      const post = firstValueFrom(http.post('/api/config', {}));
      backend.expectOne('/api/config').flush({ v: value });
      expect(await post).toEqual({ v: value });
    }
  });

  it('caches per URL', async () => {
    const a = firstValueFrom(http.get('/api/a'));
    backend.expectOne('/api/a').flush('a');
    await a;
    const b = firstValueFrom(http.get('/api/b'));
    backend.expectOne('/api/b').flush('b');
    expect(await b).toBe('b');
  });
});

describe('FreshHttpInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let interceptor: FreshHttpInterceptor;

  beforeEach(() => {
    ({ http, backend } = setup(FreshHttpInterceptor));
    interceptor = TestBed.inject(FreshHttpInterceptor);
    spyOn(console, 'warn');
  });

  afterEach(() => backend.verify());

  const toJobs = (r: any) => r.url === '/api/jobs';

  it('retries server and network errors twice with cache-busting headers', fakeAsync(() => {
    let error: any;
    http.get('/api/jobs').subscribe({ error: e => error = e });

    const first = backend.expectOne(toJobs);
    expect(first.request.params.has('_ts')).toBeFalse();
    first.flush('down', { status: 503, statusText: 'Unavailable' });
    tick(interceptor.delayMs);

    const retry1 = backend.expectOne(toJobs);
    expect(retry1.request.params.has('_ts')).toBeTrue();
    expect(retry1.request.headers.get('Cache-Control')).toBe('no-cache');
    expect(retry1.request.headers.get('Pragma')).toBe('no-cache');
    retry1.error(new ProgressEvent('error'), { status: 0 });
    tick(interceptor.delayMs);

    const retry2 = backend.expectOne(toJobs);
    retry2.flush('down', { status: 500, statusText: 'Error' });
    tick(interceptor.delayMs);

    backend.expectNone(toJobs);
    expect(error.status).toBe(500);
  }));

  it('returns the first successful retry', fakeAsync(() => {
    let body: any;
    http.get('/api/jobs').subscribe(b => body = b);
    backend.expectOne(toJobs).flush('down', { status: 502, statusText: 'Bad Gateway' });
    tick(interceptor.delayMs);
    backend.expectOne(toJobs).flush({ response: 'ok' });
    expect(body).toEqual({ response: 'ok' });
  }));

  it('does not retry client errors', fakeAsync(() => {
    let error: any;
    http.get('/api/jobs').subscribe({ error: e => error = e });
    backend.expectOne(toJobs).flush('nope', { status: 400, statusText: 'Bad Request' });
    tick(interceptor.delayMs);
    backend.expectNone(toJobs);
    expect(error.status).toBe(400);
  }));

  it('retries a read-only POST (this API reads through POST)', fakeAsync(() => {
    let body: any;
    const toDocuments = (r: any) => r.url === '/api/documents';
    http.post('/api/documents', new FormData()).subscribe(b => body = b);
    backend.expectOne(toDocuments).error(new ProgressEvent('error'), { status: 0 });
    tick(interceptor.delayMs);
    backend.expectOne(toDocuments).flush({ response: [] });
    expect(body).toEqual({ response: [] });
  }));

  it('never retries a POST that changes state, even on a network error', fakeAsync(() => {
    let error: any;
    const toEvaluate = (r: any) => r.url === '/api/evaluate';
    http.post('/api/evaluate', new FormData()).subscribe({ error: e => error = e });
    backend.expectOne(toEvaluate).error(new ProgressEvent('error'), { status: 0 });
    tick(interceptor.delayMs);
    backend.expectNone(toEvaluate);
    expect(error.status).toBe(0);
  }));

  it('classifies requests by path, tolerating a doubled slash', () => {
    const post = (url: string) => new HttpRequest('POST', url, new FormData());
    expect(FreshHttpInterceptor.isRetryable(post('/api/jobs'))).toBeTrue();
    expect(FreshHttpInterceptor.isRetryable(post('/api//documents'))).toBeTrue();
    expect(FreshHttpInterceptor.isRetryable(post('/api/document/update'))).toBeFalse();
    expect(FreshHttpInterceptor.isRetryable(post('/api//documents/replace'))).toBeFalse();
    expect(FreshHttpInterceptor.isRetryable(new HttpRequest('PUT', '/api/updateSaveVerifiedImages', {}))).toBeFalse();
    expect(FreshHttpInterceptor.isRetryable(new HttpRequest('GET', '/api/admin/executor'))).toBeTrue();
  });
});

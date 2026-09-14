import { TestBed } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { AuthInterceptor } from './auth.interceptor';
import { UserService } from './user.service';

describe('AuthInterceptor', () => {
  let http: HttpTestingController;
  let client: HttpClient;
  let user: { authHeader: jasmine.Spy };

  beforeEach(() => {
    user = { authHeader: jasmine.createSpy('authHeader').and.returnValue('Bearer tok') };
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: UserService, useValue: user },
        { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    client = TestBed.inject(HttpClient);
  });

  afterEach(() => http.verify());

  it('sets the bearer header on API requests', () => {
    client.post('/api/jobs', new FormData()).subscribe();
    const req = http.expectOne('/api/jobs');
    expect(req.request.headers.get('Authorization')).toBe('Bearer tok');
    req.flush({});
  });

  it('leaves other origins and anonymous sessions alone', () => {
    client.get('https://cdn.example/lib.js').subscribe();
    expect(http.expectOne('https://cdn.example/lib.js').request.headers.has('Authorization')).toBeFalse();

    user.authHeader.and.returnValue(undefined);  // logged out, or a share link
    client.post('/api/documents', new FormData()).subscribe();
    expect(http.expectOne('/api/documents').request.headers.has('Authorization')).toBeFalse();
  });

  it('does not overwrite a header a caller set itself', () => {
    client.get('/api/admin/users', { headers: { Authorization: 'Bearer other' } }).subscribe();
    expect(http.expectOne('/api/admin/users').request.headers.get('Authorization')).toBe('Bearer other');
  });
});

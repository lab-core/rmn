import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest, HttpParams } from '@angular/common/http';
import { Observable, throwError, timer } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { UserService } from './user.service';
import { NotificationService } from 'src/app/services/notification.service';


@Injectable({
  providedIn: 'root',
})
export class ErrorInterceptor implements HttpInterceptor {
  constructor(
    private readonly router: Router,
    private userService: UserService,
    private notificationService: NotificationService,
  ) {}

  intercept(
    req: HttpRequest<any>,
    next: HttpHandler
  ): Observable<HttpEvent<any>> {
    return next.handle(req).pipe(
      catchError((error) => {
        let warningMsg;
        if (error.status === 401) {
          warningMsg = "The http request has been intercepted as the response had a status 401 (unauthorized).";
        } else if (error.status === 404) {
          warningMsg = "The http request has been intercepted as the response had a status 404 (not found).";
        }
        if (warningMsg) {
          console.warn(warningMsg);
          const handle = (body: any) => {
            this.notificationService.showError(body?.Error ?? body?.response, "Erreur !");
            if (!this.userService.loggued()) {
              return;
            }
            if (error.status === 401 && body?.code === 'token_invalid') {
              // The session is gone (expired or revoked token). Drop it and go
              // to the login page: sending the user to '/' kept the stale
              // token, so the next request 401'd again and the redirect
              // looped forever.
              this.userService.logout();
              this.router.navigate(['/login']);
            } else {
              this.router.navigate(['/']);
            }
          };
          if (error.error instanceof Blob) {
            error.error.text().then(data => handle(JSON.parse(data)));
          } else {
            handle(error.error);
          }
        }
        // Re-throw so component error callbacks and awaited promises actually
        // observe the failure. Returning EMPTY here used to swallow every
        // error, which left `subscribe` error handlers dead and made
        // `toPromise()`/awaited calls resolve `undefined` or hang forever
        // (e.g. a failed upload never cleared its spinner).
        return throwError(() => error);
      })
    );
  }
}

@Injectable({
  providedIn: 'root',
})
export class FreshHttpInterceptor implements HttpInterceptor {
  maxRetries = 2;
  delayMs = 300;

  // This API reads through POST too (the token travels in the form body), so
  // a method check alone would retry nothing. Only requests that cannot
  // change state are retried: a mutation re-sent after a network error may
  // already have been applied (a task created twice, a grade written twice,
  // a 5 GiB upload sent three times).
  // The server's routes (under /api), as #181 named them: the old names
  // stayed here after the rename, so no read was retried any more.
  static readonly READ_ONLY_POSTS = new Set([
    'jobs', 'jobs/info', 'jobs/batch/info', 'jobs/incorrect/download',
    'documents', 'documents/download', 'documents/annotations', 'documents/last_version',
    'templates/user', 'templates/info', 'templates/download', 'templates/download/src',
    'files/download',
  ]);

  static isRetryable(req: HttpRequest<any>): boolean {
    if (req.method === 'GET' || req.method === 'HEAD') {
      return true;
    }
    if (req.method !== 'POST') {
      return false;
    }
    const path = req.url.split('?')[0].replace(/\/+/g, '/').replace(/^\/?api\//, '').replace(/^\/|\/$/g, '');
    return FreshHttpInterceptor.READ_ONLY_POSTS.has(path);
  }

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    if (!FreshHttpInterceptor.isRetryable(req)) {
      return next.handle(req);
    }
    return this.handle(req, next, 0);
  }

  private handle(req: HttpRequest<any>, next: HttpHandler, attempt: number): Observable<HttpEvent<any>> {
    let req2 = req;
    if (attempt > 0) {
      const ts = Date.now().toString();
      const updatedParams = req.params
        ? req.params.set('_ts', ts)
        : new HttpParams().set('_ts', ts);

      const headers = req.headers
        .set('Cache-Control', 'no-cache')
        .set('Pragma', 'no-cache')
        .set('Connection', 'close');

      req2 = req.clone({
        headers,
        params: updatedParams,
        withCredentials: req.withCredentials
      });
    }

    return next.handle(req2).pipe(
      catchError(error => {
        const isRetryable = error.status === 0 || error.status >= 500;
        if (isRetryable && attempt < this.maxRetries) {
          console.warn(`Retry ${attempt + 1} after error:`, error);
          return timer(this.delayMs).pipe(
            switchMap(() =>
              this.handle(req, next, attempt + 1)
            )
          );
        }

        return throwError(() => error);
      })
    );
  }
}

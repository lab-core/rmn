import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest, HttpResponse, HttpParams, HttpHeaders } from '@angular/common/http';
import { Observable, of, throwError, timer } from 'rxjs';
import { catchError, tap, switchMap } from 'rxjs/operators';
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
          if (error.error instanceof Blob) {
            error.error.text().then(data => {
              const errorMsg = JSON.parse(data).Error;
              this.notificationService.showError(errorMsg, "Erreur !");
            });
          } else {
            this.notificationService.showError(error.error.response, "Erreur !");
          }
          console.warn(warningMsg);
          if (this.userService.loggued()) {
            this.router.navigate(['/']);
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
export class CacheInterceptor implements HttpInterceptor {
  private cache = new Map<string, HttpResponse<any>>();

  intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    if (request.method !== 'GET') {
      return next.handle(request);
    }

    const cachedResponse = this.cache.get(request.url);

    if (cachedResponse) {
      return of(cachedResponse);
    }

    return next.handle(request).pipe(
      tap((event) => {
        if (event instanceof HttpResponse) {
          this.cache.set(request.url, event);
        }
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

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
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

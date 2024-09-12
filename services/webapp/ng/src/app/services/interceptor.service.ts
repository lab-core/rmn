import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest, HttpResponse } from '@angular/common/http';
import { EMPTY, Observable, of } from 'rxjs';
import { catchError, tap  } from 'rxjs/operators';
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
              let errorMsg = JSON.parse(data).Error;
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
        return EMPTY;
      })
    );
  }
}

@Injectable({
  providedIn: 'root',
})
export class CacheInterceptor implements HttpInterceptor {
  private cache = new Map<string, HttpResponse<any>>();

  intercept(request: HttpRequest<any>, next: HttpHandler) {
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

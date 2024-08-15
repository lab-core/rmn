import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest, HttpResponse } from '@angular/common/http';
import { EMPTY, Observable, of } from 'rxjs';
import { catchError, tap  } from 'rxjs/operators';
import { NotificationService } from 'src/app/services/notification.service';



@Injectable({
  providedIn: 'root',
})
export class ErrorInterceptor implements HttpInterceptor {
  constructor(
    private readonly router: Router,
    private notificationService: NotificationService,
  ) {}

  intercept(
    req: HttpRequest<any>,
    next: HttpHandler
  ): Observable<HttpEvent<any>> {
    return next.handle(req).pipe(
      catchError((error) => {
        if (error.status === 401) {
          this.notificationService.showError(error.error.response, "Erreur !")
          this.router.navigate(['/']);
          console.warn("The http request has been intercepted as the response had a status 401 (unauthorized).")
        } else if (error.status === 404) {
          this.notificationService.showError(error.error.response, "Erreur !")
          this.router.navigate(['/']);
          console.warn("The http request has been intercepted as the response had a status 404 (not found).")
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

import { Injectable } from '@angular/core';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Observable } from 'rxjs';
import { UserService } from './user.service';
import { SERVER_URL } from '../utils';

/**
 * Sends the login token as `Authorization: Bearer <token>` on every API
 * request. It used to be appended to each multipart form, which put it in any
 * request-body logging and in forty call sites; a header is set once here and
 * never reaches a foreign origin (only SERVER_URL requests get it).
 */
@Injectable({
  providedIn: 'root',
})
export class AuthInterceptor implements HttpInterceptor {
  constructor(private userService: UserService) {}

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    if (!req.url.startsWith(SERVER_URL) || req.headers.has('Authorization')) {
      return next.handle(req);
    }
    const value = this.userService.authHeader();
    if (!value) {
      return next.handle(req);
    }
    return next.handle(req.clone({ setHeaders: { Authorization: value } }));
  }
}

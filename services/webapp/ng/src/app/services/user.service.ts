import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot } from '@angular/router';
import { NotificationService } from 'src/app/services/notification.service';
import { Subject } from 'rxjs';
import { SERVER_URL } from '../utils';
import { db } from './offline-db';
import { UserRole } from '../generated/rmn-contracts';


@Injectable({
  providedIn: 'root'
})
export class UserService {

  currentUsername: string;
  private token: string;
  private shareToken: string;
  private questionIndex: string;
  role: string;
  moodleStructureInd: boolean = false;
  warningShown: boolean = true;
  /** The admin who opened this session in the user's place, if any. */
  impersonatedBy: string;
  /** A temporary password to replace: the server refuses everything else until then. */
  mustChangePassword: boolean = false;
  /** Fires after logout(): the socket and the pdf cache drop the previous
   *  user's state on it (they used to survive into the next session). */
  readonly loggedOut$ = new Subject<void>();

  constructor(private http: HttpClient,
              private router: Router,
              private notificationService: NotificationService) {

    this.currentUsername = localStorage.getItem('user_id')
    this.role = localStorage.getItem('role')
    this.token = localStorage.getItem('token')
    this.impersonatedBy = localStorage.getItem('impersonated_by') ?? undefined
    this.mustChangePassword = localStorage.getItem('must_change_password') == 'true'

    const moodleInd = localStorage.getItem('moodleStructureInd')
    this.moodleStructureInd = (moodleInd && moodleInd != "undefined") ? JSON.parse(localStorage.getItem('moodleStructureInd')) : false
  }

  private setShareToken(queryParams): void {
    this.clearShareToken();
    if (queryParams.token) {
      this.shareToken = queryParams.token;
      this.questionIndex = queryParams.question_index;
    }
  }

  private clearShareToken(): void {
    this.shareToken = undefined;
    this.questionIndex = undefined;
  }

  /** Credentials that belong in the body: the share token of a share link, or
   *  the user id the server checks against the token. The token itself goes in
   *  the Authorization header (AuthInterceptor, authHeader()). */
  addTokens(form) {
    if (this.shareToken) {
      form.append('share_token', this.shareToken);
      if (this.questionIndex) {
        form.append('question_index', this.questionIndex);
      }
    } else if (this.token) {
      form.append('user_id', this.currentUsername);
    }
  }

  /** Value of the Authorization header for API requests, or undefined when
   *  there is no session or a share link is in use (the share token travels in
   *  the form, and a logged-in user on a share link acts as the link). */
  authHeader(): string | undefined {
    if (this.shareToken || !this.token) {
      return undefined;
    }
    return `Bearer ${this.token}`;
  }

  addShareToken(queryParams) {
    queryParams['token'] = this.shareToken;
  }

  // credentials sent on the socket handshake so the server can authenticate the
  // connection and authorize room joins
  getSocketAuth() {
    if (this.shareToken) {
      return { share_token: this.shareToken };
    }
    return { user_id: this.currentUsername, token: this.token };
  }

  async login(username, password) {
    const formdata: FormData = new FormData();
    formdata.append('username', username);
    formdata.append('password', password);
    const url = SERVER_URL + "users/login"
    const resp = await this.http.post(url, formdata).toPromise();
    //Insert loading bar condition
    this.setSession(resp['response']);
    this.warningShown = false;
  }

  /** Keep a session (the answer of login or impersonate) here and in localStorage. */
  private setSession(response) {
    localStorage.setItem('user_id', response['username'])
    localStorage.setItem('role', response['role'])
    localStorage.setItem('token', response['token'])
    localStorage.setItem('moodleStructureInd', JSON.stringify(response['moodleStructureInd']))
    this.setMustChangePassword(!!response['mustChangePassword']);
    if (response['impersonatedBy']) {
      localStorage.setItem('impersonated_by', response['impersonatedBy'])
    } else {
      localStorage.removeItem('impersonated_by')
    }

    this.currentUsername = response['username']
    this.role = response['role']
    this.token = response['token']
    this.moodleStructureInd = response['moodleStructureInd'];
    this.impersonatedBy = response['impersonatedBy'] ?? undefined;
  }

  private setMustChangePassword(value: boolean) {
    this.mustChangePassword = value;
    if (value) {
      localStorage.setItem('must_change_password', 'true');
    } else {
      localStorage.removeItem('must_change_password');
    }
  }

  /** The temporary password was replaced: the session is a full one again. */
  passwordChanged() {
    this.setMustChangePassword(false);
  }

  isAdmin(): boolean {
    return this.role == UserRole.ADMIN;
  }

  /** Gestionnaires and Administrateurs create accounts. */
  canCreateUsers(): boolean {
    return this.role == UserRole.MANAGER || this.isAdmin();
  }

  /** The roles this user may give a new account: never above a Gestionnaire's own. */
  creatableRoles(): string[] {
    if (this.isAdmin()) {
      return [UserRole.USER, UserRole.MANAGER, UserRole.ADMIN];
    }
    return this.canCreateUsers() ? [UserRole.USER, UserRole.MANAGER] : [];
  }

  /** The session as setSession() takes it back. */
  private currentSession() {
    return {
      username: this.currentUsername,
      role: this.role,
      token: this.token,
      moodleStructureInd: this.moodleStructureInd,
    };
  }

  /** Drop what belongs to the user being left: the offline pdfs, the socket rooms. */
  private leaveUser() {
    db.clearAll().catch((error) => console.error('offline database not cleared', error));
    this.loggedOut$.next();
  }

  /** Every user and their role (admins only). */
  listUsers() {
    return this.http.get(SERVER_URL + 'users/all');
  }

  /** Become ``username`` (admins only), with every right they have.
   *
   *  The admin's own session is kept aside until stopImpersonating(); when
   *  already someone else, the borrowed session is dropped and the admin's
   *  is still the one kept. */
  async impersonate(username: string) {
    const formdata: FormData = new FormData();
    this.addTokens(formdata);
    formdata.append('username', username);
    const resp = await this.http.post(SERVER_URL + 'users/impersonate', formdata).toPromise();
    const borrowed = this.impersonatedBy ? this.token : undefined;
    if (!this.impersonatedBy) {
      localStorage.setItem('admin_session', JSON.stringify(this.currentSession()));
    }
    if (borrowed) {
      this.dropToken(borrowed);
    }
    this.leaveUser();
    this.setSession(resp['response']);
    if (!this.impersonatedBy) {
      // back to the admin who started: nothing left to return to
      localStorage.removeItem('admin_session');
    }
  }

  /** Back to the admin's own session; the borrowed token is deleted. */
  stopImpersonating() {
    const saved = localStorage.getItem('admin_session');
    if (!this.impersonatedBy || !saved) {
      return;
    }
    this.dropToken(this.token);
    this.leaveUser();
    this.setSession(JSON.parse(saved));
    localStorage.removeItem('admin_session');
  }

  /** Delete a login token on the server, whatever the current session is. */
  private dropToken(token: string) {
    this.http.post(SERVER_URL + 'users/logout', new FormData(), {
      headers: { Authorization: `Bearer ${token}` },
    }).subscribe({ error: (error) => console.warn('token not deleted', error) });
  }

  logout() {
    if (this.impersonatedBy) {
      // nobody returns to a borrowed session once logged out
      this.dropToken(this.token);
    }
    localStorage.clear();
    this.token = undefined;
    this.currentUsername = undefined;
    this.role = undefined;
    this.impersonatedBy = undefined;
    this.mustChangePassword = false;
    this.clearShareToken();
    // the student pdfs kept for offline correction are the previous user's
    db.clearAll().catch((error) => console.error('offline database not cleared', error));
    this.loggedOut$.next();
  }

  signup(username, password, role) {
    const formdata: FormData = new FormData();
    this.addTokens(formdata);
    formdata.append('username', username);
    formdata.append('password', password);
    formdata.append('role', role);
    if (this.moodleStructureInd) formdata.append('moodleStructureInd', "on");
    const url = SERVER_URL + "users/signup"

    return this.http.post(url, formdata)
  }

  updateMoodleStructureInd(moodleStructureInd: boolean) {
    this.moodleStructureInd = moodleStructureInd;
    const formdata: FormData = new FormData();
    formdata.append('username', this.currentUsername);
    formdata.append('moodleStructureInd', (+moodleStructureInd).toString());
    const url = SERVER_URL + 'users/updateMoodleStructureInd';

    return this.http.put(url, formdata);
  }

  loggued(): boolean {
    return this.token != undefined;
  }

  shared(): boolean {
    return this.shareToken != undefined;
  }

  canActivateLoggued(route: ActivatedRouteSnapshot,
                     state: RouterStateSnapshot) {
    if (this.loggued()) {
      this.clearShareToken()
      // a temporary password: the profile page asks for the new one first
      if (this.mustChangePassword && !state?.url?.startsWith('/user-profile')) {
        return this.router.createUrlTree(['/user-profile']);
      }
      return true;
    } else {
      if(!this.warningShown) {
        this.notificationService.showWarning("Veuillez vous logguer.", "Attention!");
        this.warningShown = true;
      }
      return this.router.createUrlTree(['/login']);
    }
  }

  /** The admin page: a logged-in Gestionnaire or Administrateur. */
  canActivateManager(route: ActivatedRouteSnapshot,
                     state: RouterStateSnapshot) {
    const logged = this.canActivateLoggued(route, state);
    if (logged !== true) {
      return logged;
    }
    return this.canCreateUsers() ? true : this.router.createUrlTree(['/']);
  }

  canActivateShared(route: ActivatedRouteSnapshot,
                    state: RouterStateSnapshot) {
    this.setShareToken(route.queryParams);
    if(this.loggued() || this.shareToken != null) {
      return true;
    } else {
      if(!this.warningShown) {
        this.notificationService.showWarning("Vous ne pouvez pas accéder à cette page.", "Attention!");
        this.warningShown = true;
      }
      return this.router.createUrlTree(['/login']);
    }
  }
}

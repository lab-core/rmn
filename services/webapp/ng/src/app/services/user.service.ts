import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot } from '@angular/router';
import { NotificationService } from 'src/app/services/notification.service';
import { Subject } from 'rxjs';
import { SERVER_URL } from '../utils';
import { db } from './offline-db';


@Injectable({
  providedIn: 'root'
})
export class UserService {

  currentUsername: string;
  private token: string;
  private shareToken: string;
  private questionIndex: string;
  role: string;
  saveVerifiedImages: boolean = false;
  moodleStructureInd: boolean = false;
  warningShown: boolean = true;
  /** Fires after logout(): the socket and the pdf cache drop the previous
   *  user's state on it (they used to survive into the next session). */
  readonly loggedOut$ = new Subject<void>();

  constructor(private http: HttpClient,
              private router: Router,
              private notificationService: NotificationService) {

    this.currentUsername = localStorage.getItem('user_id')
    this.role = localStorage.getItem('role')
    this.token = localStorage.getItem('token')

    const saveImages = localStorage.getItem('saveVerifiedImages')
    this.saveVerifiedImages = (saveImages && saveImages != "undefined") ? JSON.parse(localStorage.getItem('saveVerifiedImages')) : false

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
    const url = SERVER_URL + "login"
    const resp = await this.http.post(url, formdata).toPromise();
    //Insert loading bar condition
    const response = resp['response']
    localStorage.setItem('user_id', response['username'])
    localStorage.setItem('role', response['role'])
    localStorage.setItem('token', response['token'])
    localStorage.setItem('saveVerifiedImages', JSON.stringify(response['saveVerifiedImages']))
    localStorage.setItem('moodleStructureInd', JSON.stringify(response['moodleStructureInd']))

    this.currentUsername = response['username']
    this.role = response['role']
    this.token = response['token']
    this.saveVerifiedImages = response['saveVerifiedImages'];
    this.moodleStructureInd = response['moodleStructureInd'];
    this.warningShown = false;
  }

  logout() {
    localStorage.clear();
    this.token = undefined;
    this.currentUsername = undefined;
    this.role = undefined;
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
    if (this.saveVerifiedImages) formdata.append('saveVerifiedImages', "on");
    if (this.moodleStructureInd) formdata.append('moodleStructureInd', "on");
    const url = SERVER_URL + "signup"

    return this.http.post(url, formdata)
  }

  updateSaveVerifiedImagesValue(saveVerifiedImages: boolean) {
    this.saveVerifiedImages = saveVerifiedImages;
    const formdata: FormData = new FormData();
    formdata.append('username', this.currentUsername);
    formdata.append('saveVerifiedImages', (+saveVerifiedImages).toString());
    const url = SERVER_URL + 'updateSaveVerifiedImages';

    return this.http.put(url, formdata);
  }

  updateMoodleStructureInd(moodleStructureInd: boolean) {
    this.moodleStructureInd = moodleStructureInd;
    const formdata: FormData = new FormData();
    formdata.append('username', this.currentUsername);
    formdata.append('moodleStructureInd', (+moodleStructureInd).toString());
    const url = SERVER_URL + 'updateMoodleStructureInd';

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
      return true;
    } else {
      if(!this.warningShown) {
        this.notificationService.showWarning("Veuillez vous logguer.", "Attention!");
        this.warningShown = true;
      }
      return this.router.createUrlTree(['/login']);
    }
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

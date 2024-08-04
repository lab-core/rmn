import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot } from '@angular/router';
import { NotificationService } from 'src/app/services/notification.service';
import { SERVER_URL } from '../utils';


@Injectable({
  providedIn: 'root'
})
export class UserService {

  currentUsername: string;
  private token: string;
  private shareToken: string;
  questionIndex: string;
  role: string;
  saveVerifiedImages: boolean = false;
  moodleStructureInd: boolean = false;
  warningShown: boolean = false;

  constructor(private http: HttpClient,
              private router: Router,
              private notificationService: NotificationService) {

    this.currentUsername = localStorage.getItem('user_id')
    this.role = localStorage.getItem('role')
    this.token = localStorage.getItem('token')

    let saveImages = localStorage.getItem('saveVerifiedImages')
    this.saveVerifiedImages = (saveImages && saveImages != "undefined") ? JSON.parse(localStorage.getItem('saveVerifiedImages')) : false

    let moodleInd = localStorage.getItem('moodleStructureInd')
    this.moodleStructureInd = (moodleInd && moodleInd != "undefined") ? JSON.parse(localStorage.getItem('moodleStructureInd')) : false
  }

  private setShareToken(queryParams: any): void {
    if (queryParams.token) {
      this.shareToken = queryParams.token;
      this.questionIndex = queryParams.question_index;
    }
  }

  addTokens(form) {
    if (this.token) {
      form.append('user_id', this.currentUsername);
      form.append('token', this.token);
    }
    if (this.shareToken) {
      form.append('share_token', this.shareToken);
      if (this.questionIndex) {
        form.append('question_index', this.questionIndex);
      }
    }
  }

  async login(username, password) {
    const formdata: FormData = new FormData();
    formdata.append('username', username);
    formdata.append('password', password);
    let url = SERVER_URL + "login"
    let resp = await this.http.post(url, formdata).toPromise();
    //Insert loading bar condition
    let response = resp['response']
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
  }

  signup(username, password, role) {
    const formdata: FormData = new FormData();
    formdata.append('token', this.token);
    formdata.append('username', username);
    formdata.append('password', password);
    formdata.append('role', role);
    if (this.saveVerifiedImages) formdata.append('saveVerifiedImages', "on");
    if (this.moodleStructureInd) formdata.append('moodleStructureInd', "on");
    let url = SERVER_URL + "signup"

    return this.http.post(url, formdata)
  }

  updateSaveVerifiedImagesValue(saveVerifiedImages: boolean) {
    this.saveVerifiedImages = saveVerifiedImages;
    const formdata: FormData = new FormData();
    formdata.append('username', this.currentUsername);
    formdata.append('token', this.token);
    formdata.append('saveVerifiedImages', (+saveVerifiedImages).toString());
    const url = SERVER_URL + 'updateSaveVerifiedImages';

    return this.http.put(url, formdata);
  }

  updateMoodleStructureInd(moodleStructureInd: boolean) {
    this.moodleStructureInd = moodleStructureInd;
    const formdata: FormData = new FormData();
    formdata.append('username', this.currentUsername);
    formdata.append('token', this.token);
    formdata.append('moodleStructureInd', (+moodleStructureInd).toString());
    const url = SERVER_URL + 'updateMoodleStructureInd';

    return this.http.put(url, formdata);
  }

  loggued(): boolean {
    return this.token != null;
  }

  canActivateLoggued(route: ActivatedRouteSnapshot,
                     state: RouterStateSnapshot) {
    if (this.loggued()) {
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

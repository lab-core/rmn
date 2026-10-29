import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { SERVER_URL } from '../utils';
import { UserService } from './user.service';

/** A row of the admin page: what /users/all says of an account. */
export interface ManagedUser {
  username: string;
  role: string;
  managers: string[];
  mustChangePassword: boolean;
  lastLogin: string | null;
  tasks: number;
}

/** The account actions and operator commands of the admin page.
 *
 *  Account actions name the account in `username`; the caller's own name
 *  goes in `user_id` (addTokens), which the server checks against the token. */
@Injectable({
  providedIn: 'root'
})
export class AdminService {

  constructor(private http: HttpClient, private userService: UserService) { }

  private form(fields: Record<string, string | string[]> = {}): FormData {
    const formdata = new FormData();
    this.userService.addTokens(formdata);
    for (const [key, value] of Object.entries(fields)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        formdata.append(key, item);
      }
    }
    return formdata;
  }

  private post(path: string, fields: Record<string, string | string[]> = {}) {
    return this.http.post(SERVER_URL + path, this.form(fields));
  }

  /** A temporary password, answered once: `{username, password}`. */
  resetPassword(username: string) {
    return this.post('users/reset_password', { username });
  }

  setRole(username: string, role: string) {
    return this.post('users/role', { username, role });
  }

  setManagers(username: string, managers: string[]) {
    return this.post('users/managers', { username, managers });
  }

  closeSessions(username: string) {
    return this.post('users/sessions/close', { username });
  }

  deleteUser(username: string) {
    return this.post('users/delete', { username });
  }

  /** The settings every user shares: `{saveVerifiedImages}`. */
  settings() {
    return this.http.get(SERVER_URL + 'manage/settings');
  }

  /** Keep, or stop keeping, the confirmed digits to retrain the recogniser. */
  setSaveVerifiedImages(on: boolean) {
    return this.post('manage/settings', { saveVerifiedImages: on ? '1' : '0' });
  }

  status() {
    return this.http.get(SERVER_URL + 'manage/status');
  }

  /** Report the storage nothing owns (and the disk usage); delete it when `clean`. */
  storageSweep(clean: boolean, includeStrays = false, includeEmptyJobs = false) {
    return this.post('manage/storage/clean', {
      dry_run: String(!clean),
      usage: String(!clean),
      include_strays: String(includeStrays),
      include_empty_jobs: String(includeEmptyJobs),
    });
  }

  deleteJobs(days: number) {
    return this.post('manage/delete/jobs', { n_days_old: String(days) });
  }

  deleteTokens(days: number) {
    return this.post('manage/delete/tokens', { n_days_old: String(days) });
  }
}

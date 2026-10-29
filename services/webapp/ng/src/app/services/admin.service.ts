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

/** A count of digits, with how many the model read and how many it read right. */
export interface DigitCount {
  n: number;
  read: number;
  correct: number;
}

/** What the digit bank holds (/manage/digit-bank `bank`). */
export interface DigitBank {
  samples: number;
  bytes: number;
  per_digit: DigitCount[];
  per_kind: Record<string, DigitCount>;
  /** What the model in use at the time read, against what the graders confirmed. */
  reading: DigitCount;
  jobs: number;
  copies: number;
  first: string | null;
  last: string | null;
  staged: { jobs: number, readings: number };
}

/** How a model reads a set of digits (process_copy.bank_eval.scores). */
export interface DigitScores {
  n: number;
  correct: number;
  accuracy: number | null;
  per_digit: { n: number, correct: number }[];
  per_kind: Record<string, { n: number, correct: number }>;
  confusion: number[][];
}

/** A model scored on the bank's test part, the whole bank and MNIST. */
export interface ModelScores {
  test: DigitScores;
  bank: DigitScores;
  mnist: DigitScores;
  /** The run that trained it, null for the shipped model. */
  model?: string | null;
}

/** A run of the trainer worker (rmn_common.digit_models). */
export interface DigitModelRun {
  run_id: string;
  action: 'train' | 'evaluate';
  status: string;
  requested_by: string;
  created: string;
  started?: string;
  finished?: string;
  error?: string;
  /** The model an evaluation scored, null for the shipped one. */
  model?: string | null;
  /** The training whose model an evaluation was asked to score (else the model in use). */
  target?: string;
  bank?: { samples: number, train: number, test: number };
  progress?: { epoch: number, epochs: number };
  results?: { model?: ModelScores, candidate?: ModelScores, current?: ModelScores };
}

/** The model the executors run, null for the shipped one. */
export interface ActiveModel {
  run_id: string;
  activated_at: string;
  activated_by: string;
}

/** The latest scores of the model in use, from an evaluation of it or a training
 *  that scored it (the one that wrote it, or one compared with it). */
export interface ModelEvaluation {
  run_id: string;
  action: 'train' | 'evaluate';
  finished: string;
  scores: ModelScores;
}

export interface DigitBankOverview {
  bank: DigitBank;
  active: ActiveModel | null;
  evaluation?: ModelEvaluation | null;
  runs: DigitModelRun[];
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

  /** The digit bank, the model in use and the trainer's latest runs. */
  digitBank() {
    return this.http.get<{ response: DigitBankOverview }>(SERVER_URL + 'manage/digit-bank');
  }

  /** Have the trainer worker retrain the model on the bank, or score a model:
   *  the one in use, or with `target` the one a training wrote. */
  runDigitModel(action: 'train' | 'evaluate', target?: string) {
    return this.post('manage/digit-bank/run', target ? { action, target } : { action });
  }

  /** Have the executors run a trained model; an empty `runId` is the shipped one. */
  activateDigitModel(runId: string) {
    return this.http.post<{ response: DigitBankOverview }>(
      SERVER_URL + 'manage/digit-bank/activate', this.form({ run_id: runId }));
  }

  /** Forget a finished run; a training's model goes with it (never the one in use). */
  deleteDigitModelRun(runId: string) {
    return this.http.post<{ response: DigitBankOverview }>(
      SERVER_URL + 'manage/digit-bank/delete', this.form({ run_id: runId }));
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

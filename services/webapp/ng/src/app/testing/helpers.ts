/**
 * Shared doubles for the component specs: the Material modules the templates
 * use, spies for the notification/dialog services, a fake Socket.IO client and
 * stub components for the heavy children (main menu, pdf viewer).
 */
import { Component, EventEmitter, Input, Output, forwardRef } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatListModule } from '@angular/material/list';
import { MatPaginatorModule } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSortModule } from '@angular/material/sort';
import { MatStepperModule } from '@angular/material/stepper';
import { MatTableModule } from '@angular/material/table';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Subject, of } from 'rxjs';

import { NotificationService } from '../services/notification.service';
import { PDFViewerComponent } from '../components/pdf-viewer/pdf-viewer.component';
import { UserRole } from '../generated/rmn-contracts';

/** Everything the templates need from Material, plus forms and no-op animations. */
export const MATERIAL_MODULES = [
  MatButtonModule, MatButtonToggleModule, MatCardModule, MatCheckboxModule, MatDialogModule,
  MatFormFieldModule, MatIconModule, MatInputModule, MatListModule, MatPaginatorModule,
  MatProgressSpinnerModule, MatSelectModule, MatSlideToggleModule, MatSortModule,
  MatStepperModule, MatTableModule, FormsModule, ReactiveFormsModule, NoopAnimationsModule,
];

export function notificationSpy(): jasmine.SpyObj<NotificationService> {
  return jasmine.createSpyObj<NotificationService>(
    'NotificationService', ['showSuccess', 'showError', 'showInfo', 'showWarning']);
}

export function dialogRefSpy(): jasmine.SpyObj<MatDialogRef<any>> {
  return jasmine.createSpyObj<MatDialogRef<any>>('MatDialogRef', ['close']);
}

/** A logged-in user ("alice") whose credentials go on every form. */
export function userServiceStub(overrides: Record<string, any> = {}): any {
  return {
    currentUsername: 'alice',
    role: UserRole.USER,
    saveVerifiedImages: false,
    moodleStructureInd: false,
    loggued: () => true,
    shared: () => false,
    addTokens: (form: FormData) => {
      form.append('user_id', 'alice');
    },
    authHeader: () => 'Bearer tok',
    addShareToken: (params: any) => { params.token = 'share-1'; },
    getSocketAuth: () => ({ user_id: 'alice', token: 'tok' }),
    loggedOut$: new Subject<void>(),
    logout: jasmine.createSpy('logout'),
    login: jasmine.createSpy('login').and.resolveTo(undefined),
    signup: jasmine.createSpy('signup').and.returnValue(of({})),
    updateSaveVerifiedImagesValue: jasmine.createSpy('updateSaveVerifiedImagesValue').and.returnValue(of({})),
    updateMoodleStructureInd: jasmine.createSpy('updateMoodleStructureInd').and.returnValue(of({})),
    ...overrides,
  };
}

/** Minimal socket.io client: records handlers so tests can fire server events. */
export class FakeSocket {
  handlers: Record<string, (payload: any) => void> = {};
  emit = jasmine.createSpy('emit');
  on(name: string, handler: (payload: any) => void) { this.handlers[name] = handler; }
  off(name: string, handler?: (payload: any) => void) {
    if (handler === undefined || this.handlers[name] === handler) {
      delete this.handlers[name];
    }
  }
  async fire(name: string, payload: any) { await this.handlers[name]?.(payload); }
}

/** SocketService double: join/leave/on/off spies over one FakeSocket. */
export function socketServiceStub(): any {
  const socket = new FakeSocket();
  return {
    socket,
    join: jasmine.createSpy('join'),
    leave: jasmine.createSpy('leave'),
    on: jasmine.createSpy('on').and.callFake((name: string, handler: any) => { socket.on(name, handler); return handler; }),
    off: jasmine.createSpy('off').and.callFake((name: string, handler: any) => socket.off(name, handler)),
    getSocket: () => socket,
    disconnect: jasmine.createSpy('disconnect'),
  };
}

/** ActivatedRoute with the given query parameters and route parameters. */
export function routeStub(queryParams: Record<string, any> = {}, params: Record<string, any> = {}): any {
  return { snapshot: { queryParams, params }, params: of(params), queryParams: of(queryParams) };
}

/** Flush the pending promise chain of an async lifecycle hook. */
export async function settle(times = 3) {
  for (let i = 0; i < times; i++) {
    await new Promise(resolve => setTimeout(resolve));
  }
}

/** Poll until `condition` holds (IndexedDB and file readers finish on their own clock). */
export async function waitUntil(condition: () => boolean, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) {
      throw new Error('waitUntil: condition still false after ' + timeoutMs + ' ms');
    }
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

@Component({ selector: 'app-main-menu', template: '', standalone: false })
export class MainMenuStubComponent {}

@Component({
  selector: 'app-pdf-viewer',
  template: '<span class="pdf-stub">{{ pdfUrl }}</span>',
  standalone: false,
  // lets `@ViewChild(PDFViewerComponent)` in the host resolve to this stub
  providers: [{ provide: PDFViewerComponent, useExisting: forwardRef(() => PdfViewerStubComponent) }],
})
export class PdfViewerStubComponent {
  @Input() pdfUrl: string;
  @Input() hideToolbar = false;
  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();
  renderAnnotations = jasmine.createSpy('renderAnnotations');
  getAnnotations = jasmine.createSpy('getAnnotations').and.returnValue([]);
  getRenderedPdfFile = jasmine.createSpy('getRenderedPdfFile').and.resolveTo(undefined);
  isWriting() { return false; }
}

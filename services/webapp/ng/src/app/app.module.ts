// modules
import { HTTP_INTERCEPTORS, provideHttpClient, withInterceptors, withInterceptorsFromDi, withXhr } from '@angular/common/http';
import { CSP_NONCE, NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialogModule } from '@angular/material/dialog';
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
import { BrowserModule } from '@angular/platform-browser';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { NgSelectModule } from '@ng-select/ng-select';
import { NgxExtendedPdfViewerModule } from 'ngx-extended-pdf-viewer';
import { ToastrModule } from 'ngx-toastr';
import { AppRoutingModule } from './app-routing.module';

// components
import { AppComponent } from './components/app/app.component';
import { ChangePasswordDialogComponent } from './components/change-password-dialog/change-password-dialog.component';
import { CreateUserDialogComponent } from './components/create-user-dialog/create-user-dialog.component';
import { CsvUpdateDialogComponent } from './components/csv-update/csv-update-dialog.component';
import { DashboardPageComponent } from './components/dashboard-page/dashboard-page.component';
import { LoginPageComponent } from './components/login-page/login-page.component';
import { MainMenuComponent } from './components/main-menu/main-menu.component';
import { MatriculeVerificationComponent } from './components/matricule-verification/matricule-verification.component';
import { NewExamCorrectionComponent } from './components/new-exam-correction/new-exam-correction.component';
import { NewTemplateDialogComponent } from './components/new-template-dialog/new-template-dialog.component';
import { PdfManagementDialogComponent } from './components/pdf-management/pdf-management-dialog.component';
import { PDFViewerComponent } from './components/pdf-viewer/pdf-viewer.component';
import { PresentationPageComponent } from './components/presentation-page/presentation-page.component';
import { TaskFilesDialogComponent } from './components/task-files-dialog/task-files-dialog.component';
import { TaskRetryDialogComponent } from './components/task-retry-dialog/task-retry-dialog.component';
import { TaskShareDialogComponent } from './components/task-share-dialog/task-share-dialog.component';
import { TaskVerificationComponent } from './components/task-verification/task-verification.component';
import { TasksHistoryComponent } from './components/tasks-history/tasks-history.component';
import { TemplateEditorComponent } from './components/template-editor/template-editor.component';
import { TemplatesPageComponent } from './components/templates-page/templates-page.component';
import { UserGuideComponent } from './components/user-guide/user-guide.component';
import { UserProfileComponent } from './components/user-profile/user-profile.component';
import { WarningDialogComponent } from './components/warning-dialog/warning-dialog.component';

// providers
import { CacheInterceptor, ErrorInterceptor, FreshHttpInterceptor } from './services/interceptor.service';

@NgModule({ declarations: [
        AppComponent,
        LoginPageComponent,
        MainMenuComponent,
        TasksHistoryComponent,
        TaskFilesDialogComponent,
        TaskShareDialogComponent,
        UserProfileComponent,
        ChangePasswordDialogComponent,
        CreateUserDialogComponent,
        CsvUpdateDialogComponent,
        PDFViewerComponent,
        TaskVerificationComponent,
        PdfManagementDialogComponent,
        TemplatesPageComponent,
        NewTemplateDialogComponent,
        TemplateEditorComponent,
        PresentationPageComponent,
        UserGuideComponent,
        NewExamCorrectionComponent,
        TaskRetryDialogComponent,
        DashboardPageComponent,
        MatriculeVerificationComponent,
        WarningDialogComponent,
    ],
    bootstrap: [AppComponent], imports: [BrowserModule,
        AppRoutingModule,
        BrowserAnimationsModule,
        MatCardModule,
        MatButtonModule,
        MatIconModule,
        MatTableModule,
        MatCheckboxModule,
        MatPaginatorModule,
        MatSortModule,
        MatProgressSpinnerModule,
        MatListModule,
        FormsModule,
        MatFormFieldModule,
        MatSelectModule,
        MatStepperModule,
        MatInputModule,
        NgSelectModule,
        MatButtonToggleModule,
        MatSlideToggleModule,
        MatDialogModule,
        ReactiveFormsModule,
        NgxExtendedPdfViewerModule,
        ToastrModule.forRoot({
          preventDuplicates: true,
        }),
      ], providers: [
        // {
        //   provide: CSP_NONCE,
        //   useValue: 'random_nonce_value'
        // },
        provideHttpClient(withXhr(), withInterceptorsFromDi()),
        { provide: HTTP_INTERCEPTORS, useClass: CacheInterceptor, multi: true },
        { provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true },
        { provide: HTTP_INTERCEPTORS, useClass: FreshHttpInterceptor, multi: true },  // should be applied before ErrorInterceptor (in reverse for multi=true)
    ] })
export class AppModule { }

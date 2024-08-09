// modules
import { BrowserModule } from '@angular/platform-browser';
import { HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { CSP_NONCE, NgModule } from '@angular/core';
import { AppRoutingModule } from './app-routing.module';
import { MatCardModule } from "@angular/material/card";
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { FormsModule } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule } from '@angular/material/paginator';
import { MatSortModule } from '@angular/material/sort';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatInputModule } from '@angular/material/input';
import { MatDialogModule } from '@angular/material/dialog';
import { ToastrModule } from 'ngx-toastr';
import { NgSelectModule } from '@ng-select/ng-select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { ReactiveFormsModule } from '@angular/forms';
import { MatStepperModule } from '@angular/material/stepper';
import { MatListModule } from '@angular/material/list';
import { NgxExtendedPdfViewerModule } from 'ngx-extended-pdf-viewer';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

// components
import { AppComponent } from './components/app/app.component';
import { LoginPageComponent } from './components/login-page/login-page.component';
import { MainMenuComponent } from './components/main-menu/main-menu.component';
import { TasksHistoryComponent } from './components/tasks-history/tasks-history.component';
import { TaskFilesDialogComponent } from './components/tasks-history/task-files-dialog/task-files-dialog.component';
import { UserProfileComponent } from './components/user-profile/user-profile.component';
import { ChangePasswordDialogComponent } from './components/user-profile/change-password-dialog/change-password-dialog.component';
import { CreateUserDialogComponent } from './components/user-profile/create-user-dialog/create-user-dialog.component';
import { PDFViewerComponent } from './components/pdf-viewer/pdf-viewer.component';
import { TaskVerificationComponent } from './components/task-verification/task-verification.component';
import { ValidationWarningDialogComponent } from './components/task-verification/validation-warning-dialog/validation-warning-dialog.component';
import { TemplatesPageComponent } from './components/templates-page/templates-page.component';
import { NewTemplateDialogComponent } from './components/templates-page/new-template-dialog/new-template-dialog.component';
import { TemplateEditorComponent } from './components/template-editor/template-editor.component';
import { DeleteTemplateDialogComponent } from './components/templates-page/delete-template-dialog/delete-template-dialog.component';
import { PresentationPageComponent } from './components/presentation-page/presentation-page.component';
import { UserGuideComponent } from './components/user-guide/user-guide.component';
import { TaskShareDialogComponent } from "./components/tasks-history/task-share-dialog/task-share-dialog.component";
import { NewExamCorrectionComponent } from './components/new-exam-correction/new-exam-correction.component';
import { TaskRetryDialogComponent } from './components/tasks-history/task-retry-dialog/task-retry-dialog.component';
import { DashboardPageComponent } from './components/dashboard-page/dashboard-page.component';
import { MatriculeVerificationComponent } from './components/matricule-verification/matricule-verification.component';

// providers
import { RequestInterceptor } from './services/interceptor.service';


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
        PDFViewerComponent,
        TaskVerificationComponent,
        ValidationWarningDialogComponent,
        TemplatesPageComponent,
        NewTemplateDialogComponent,
        TemplateEditorComponent,
        DeleteTemplateDialogComponent,
        PresentationPageComponent,
        UserGuideComponent,
        NewExamCorrectionComponent,
        TaskRetryDialogComponent,
        DashboardPageComponent,
        MatriculeVerificationComponent,
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
        MatDialogModule,
        MatFormFieldModule,
        MatSelectModule,
        MatStepperModule,
        MatInputModule,
        NgSelectModule,
        MatButtonToggleModule,
        MatSlideToggleModule,
        ReactiveFormsModule,
        NgxExtendedPdfViewerModule,
        ToastrModule.forRoot()], providers: [
        // {
        //   provide: CSP_NONCE,
        //   useValue: 'random_nonce_value'
        // },
        {
            provide: HTTP_INTERCEPTORS,
            useClass: RequestInterceptor,
            multi: true,
        },
        provideHttpClient(withInterceptorsFromDi())
    ] })
export class AppModule { }

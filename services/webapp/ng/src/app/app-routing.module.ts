import { inject, NgModule } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, RouterModule, RouterStateSnapshot, Routes } from '@angular/router';
import { DashboardPageComponent } from './components/dashboard-page/dashboard-page.component';
import { LoginPageComponent } from './components/login-page/login-page.component';
import { MainMenuComponent } from './components/main-menu/main-menu.component';
import { MatriculeVerificationComponent } from './components/matricule-verification/matricule-verification.component';
import { NewExamCorrectionComponent } from './components/new-exam-correction/new-exam-correction.component';
import { PresentationPageComponent } from './components/presentation-page/presentation-page.component';
import { TaskVerificationComponent } from './components/task-verification/task-verification.component';
import { TasksHistoryComponent } from './components/tasks-history/tasks-history.component';
import { TemplateEditorComponent } from './components/template-editor/template-editor.component';
import { TemplatesPageComponent } from './components/templates-page/templates-page.component';
import { UserGuideComponent } from './components/user-guide/user-guide.component';
import { UserProfileComponent } from './components/user-profile/user-profile.component';
import { UserService } from './services/user.service';

const canActivateLoggued: CanActivateFn = (
  route: ActivatedRouteSnapshot,
  state: RouterStateSnapshot,
) => {
  return inject(UserService).canActivateLoggued(route, state);
};

const canActivateShared: CanActivateFn = (
  route: ActivatedRouteSnapshot,
  state: RouterStateSnapshot,
) => {
  return inject(UserService).canActivateShared(route, state);
};

// This is my case
const routes: Routes = [
    {
        path: '',
        component : TasksHistoryComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'tasks-history',
        redirectTo : '',
    },
    {
        path: 'main-menu',
        redirectTo : '',
    },
    {
      path : 'login',
      component : LoginPageComponent,
    },
    {
        path: 'dashboard',
        component : DashboardPageComponent,
        canActivate: [canActivateShared],
    },
    {
        path: 'dashboard/:taskId',
        component : DashboardPageComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'templates',
        component : TemplatesPageComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'template-editor',
        component : TemplateEditorComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'task-validation',
        component: TaskVerificationComponent,
        canActivate: [canActivateShared],
    },
    {
        path: 'task-validation/:job_id',
        component : TaskVerificationComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'task-validation/:job_id/:index',
        component : TaskVerificationComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'matricule-validation',
        component: MatriculeVerificationComponent,
        canActivate: [canActivateShared],
    },
    {
        path: 'matricule-validation/:job_id',
        component: MatriculeVerificationComponent,
        canActivate: [canActivateLoggued],
    },
    // {
    //     path: 'presentation-page',
    //     component : PresentationPageComponent,
    //     canActivate: [UserService]
    // },
    {
        path: 'new-exam-correction',
        component : NewExamCorrectionComponent,
        canActivate: [canActivateLoggued],
    },
    {
        // the wizard opened on an existing task: same screen, prefilled
        path: 'new-exam-correction/:from',
        component : NewExamCorrectionComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'user-profile',
        component : UserProfileComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: 'user-guide',
        component : UserGuideComponent,
        canActivate: [canActivateLoggued],
    },
    {
        path: '**',
        redirectTo : 'login',
    },
];

@NgModule({
  imports: [RouterModule.forRoot(routes, {
      // onSameUrlNavigation: 'reload'
  })],
  exports: [RouterModule],
})

export class AppRoutingModule { }

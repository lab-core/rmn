import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LoginPageComponent } from './components/login-page/login-page.component';
import { MainMenuComponent } from './components/main-menu/main-menu.component';
import { NewCorrectionComponent } from './components/new-correction/new-correction.component';
import { TasksHistoryComponent } from './components/tasks-history/tasks-history.component';
import { TemplatesPageComponent } from './components/templates-page/templates-page.component';
import { TemplateEditorComponent } from './components/template-editor/template-editor.component';
import { TaskVerificationComponent } from './components/task-verification/task-verification.component';
import { PresentationPageComponent } from './components/presentation-page/presentation-page.component';
import { UserProfileComponent } from './components/user-profile/user-profile.component';
import { UserGuideComponent } from './components/user-guide/user-guide.component';
import { UserService } from './services/user.service';


// This is my case
const routes: Routes = [
    {
        path : '',
        component : LoginPageComponent
    },
    {
        path: 'tasks-history',
        component : TasksHistoryComponent,
        canActivate: [UserService]
    },
    {
        path: 'new-correction',
        component : NewCorrectionComponent,
        canActivate: [UserService]
    },
    {
        path: 'templates',
        component : TemplatesPageComponent,
        canActivate: [UserService]
    },
    {
        path: 'template-editor',
        component : TemplateEditorComponent,
        canActivate: [UserService]
    },
    {
        path: 'task-validation',
        component : TaskVerificationComponent,
        canActivateChild: [UserService]
    },
    {
        path: 'presentation-page',
        component : PresentationPageComponent,
        canActivate: [UserService]
    },
    {
        path: 'user-profile',
        component : UserProfileComponent,
        canActivate: [UserService]
    },
    {
        path: 'user-guide',
        component : UserGuideComponent,
        canActivate: [UserService]
    },
    {
        path: '**',
        redirectTo : 'tasks-history',
        canActivate: [UserService]
    },
    {
        path: '**',
        redirectTo : ''
    }
];

@NgModule({
  imports: [RouterModule.forRoot(routes, {
      // onSameUrlNavigation: 'reload'
  })],
  exports: [RouterModule]
})

export class AppRoutingModule { }

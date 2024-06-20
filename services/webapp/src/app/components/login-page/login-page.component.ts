import { Component, HostListener, OnInit } from '@angular/core';
import { Location } from '@angular/common';
import { Router, NavigationStart } from '@angular/router';
import { filter } from 'rxjs/operators';
import { UserService } from 'src/app/services/user.service';
import { NotificationService } from 'src/app/services/notification.service';

@Component({
  selector: 'app-login-page',
  templateUrl: './login-page.component.html',
  styleUrls: ['./login-page.component.css']
})
export class LoginPageComponent implements OnInit {

  username: string = ''
  password: string = ''

  constructor(
    private location: Location,
    private router: Router,
    private userService: UserService,
    private notification: NotificationService
  ) {
    this.router.events
      .pipe(filter((event: NavigationStart) => event.navigationTrigger === 'popstate'))
      .subscribe(() => {
        if (this.router.url === '/'){
          this.router.navigateByUrl(this.router.url);
          this.location.go(this.router.url);
        }
      });
   }

  ngOnInit(): void {
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    this.attemptLogin();
  }

  checkCredential() {

  }

   attemptLogin() {
    this.userService.login(this.username, this.password).subscribe((resp) => {
      //Insert loading bar condition
      let response = resp['response']
      localStorage.setItem('user_id', response['username'])
      localStorage.setItem('role', response['role'])
      localStorage.setItem('token', response['token'])
      localStorage.setItem('saveVerifiedImages', JSON.stringify(response['saveVerifiedImages']))
      localStorage.setItem('moodleStructureInd', JSON.stringify(response['moodleStructureInd']))

      this.userService.currentUsername = response['username']
      this.userService.role = response['role']
      this.userService.token = response['token']
      this.userService.saveVerifiedImages = response['saveVerifiedImages'];
      this.userService.moodleStructureInd = response['moodleStructureInd'];
      this.router.navigate(['/main-menu']);
    }, (err) => {
      this.notification.showError(err.error.response, "Erreur de connexion")
    })

  }
}

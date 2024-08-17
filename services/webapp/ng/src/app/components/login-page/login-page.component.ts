import { Component, HostListener, OnInit, OnDestroy } from '@angular/core';
import { Location } from '@angular/common';
import { Router, NavigationStart } from '@angular/router';
import { filter, first } from 'rxjs/operators';
import { UserService } from 'src/app/services/user.service';
import { NotificationService } from 'src/app/services/notification.service';

@Component({
  selector: 'app-login-page',
  templateUrl: './login-page.component.html',
  styleUrls: ['./login-page.component.css']
})
export class LoginPageComponent implements OnInit, OnDestroy {

  username: string = ''
  password: string = ''
  subscription;

  constructor(
    private location: Location,
    private router: Router,
    private userService: UserService,
    private notification: NotificationService
  ) {
    this.subscription = this.router.events
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

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
  }

  @HostListener('document:keydown.enter', ['$event'])
  onKeydownHandler(event: KeyboardEvent) {
    this.attemptLogin();
  }

  checkCredential() {

  }

  async attemptLogin() {
     try {
      await this.userService.login(this.username, this.password);
      this.router.navigate(['/main-menu']);
    } catch(err) {
      this.notification.showError(err.error.response, "Erreur de connexion")
    }
  }
}

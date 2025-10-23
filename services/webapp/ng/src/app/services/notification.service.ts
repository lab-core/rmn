import { Injectable } from '@angular/core';
import { ToastrService } from 'ngx-toastr';

@Injectable({
  providedIn: 'root',
})
export class NotificationService {

  constructor(private toastr: ToastrService) {
  }

  showSuccess(message, title, options: any = {}) {
    console.log('Success Notification:', title, message);
    this.toastr.success(message, title, options);
  }

  showError(message, title, options: any = {}) {
    console.log('Error Notification:', title, message);
    this.toastr.error(message, title, options);
  }

  showInfo(message, title, options: any = {}) {
    console.log('Info Notification:', title, message);
    this.toastr.info(message, title, options);
  }

  showWarning(message, title, options: any = {}) {
    console.log('Warning Notification:', title, message);
    this.toastr.warning(message, title, options);
  }
}

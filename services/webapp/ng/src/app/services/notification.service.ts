import { Injectable } from '@angular/core';
import { ToastrService } from 'ngx-toastr';

@Injectable({
  providedIn: 'root',
})
export class NotificationService {

  constructor(private toastr: ToastrService) {
  }

  showSuccess(message, title, options: any = {}) {
    this.toastr.success(message, title, options);
  }

  showError(message, title, options: any = {}) {
    this.toastr.error(message, title, options);
  }

  showInfo(message, title, options: any = {}) {
    this.toastr.info(message, title, options);
  }

  showWarning(message, title, options: any = {}) {
    this.toastr.warning(message, title, options);
  }
}

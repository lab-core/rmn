import { TestBed } from '@angular/core/testing';
import { ToastrService } from 'ngx-toastr';

import { NotificationService } from './notification.service';

describe('NotificationService', () => {
  let service: NotificationService;
  let toastr: jasmine.SpyObj<ToastrService>;

  beforeEach(() => {
    toastr = jasmine.createSpyObj('ToastrService', ['success', 'error', 'info', 'warning']);
    TestBed.configureTestingModule({ providers: [{ provide: ToastrService, useValue: toastr }] });
    service = TestBed.inject(NotificationService);
    spyOn(console, 'log');
  });

  it('routes each level to the matching toast with empty options by default', () => {
    service.showSuccess('saved', 'OK');
    service.showError('failed', 'Erreur !');
    service.showInfo('fyi', 'Info');
    service.showWarning('careful', 'Attention!');

    expect(toastr.success).toHaveBeenCalledWith('saved', 'OK', {});
    expect(toastr.error).toHaveBeenCalledWith('failed', 'Erreur !', {});
    expect(toastr.info).toHaveBeenCalledWith('fyi', 'Info', {});
    expect(toastr.warning).toHaveBeenCalledWith('careful', 'Attention!', {});
  });

  it('passes toast options through', () => {
    service.showError('failed', 'Erreur !', { timeOut: 0 });
    expect(toastr.error).toHaveBeenCalledWith('failed', 'Erreur !', { timeOut: 0 });
  });
});

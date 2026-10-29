import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { TemporaryPasswordDialogComponent } from './temporary-password-dialog.component';
import { NotificationService } from 'src/app/services/notification.service';
import { MATERIAL_MODULES, dialogRefSpy, notificationSpy } from '../../testing/helpers';

describe('TemporaryPasswordDialogComponent', () => {
  let fixture: ComponentFixture<TemporaryPasswordDialogComponent>;
  let notification: jasmine.SpyObj<NotificationService>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;

  beforeEach(() => {
    notification = notificationSpy();
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [TemporaryPasswordDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: NotificationService, useValue: notification },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: MAT_DIALOG_DATA, useValue: { username: 'bob', password: 'Tmp4x!yZ9qWe' } },
      ],
    });
    fixture = TestBed.createComponent(TemporaryPasswordDialogComponent);
    fixture.detectChanges();
  });

  it('shows the password once, for the account reset', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('bob');
    expect(fixture.nativeElement.querySelector('.password').textContent).toBe('Tmp4x!yZ9qWe');
  });

  it('copies it to the clipboard', async () => {
    const write = spyOn(navigator.clipboard, 'writeText').and.resolveTo();
    await fixture.componentInstance.copy();
    expect(write).toHaveBeenCalledWith('Tmp4x!yZ9qWe');
    expect(notification.showSuccess).toHaveBeenCalled();
  });

  it('says so when the clipboard refuses', async () => {
    spyOn(navigator.clipboard, 'writeText').and.rejectWith(new Error('denied'));
    await fixture.componentInstance.copy();
    expect(notification.showWarning).toHaveBeenCalled();
  });
});

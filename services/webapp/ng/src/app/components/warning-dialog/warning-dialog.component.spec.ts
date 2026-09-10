import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { WarningDialogComponent } from './warning-dialog.component';
import { MATERIAL_MODULES, dialogRefSpy } from '../../testing/helpers';

describe('WarningDialogComponent', () => {
  let fixture: ComponentFixture<WarningDialogComponent>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;

  beforeEach(() => {
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [WarningDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: MAT_DIALOG_DATA, useValue: 'Supprimer la tâche Exam ?' },
      ],
    });
    fixture = TestBed.createComponent(WarningDialogComponent);
    fixture.detectChanges();
  });

  it('shows the question it was opened with', () => {
    expect(fixture.nativeElement.querySelector('p').textContent).toContain('Supprimer la tâche Exam ?');
  });

  it('closes with true on OUI and false on NON', () => {
    (fixture.nativeElement.querySelector('.confirm-button') as HTMLButtonElement).click();
    expect(dialogRef.close).toHaveBeenCalledWith(true);
    (fixture.nativeElement.querySelector('.cancel-button') as HTMLButtonElement).click();
    expect(dialogRef.close).toHaveBeenCalledWith(false);
  });
});

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { ConfirmDialogComponent, ConfirmData } from './confirm-dialog.component';
import { MATERIAL_MODULES, dialogRefSpy } from '../../testing/helpers';

describe('ConfirmDialogComponent', () => {
  let fixture: ComponentFixture<ConfirmDialogComponent>;
  let dialogRef: jasmine.SpyObj<MatDialogRef<any>>;

  const create = (data: ConfirmData) => {
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [ConfirmDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    fixture = TestBed.createComponent(ConfirmDialogComponent);
    fixture.detectChanges();
  };

  const click = (selector: string) => (fixture.nativeElement.querySelector(selector) as HTMLButtonElement).click();

  it('shows the question and answers true or false', () => {
    create({ title: 'Supprimer le compte', message: 'bob sera supprimé.', confirm: 'Supprimer', danger: true });
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Supprimer le compte');
    expect(text).toContain('bob sera supprimé.');
    expect(fixture.nativeElement.querySelector('mat-icon.danger')).not.toBeNull();
    click('.confirm');
    expect(dialogRef.close).toHaveBeenCalledWith(true);
    click('.cancel');
    expect(dialogRef.close).toHaveBeenCalledWith(false);
  });

  it('says Confirmer when no label is given', () => {
    create({ title: 'Changer le rôle', message: 'bob deviendra Gestionnaire.' });
    expect(fixture.nativeElement.querySelector('.confirm').textContent.trim()).toBe('Confirmer');
    expect(fixture.nativeElement.querySelector('mat-icon.danger')).toBeNull();
  });
});

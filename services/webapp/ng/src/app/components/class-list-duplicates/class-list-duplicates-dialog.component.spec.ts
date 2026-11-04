import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef, MatDialogConfig } from '@angular/material/dialog';
import { of } from 'rxjs';

import {
  ClassListDuplicatesData, ClassListDuplicatesDialogComponent, askClassListAssignments,
} from './class-list-duplicates-dialog.component';
import { MATERIAL_MODULES, dialogRefSpy } from '../../testing/helpers';

describe('ClassListDuplicatesDialogComponent', () => {
  let fixture: ComponentFixture<ClassListDuplicatesDialogComponent>;
  let component: ClassListDuplicatesDialogComponent;
  let dialogRef: jasmine.SpyObj<MatDialogRef<unknown>>;
  const data: ClassListDuplicatesData = {
    duplicates: [
      { matricule: '2345678', name: 'Bob B', lists: ['A', 'B'] },
      { matricule: '3456789', name: 'Carl C', lists: ['A', 'C'] },
    ],
  };

  beforeEach(() => {
    dialogRef = dialogRefSpy();
    TestBed.configureTestingModule({
      declarations: [ClassListDuplicatesDialogComponent],
      imports: MATERIAL_MODULES,
      providers: [
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    fixture = TestBed.createComponent(ClassListDuplicatesDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  const confirmButton = () => fixture.nativeElement.querySelector('.confirm') as HTMLButtonElement;

  it('lists each student with their lists and asks to fix the files', () => {
    const rows = Array.from(fixture.nativeElement.querySelectorAll('tbody tr') as NodeListOf<HTMLElement>);
    expect(rows.map((r) => r.textContent)).toEqual([
      jasmine.stringContaining('2345678'), jasmine.stringContaining('3456789')]);
    expect(fixture.nativeElement.textContent).toContain('Corrigez les fichiers Moodle');
    expect(confirmButton().disabled).toBeTrue();
  });

  it('closes with a list for every student, and only then', () => {
    component.assignments['2345678'] = 'B';
    component.confirm();
    expect(dialogRef.close).not.toHaveBeenCalled();
    component.assignments['3456789'] = 'B';  // not one of his
    expect(component.complete()).toBeFalse();
    component.assignments['3456789'] = 'C';
    fixture.detectChanges();
    expect(confirmButton().disabled).toBeFalse();
    confirmButton().click();
    expect(dialogRef.close).toHaveBeenCalledWith({ '2345678': 'B', '3456789': 'C' });
  });

  it('closes with nothing when cancelled', () => {
    (fixture.nativeElement.querySelector('.cancel') as HTMLButtonElement).click();
    expect(dialogRef.close).toHaveBeenCalledWith(undefined);
  });
});

describe('askClassListAssignments', () => {
  const duplicates = [{ matricule: '1', name: 'X', lists: ['A', 'B'] }];

  it('opens the dialog on a 409 naming duplicates and returns the choice', async () => {
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dialog.open.and.returnValue({ afterClosed: () => of({ '1': 'A' }) } as unknown as MatDialogRef<unknown>);
    expect(await askClassListAssignments(dialog, { status: 409, error: { duplicates } })).toEqual({ '1': 'A' });
    expect((dialog.open.calls.mostRecent().args[1] as MatDialogConfig).data).toEqual({ duplicates });
  });

  it('returns null for any other error, without a dialog', async () => {
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    expect(await askClassListAssignments(dialog, { status: 400, error: {} })).toBeNull();
    expect(await askClassListAssignments(dialog, { status: 409, error: { duplicates: [] } })).toBeNull();
    expect(await askClassListAssignments(dialog, new Error('x'))).toBeNull();
    expect(dialog.open).not.toHaveBeenCalled();
  });
});

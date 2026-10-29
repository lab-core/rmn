import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';

import { ErrorInfoDialogComponent } from './error-info-dialog.component';

describe('ErrorInfoDialogComponent', () => {
  function create(infos: string | string[], title?: string): ComponentFixture<ErrorInfoDialogComponent> {
    TestBed.configureTestingModule({
      declarations: [ErrorInfoDialogComponent],
      imports: [MatDialogModule],
      providers: [{provide: MAT_DIALOG_DATA, useValue: {taskName: 'Examen', infos, title}}],
    });
    const fixture = TestBed.createComponent(ErrorInfoDialogComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('shows a single error message', () => {
    const fixture = create('Échec de la finalisation : pdflatex failed');
    const shown = fixture.nativeElement.querySelectorAll('.error-message');
    expect(shown.length).toBe(1);
    expect(shown[0].textContent).toContain('pdflatex failed');
  });

  it('is titled as an error unless told otherwise', () => {
    expect(create('x').nativeElement.querySelector('h2').textContent).toContain('Erreur : Examen');
  });

  it('takes the title it is given', () => {
    const fixture = create(['copie 1'], 'Pages de garde à vérifier');
    expect(fixture.nativeElement.querySelector('h2').textContent).toContain('Pages de garde à vérifier : Examen');
  });

  it('shows each per-copy error of a list', () => {
    const fixture = create(['copie 1 illisible', 'copie 2 illisible']);
    expect(fixture.nativeElement.querySelectorAll('.error-message').length).toBe(2);
  });
});

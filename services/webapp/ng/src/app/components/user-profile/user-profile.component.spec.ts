import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';

import { UserProfileComponent } from './user-profile.component';
import { ChangePasswordDialogComponent } from '../change-password-dialog/change-password-dialog.component';
import { CreateUserDialogComponent } from '../create-user-dialog/create-user-dialog.component';
import { UserService } from 'src/app/services/user.service';
import { MATERIAL_MODULES, MainMenuStubComponent, userServiceStub } from '../../testing/helpers';

describe('UserProfileComponent', () => {
  let fixture: ComponentFixture<UserProfileComponent>;
  let component: UserProfileComponent;
  let user: any;
  let dialog: MatDialog;

  const create = (role: string) => {
    localStorage.clear();
    user = userServiceStub({ role });
    TestBed.configureTestingModule({
      declarations: [UserProfileComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [provideRouter([]), { provide: UserService, useValue: user }],
    });
    fixture = TestBed.createComponent(UserProfileComponent);
    component = fixture.componentInstance;
    dialog = TestBed.inject(MatDialog);
    spyOn(dialog, 'open').and.returnValue({} as any);
    fixture.detectChanges();
  };

  it('shows the account and lets any user change the password', () => {
    create('Utilisateur');
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('alice');
    expect(text).toContain('Utilisateur');
    expect(fixture.nativeElement.querySelector('.profile-button')).toBeNull();

    (fixture.nativeElement.querySelector('.change-password') as HTMLButtonElement).click();
    expect(dialog.open).toHaveBeenCalledWith(ChangePasswordDialogComponent, jasmine.any(Object));
  });

  it('offers account creation to administrators only', () => {
    create('Administrateur');
    const button = fixture.nativeElement.querySelector('.profile-button') as HTMLButtonElement;
    expect(button).not.toBeNull();
    button.click();
    expect(dialog.open).toHaveBeenCalledWith(CreateUserDialogComponent, jasmine.any(Object));
  });

  it('persists the profile flags once the server accepted them', () => {
    create('Utilisateur');
    component.updateSaveVerifiedImagesValue(true);
    expect(user.updateSaveVerifiedImagesValue).toHaveBeenCalledWith(true);
    expect(user.saveVerifiedImages).toBeTrue();
    expect(localStorage.getItem('saveVerifiedImages')).toBe('true');

    component.updateSaveInMoodleStructure(false);
    expect(user.moodleStructureInd).toBeFalse();
    expect(localStorage.getItem('moodleStructureInd')).toBe('false');
  });

  it('reroute goes back to the menu', () => {
    create('Utilisateur');
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    component.reroute();
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });
});

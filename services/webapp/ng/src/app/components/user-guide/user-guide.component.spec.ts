import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { UserGuideComponent } from './user-guide.component';
import { MATERIAL_MODULES, MainMenuStubComponent } from '../../testing/helpers';

describe('UserGuideComponent', () => {
  let fixture: ComponentFixture<UserGuideComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [UserGuideComponent, MainMenuStubComponent],
      imports: MATERIAL_MODULES,
      providers: [provideRouter([])],
    });
    fixture = TestBed.createComponent(UserGuideComponent);
    fixture.detectChanges();
  });

  it('renders the guide as a stepper', () => {
    expect(fixture.nativeElement.querySelectorAll('mat-step-header').length).toBeGreaterThan(1);
  });

  it('every step control is required', () => {
    const component = fixture.componentInstance;
    for (const group of [component.firstFormGroup, component.fourthFormGroup, component.eightFormGroup]) {
      expect(group.valid).toBeFalse();
    }
    component.firstFormGroup.controls.firstCtrl.setValue('done');
    expect(component.firstFormGroup.valid).toBeTrue();
  });

  it('goes back to the menu', () => {
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.componentInstance.reroute();
    expect(router.navigate).toHaveBeenCalledWith(['/main-menu']);
  });
});

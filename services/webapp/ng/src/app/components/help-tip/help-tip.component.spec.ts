import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { HelpTipComponent } from './help-tip.component';
import { HELP } from '../../help/guide';

describe('HelpTipComponent', () => {
  function create(key: string): ComponentFixture<HelpTipComponent> {
    TestBed.configureTestingModule({imports: [HelpTipComponent, NoopAnimationsModule]});
    const fixture = TestBed.createComponent(HelpTipComponent);
    fixture.componentRef.setInput('key', key);
    fixture.detectChanges();
    return fixture;
  }

  it('links to the section of the guide in a new tab', () => {
    const anchor: HTMLAnchorElement = create('wizard.csv').nativeElement.querySelector('a');
    expect(anchor.getAttribute('href')).toBe(`/user-guide/05-nouvelle-tache#${HELP['wizard.csv'].anchor}`);
    expect(anchor.target).toBe('_blank');
    expect(anchor.getAttribute('aria-label')).toContain('formulaire d\'évaluation');
  });

  it('links to the top of a chapter without anchor', () => {
    const anchor: HTMLAnchorElement = create('dashboard.finalize').nativeElement.querySelector('a');
    expect(anchor.getAttribute('href')).toBe('/user-guide/09-finalisation');
  });

  it('does not trigger the click of what it sits in', () => {
    const fixture = create('tasks.status');
    const parent = jasmine.createSpy('parent');
    fixture.nativeElement.addEventListener('click', parent);
    const anchor: HTMLAnchorElement = fixture.nativeElement.querySelector('a');
    anchor.addEventListener('click', (event) => event.preventDefault());  // no new tab in the test
    anchor.click();
    expect(parent).not.toHaveBeenCalled();
  });

  it('refuses a key without text', () => {
    expect(() => create('nope')).toThrowError(/nope/);
  });
});

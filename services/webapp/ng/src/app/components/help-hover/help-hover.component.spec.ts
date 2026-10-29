import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { HelpHoverComponent } from './help-hover.component';
import { HELP } from '../../help/guide';

@Component({
  template: `<app-help-hover key="dashboard.read-grades"><button class="wrapped" (click)="clicked = true">Relire</button></app-help-hover>`,
  imports: [HelpHoverComponent],
})
class HostComponent {
  clicked = false;
}

describe('HelpHoverComponent', () => {
  const create = () => {
    TestBed.configureTestingModule({imports: [HostComponent, NoopAnimationsModule]});
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    return fixture;
  };

  it('keeps the button it wraps, and its click', () => {
    const fixture = create();
    (fixture.nativeElement.querySelector('.wrapped') as HTMLButtonElement).click();
    expect(fixture.componentInstance.clicked).toBeTrue();
  });

  it('links to the section of the guide in a new tab', () => {
    const anchor: HTMLAnchorElement = create().nativeElement.querySelector('.guide-link');
    const entry = HELP['dashboard.read-grades'];
    expect(anchor.getAttribute('href')).toBe(`/user-guide/${entry.chapter}#${entry.anchor}`);
    expect(anchor.target).toBe('_blank');
    expect(anchor.getAttribute('aria-label')).toContain(entry.text);
  });

  it('opening the guide does not click the button', () => {
    const fixture = create();
    const anchor: HTMLAnchorElement = fixture.nativeElement.querySelector('.guide-link');
    anchor.addEventListener('click', (event) => event.preventDefault());  // no new tab in the test
    anchor.click();
    expect(fixture.componentInstance.clicked).toBeFalse();
  });

  it('refuses a key without text', () => {
    TestBed.configureTestingModule({imports: [HelpHoverComponent, NoopAnimationsModule]});
    const fixture = TestBed.createComponent(HelpHoverComponent);
    fixture.componentRef.setInput('key', 'nope');
    expect(() => fixture.detectChanges()).toThrowError(/nope/);
  });
});

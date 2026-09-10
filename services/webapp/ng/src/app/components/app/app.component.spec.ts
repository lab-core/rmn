import { TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { RouterOutlet, provideRouter } from '@angular/router';

import { AppComponent } from './app.component';

describe('AppComponent', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [AppComponent],
      imports: [RouterOutlet],
      providers: [provideRouter([])],
    });
  });

  it('renders the router outlet and names the document', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('router-outlet')).not.toBeNull();
    expect(TestBed.inject(Title).getTitle()).toBe('RMN');
  });

  it('stops listening to the router when destroyed', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.subscription.closed).toBeFalse();
    fixture.destroy();
    expect(fixture.componentInstance.subscription.closed).toBeTrue();
  });
});

import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HELP, HelpEntry, guideLink } from '../../help/guide';

/**
 * The help of a button, shown on hover rather than by a "?" beside it.
 *
 * Wraps the button: hovering it shows the help text of `key` (see
 * help/guide.ts) and a small "?" in its corner that opens the section of the
 * guide in a new tab. The "?" bubble (app-help-tip) stays for the fields and
 * the few actions worth reading about before using them.
 */
@Component({
    selector: 'app-help-hover',
    templateUrl: './help-hover.component.html',
    styleUrls: ['./help-hover.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [MatIconModule, MatTooltipModule],
})
export class HelpHoverComponent {
  @Input({required: true}) key!: string;

  get entry(): HelpEntry {
    const entry = HELP[this.key];
    if (!entry) {
      throw new Error(`No help text for "${this.key}"`);
    }
    return entry;
  }

  get link(): string {
    return guideLink(this.entry);
  }
}

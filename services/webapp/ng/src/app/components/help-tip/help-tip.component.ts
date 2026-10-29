import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HELP, HelpEntry, guideLink } from '../../help/guide';

/**
 * A "?" next to a field: hovering shows the help text of `key` (see
 * help/guide.ts), clicking opens the section of the user guide that explains
 * it. The guide opens in a new tab so a half-filled form is not lost.
 */
@Component({
    selector: 'app-help-tip',
    templateUrl: './help-tip.component.html',
    styleUrls: ['./help-tip.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [MatIconModule, MatTooltipModule],
})
export class HelpTipComponent {
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

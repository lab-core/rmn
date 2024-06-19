import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css']
})
export class DashboardPageComponent {
  @Input() taskName: string = 'TASK_NAME';
  @Input() questions: { corrected: number, total: number }[] = [
    { corrected: 0, total: 150 },
    { corrected: 10, total: 150 },
    { corrected: 75, total: 150 }
  ];
  @Input() averages: string[] = [
    '0/5',
    '2.18/3',
    '3.47/5'
  ];

  correctQuestion() {
    console.log('Correction button clicked');
  }
}

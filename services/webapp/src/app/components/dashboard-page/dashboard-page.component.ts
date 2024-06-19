import { Component, Input } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-dashboard-page',
  templateUrl: './dashboard-page.component.html',
  styleUrls: ['./dashboard-page.component.css']
})
export class DashboardPageComponent {
  taskName: string = 'Tâche';
  questions: { corrected: number, total: number }[] = [
    { corrected: 0, total: 150 },
    { corrected: 10, total: 150 },
    { corrected: 75, total: 150 }
  ];
  averages: string[] = [
    '0/5',
    '2.18/3',
    '3.47/5'
  ];
  constructor(private router: Router) { }

  correctQuestion() {
    console.log('Correction button clicked');
  }

  shareQuestion(index: number) {
    console.log(`Share question ${index + 1}`);
  }

  reroute() {
    this.router.navigate(['/tasks-history']);
  }
}

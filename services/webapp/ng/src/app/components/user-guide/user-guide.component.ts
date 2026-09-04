import { Component, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { FormBuilder, Validators } from '@angular/forms';
import { Router } from '@angular/router';

@Component({
    selector: 'app-user-guide',
    templateUrl: './user-guide.component.html',
    styleUrls: ['./user-guide.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class UserGuideComponent implements OnInit {

  firstFormGroup;
  secondFormGroup;
  thirdFormGroup;
  fourthFormGroup;
  fifthFormGroup;
  sixthFormGroup;
  seventhFormGroup;
  eightFormGroup;

  constructor(private router: Router, private _formBuilder: FormBuilder) {
    this.firstFormGroup = this._formBuilder.group({
      firstCtrl: ['', Validators.required],
    });
    this.secondFormGroup = this._formBuilder.group({
      secondCtrl: ['', Validators.required],
    });
    this.thirdFormGroup = this._formBuilder.group({
      thirdCtrl: ['', Validators.required],
    });
    this.fourthFormGroup = this._formBuilder.group({
      fourthCtrl: ['', Validators.required],
    });
    this.fifthFormGroup = this._formBuilder.group({
      fifthCtrl: ['', Validators.required],
    });
    this.sixthFormGroup = this._formBuilder.group({
      sixthCtrl: ['', Validators.required],
    });
    this.seventhFormGroup = this._formBuilder.group({
      seventhCtrl: ['', Validators.required],
    });
    this.eightFormGroup = this._formBuilder.group({
      eightCtrl: ['', Validators.required],
    });
  }

  ngOnInit(): void {
  }
  reroute() {
    this.router.navigate(['/main-menu']);
  }

}

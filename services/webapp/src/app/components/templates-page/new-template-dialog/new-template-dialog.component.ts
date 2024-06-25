import { Component, OnInit, HostListener } from '@angular/core';
import { Router } from '@angular/router';
import { MatDialogRef } from '@angular/material/dialog';
import { TemplateService } from 'src/app/services/template.service';

@Component({
  selector: 'app-new-template-dialog',
  templateUrl: './new-template-dialog.component.html',
  styleUrls: ['./new-template-dialog.component.css']
})
export class NewTemplateDialogComponent implements OnInit {
  constructor(
    private router: Router,
    private templateService : TemplateService,
    public dialogRef: MatDialogRef<NewTemplateDialogComponent>
    ) { }

  copy: File;
  copyName: string = '';

  disabled: boolean = true;

  ngOnInit(): void {
  }

  CopyFileEvent(fileInput: Event){
    let target= fileInput.target as HTMLInputElement;
    let file: File = (target.files as FileList)[0];
    this.setCopy(file);
  }
  
  setCopy(file: File) {
    this.copy = file;
    this.copyName = file.name;
    this.checkDisabled();
  }

  checkDisabled(){
    this.disabled = !this.copyName;
  }

  async confirm() {
    this.templateService.setFile(this.copy);
    this.templateService.setEditingExisting(false);
    await this.templateService.createNewTemplate(this.copy);
    this.dialogRef.close();
    this.router.navigate(['/template-editor']);
  }

  @HostListener('dragover', ['$event']) 
  onDragOver(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
  }

  @HostListener('drop', ['$event']) 
  onDrop(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer && event.dataTransfer.files.length > 0) {
      const file = event.dataTransfer.files[0];
      this.setCopy(file);
      event.dataTransfer.clearData();
    }
  }
}

import { Component, OnInit, HostListener } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { MatDialogRef } from '@angular/material/dialog';
import { TemplateService } from 'src/app/services/template.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';


@Component({
  selector: 'app-new-template-dialog',
  templateUrl: './new-template-dialog.component.html',
  styleUrls: ['./new-template-dialog.component.css']
})
export class NewTemplateDialogComponent implements OnInit {
  constructor(
    private router: Router,
    private http: HttpClient,
    private templateService : TemplateService,
    private userService: UserService,
    public dialogRef: MatDialogRef<NewTemplateDialogComponent>
  ) {}

  copy: File;
  copyName: string = '';
  page: number = 1;

  disabled: boolean = true;
  hideWarning: boolean = true;

  ngOnInit(): void {
  }

  onFileSelected(event: any) {
    let file: File = (event.target.files as FileList)[0];
    this.setCopy(file);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer && event.dataTransfer.files.length > 0) {
      const file = event.dataTransfer.files[0];
      this.setCopy(file);
      event.dataTransfer.clearData();
    }
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
  }

  deleteFile(): void {
    this.copy = undefined;
    this.copyName = undefined;
    this.checkDisabled();
  }

  setCopy(file: File) {
    this.copy = file;
    this.copyName = file.name;
    this.checkDisabled();
  }

  setPage() {
    this.hideWarning = (this.page > 0);
    this.checkDisabled();
  }

  checkDisabled(){
    this.disabled = !this.copyName || !this.hideWarning;
  }

  selectText(event): void {
    event.target.select();
  }

  async confirm() {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('template_file', this.copy);
    formdata.append('template_page', (this.page - 1).toString());
    formdata.append('template_name', "New template");
    this.http.post<any>(`${SERVER_URL}template`, formdata).subscribe(
        (data) => {
          this.templateService.setTemplateName(data["response"]["template_name"]);
          this.templateService.setTemplateId(data["response"]["template_id"]);

          const formdata: FormData = new FormData();
          this.userService.addTokens(formdata);
          formdata.append('template_id', data["response"]["template_id"]);
           this.http.post(`${SERVER_URL}template/download`, formdata, {responseType: 'blob'}).subscribe(async data => {
              var file = new File([data], this.templateService.getTemplateName());
              this.templateService.setFile(file);
              await this.templateService.createNewTemplate(file);
              this.dialogRef.close();
              this.router.navigate(['/template-editor']);
        });
    });
  }
}

import { Component, OnInit } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { MatDialog } from '@angular/material/dialog';
import { UserService } from 'src/app/services/user.service';
import { TemplateService } from 'src/app/services/template.service';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { NewTemplateDialogComponent } from './new-template-dialog/new-template-dialog.component';
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { SERVER_URL } from 'src/app/utils';
import { filter } from 'rxjs/operators';
import { saveAs } from 'file-saver';


@Component({
  selector: 'app-templates-page',
  templateUrl: './templates-page.component.html',
  styleUrls: ['./templates-page.component.css']
})
export class TemplatesPageComponent implements OnInit {
  constructor(
    public dialog: MatDialog,
    private router: Router,
    private http: HttpClient,
    private userService: UserService,
    private templateService: TemplateService,
    private rectangleService: RectangleService
  ) {
    this.router.events
      .pipe(filter((event: NavigationStart) => event.navigationTrigger === 'popstate'))
      .subscribe(() => {
        if (this.router.url === '/templates'){
          this.reroute();
        }
      });
   }

  templatesList: Array<Map<string, string>>;
  allTemplatesList:Array<Map<string, string>>;

  filterSearch: string = '';

  async ngOnInit(): Promise<void> {
    this.getTemplates();
  }


  getTemplates() {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    this.http.post<any>(`${SERVER_URL}user/template`, formdata).subscribe(
      (data) => {
        // "template_name"
        // "template_id"
        this.templatesList = data['response'];
        this.allTemplatesList = data['response'];
      });
  }


  updateAvailableTemplates(event: KeyboardEvent) {
    if (event.key == "Backspace") {
      this.templatesList = this.allTemplatesList;
    }
    this.filterTemplates();
  }

  filterTemplates() {
    let newList:Array<Map<string, string>> = [];
    for(let template of this.allTemplatesList) {
      //filter by template name
      if(template["template_name"].toLowerCase().includes(this.filterSearch.toLowerCase())){
        newList.push(template);
      }
    }
    this.templatesList = newList;
  }


  editTemplate(template: Map<string, string>): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('template_id', template["template_id"]);
    this.http.post<any>(`${SERVER_URL}template/info`, formdata).subscribe(
      (data) => {
        this.rectangleService.setIdentificationRectCoords(data["response"]["matricule_box"]);
        this.rectangleService.setquestionsRectCoords(data["response"]["grade_box"]);

        this.templateService.setTemplateName(data["response"]["template_name"]);
        this.templateService.setTemplateId(data["response"]["template_id"]);
        this.templateService.setLocked(data["response"]["locked"]);

        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('template_id', template["template_id"]);
         this.http.post(`${SERVER_URL}template/download`, formdata, {responseType: 'blob'}).subscribe(async data => {
            var file = new File([data], this.templateService.getTemplateName());
            this.templateService.setFile(file);
            await this.templateService.createNewTemplate(file);
            this.router.navigate(['/template-editor']);
        });
    });
  }

  downloadSource(template: Map<string, string>): void {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    formdata.append('template_id', template["template_id"]);
    this.http.post(`${SERVER_URL}template/download/src`, formdata, {responseType: 'blob'}).subscribe(
      (data) => {
        const downloadURL = window.URL.createObjectURL(data);
        saveAs(downloadURL, template["src_name"]);
        URL.revokeObjectURL(downloadURL);
      },
      (error) => {
        console.error(error);
    });
  }

  openNewTemplateDialog(): void {
    this.dialog.open(NewTemplateDialogComponent, {
        width: '40%',
        height: '60%',
    })
  }


  openDeleteDialog(template: Map<string, string>): void {
    let dialogRef = this.dialog.open(WarningDialogComponent, {
      width: '40%',
      height: '50%',
      data: "Êtes-vous sur de vouloir supprimer le template?"
    })
    dialogRef.afterClosed().subscribe(async result => {
      if (result !== undefined && result === true) {
        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('template_id', template["template_id"]);
        this.http.post<any>(`${SERVER_URL}template/delete`, formdata).subscribe(
          (data) => {
            this.getTemplates();
          });
      }
    });
  }

  reroute() {
    this.router.navigate(['/main-menu']);
  }

}

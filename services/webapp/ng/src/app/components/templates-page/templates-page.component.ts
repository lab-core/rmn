import { Component, OnInit, OnDestroy } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { MatDialog } from '@angular/material/dialog';
import { UserService } from 'src/app/services/user.service';
import { TemplateService } from 'src/app/services/template.service';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { NewTemplateDialogComponent } from '../new-template-dialog/new-template-dialog.component';
import { WarningDialogComponent } from 'src/app/components/warning-dialog/warning-dialog.component';
import { SERVER_URL } from 'src/app/utils';
import { filter, first } from 'rxjs/operators';
import { saveAs } from 'file-saver';


@Component({
  selector: 'app-templates-page',
  templateUrl: './templates-page.component.html',
  styleUrls: ['./templates-page.component.css']
})
export class TemplatesPageComponent implements OnInit, OnDestroy {
  constructor(
    public dialog: MatDialog,
    private router: Router,
    private http: HttpClient,
    private userService: UserService,
    private templateService: TemplateService,
    private rectangleService: RectangleService
  ) {
    this.subscription = this.router.events
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

  subscription;

  async ngOnInit(): Promise<void> {
    this.getTemplates();

  }

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
  }


  getTemplates() {
    const formdata: FormData = new FormData();
    this.userService.addTokens(formdata);
    this.http.post<any>(`${SERVER_URL}user/template`, formdata).pipe(first()).subscribe(
      (data) => {
        // "template_name"
        // "template_id"
        this.templatesList = data['response'];
        this.allTemplatesList = data['response'];
        // load template if any id given in template service
        const templateId = this.templateService.getId();
        if (templateId) {
          const template = this.templatesList.find((temp) => temp['template_id'] === templateId);
          if (template) {
            this.editTemplate(template);
          }
        }
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
    this.http.post<any>(`${SERVER_URL}template/info`, formdata).pipe(first()).subscribe(
      (data) => {
        this.rectangleService.setIdentificationRectCoords(data["response"]["matricule_box"]);
        this.rectangleService.setquestionsRectCoords(data["response"]["grade_box"]);

        this.templateService.setName(data["response"]["template_name"]);
        this.templateService.setId(data["response"]["template_id"]);
        this.templateService.setLocked(data["response"]["locked"]);
        this.templateService.setNQuestions(data["response"]["n_questions"]);

        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('template_id', template["template_id"]);
         this.http.post(`${SERVER_URL}template/download`, formdata, {responseType: 'blob'}).pipe(first()).subscribe(async data => {
            var file = new File([data], this.templateService.getName());
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
    this.http.post(`${SERVER_URL}template/download/src`, formdata, {responseType: 'blob'}).pipe(first()).subscribe(
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
    this.rectangleService.resetRects();
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
    dialogRef.afterClosed().pipe(first()).subscribe(async result => {
      if (result === true) {
        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('template_id', template["template_id"]);
        this.http.post<any>(`${SERVER_URL}template/delete`, formdata).pipe(first()).subscribe(
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

import { HttpClient } from '@angular/common/http';
import { AfterViewInit, Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { TemplateService } from 'src/app/services/template.service';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { SelectionService } from 'src/app/services/drawing/selection.service';
import { EraserService } from 'src/app/services/drawing/eraser.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';

@Component({
  selector: 'app-template-editor',
  templateUrl: './template-editor.component.html',
  styleUrls: ['./template-editor.component.css']
})
export class TemplateEditorComponent implements OnInit, AfterViewInit {

  templateName: string = 'Template';
  toolType: string = 'rectangle';
  rectangleType: string = 'identification';

  identificationActive : boolean = true;
  questionsActive : boolean = false;

  constructor(
    public templateService : TemplateService,
    private http: HttpClient,
    private router: Router,
    private userService: UserService,
    private rectangleService : RectangleService,
    private selectionService : SelectionService,
    private notifyService : NotificationService,
    private eraserService : EraserService) {
     }

  ngOnInit(): void {
    if (this.templateService.checkEditing()){
      this.templateName = this.templateService.getTemplateName();
      this.rectangleService.initExistingRects();
    }
    this.rectangleService.init();
  }

  async onFileSelected(event: any) {
    const file = event.target.files[0];
    this.templateService.setFile(file);
    await this.templateService.createNewTemplate(file);
  }

  ngAfterViewInit(): void {
    (<HTMLElement>document.querySelector('#viewerContainer')).style.overflowY = "hidden";
  }

  onToolChange(value){
    if(value === 'rectangle'){
      this.rectangleService.init();
      this.selectionService.deleteControlPoints();
    } else if(value === 'selection'){
      this.selectionService.init();
    } else if(value === 'delete'){
      this.eraserService.init();
      this.selectionService.deleteControlPoints();
    }
  }

  setIdentificationRect(){
    this.identificationActive = true;
    this.questionsActive = false;
  }

  setQuestionsRect(){
    this.identificationActive = false;
    this.questionsActive = true;
  }

  mouseDown(event: MouseEvent): void  {
    if (this.toolType === 'rectangle'){
      this.rectangleService.mouseDown(event, this.identificationActive);
    } else if(this.toolType === 'selection'){
      this.selectionService.mouseDown(event);
    } else if(this.toolType === 'delete'){
      this.eraserService.mouseDown(event);
    }
  }

  mouseMove(event: MouseEvent): void  {
    if (this.toolType === 'rectangle'){
      this.rectangleService.mouseMove(event, this.identificationActive);
    } else if(this.toolType === 'selection'){
      this.selectionService.mouseMove(event);
    }
  }

  mouseUp(event: MouseEvent): void {
    if (this.toolType === 'rectangle'){
      this.rectangleService.mouseUp(event, this.identificationActive);
    } else if(this.toolType === 'selection'){
      this.selectionService.mouseUp(event);
    }
  }

  mouseLeave(event: MouseEvent): void {
    if (this.toolType === 'rectangle'){
      this.rectangleService.mouseLeave(event, this.identificationActive);
    } else if(this.toolType === 'selection'){
      this.selectionService.mouseLeave(event);
    }
  }

  showRectanglesNotificationError(){
    this.notifyService.showError("Assurez-vous de définir le rectangle de notes.", "ERREUR");
  }

  showNameNotificationError(){
    this.notifyService.showError("Assurez-vous de remplir le champ du nom de template!", "ERREUR");
  }

  confirm() {
    if (this.templateName.trim() === '') {
        this.showNameNotificationError();
    } else {
        const formdata: FormData = new FormData();
        formdata.append('user_id', this.userService.currentUsername);
        formdata.append('token', this.userService.token);
        formdata.append('template_name', this.templateName);
        formdata.append('matricule_box', JSON.stringify(this.rectangleService.getIdentificationRectCoords()));
        
        const questionsRectCoords = this.rectangleService.getQuestionsRectCoords();
        if (questionsRectCoords && questionsRectCoords.x1 != null) {
            formdata.append('grade_box', JSON.stringify(questionsRectCoords));
        }
        
        if (!this.templateService.checkEditing()) {
            formdata.append('template_file', this.templateService.getFile());
            this.http.post<any>(`${SERVER_URL}template`, formdata).subscribe(
                (data) => {
                    this.router.navigate(['/templates']);
                }
            );
        } else {
            formdata.append('template_id', this.templateService.getTemplateId());
            this.http.post<any>(`${SERVER_URL}template/modify`, formdata).subscribe(
                (data) => {
                    this.router.navigate(['/templates']);
                }
            );
        }
        this.rectangleService.resetRects();
    }
  }

  reroute() {
    this.router.navigate(['/templates']);
  }

}

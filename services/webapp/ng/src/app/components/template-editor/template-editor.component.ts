import { HttpClient } from '@angular/common/http';
import { AfterViewInit, Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { SocketService } from 'src/app/services/socket.service';
import { TemplateService } from 'src/app/services/template.service';
import { RectangleService } from 'src/app/services/drawing/rectangle.service';
import { SelectionService } from 'src/app/services/drawing/selection.service';
import { EraserService } from 'src/app/services/drawing/eraser.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { first } from 'rxjs/operators';

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
  disabled: boolean = false;

  constructor(
    public templateService : TemplateService,
    private http: HttpClient,
    private router: Router,
    private socketService: SocketService,
    private userService: UserService,
    private rectangleService : RectangleService,
    private selectionService : SelectionService,
    private notifyService : NotificationService,
    private eraserService : EraserService) {
     }

  ngOnInit(): void {
    if (!this.templateService.getTemplateUrl()) {
      this.reroute();
    } else {
      this.templateName = this.templateService.getTemplateName();
      this.rectangleService.initExistingRects();
      this.disabled = this.templateService.getLocked();
    }

    this.joinSocket();
    this.loadTemplate();
  }

  ngOnDestroy(): void {
    this.templateService.revokeTemplate();
    this.socketService.getSocket().off('template_rendered');
    this.socketService.disconnectSocket();
  }


  async loadTemplate() {
    // Apply page dimensions to the `<canvas>` element.
    let canvas = document.getElementById("cv") as HTMLCanvasElement;
    let context = canvas.getContext("2d");

    var img = new Image();
    img.onload = function(){
      canvas.height = img.height;
      canvas.width = img.width;
      context.drawImage(img, 0, 0);
    }
    img.src = this.templateService.getTemplateUrl();
  }

  joinSocket() {
    this.socketService.join(this.templateService.getTemplateId());
    this.socketService.getSocket().on('template_rendered', async (data: any) => {
      const formdata: FormData = new FormData();
      this.userService.addTokens(formdata);
      formdata.append('template_id', this.templateService.getTemplateId());
       this.http.post(`${SERVER_URL}template/download`, formdata, {responseType: 'blob'}).pipe(first()).subscribe(async data => {
          var file = new File([data], this.templateService.getTemplateName());
          this.templateService.setFile(file);
          await this.templateService.createNewTemplate(file);
          await this.loadTemplate();
          this.notifyService.showSuccess("Le template a été mis à jour.", "Rendu");
          this.disabled = this.templateService.getLocked();

      });
    });
  }

  ngAfterViewInit(): void {
    // (<HTMLElement>document.querySelector('#viewerContainer')).style.overflowY = "hidden";
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
    this.notifyService.showError("Assurez-vous de définir le rectangle de notes.", "Erreur");
  }

  showNameNotificationError(){
    this.notifyService.showError("Assurez-vous de remplir le champ du nom de template!", "Erreur");
  }

  showTemplateNotificationInfo(){
    this.notifyService.showInfo("Veuillez attendre le rendu maintenant.", "Sauvegardé");
  }

  confirm() {
    if (this.templateName.trim() === '') {
        this.showNameNotificationError();
    } else {
        const formdata: FormData = new FormData();
        this.userService.addTokens(formdata);
        formdata.append('template_name', this.templateName);
        formdata.append('matricule_box', JSON.stringify(this.rectangleService.getIdentificationRectCoords()));

        const questionsRectCoords = this.rectangleService.getQuestionsRectCoords();
        if (questionsRectCoords && questionsRectCoords.x1 != null) {
            formdata.append('grade_box', JSON.stringify(questionsRectCoords));
        }

        formdata.append('template_id', this.templateService.getTemplateId());
        this.http.post<any>(`${SERVER_URL}template/modify`, formdata).pipe(first()).subscribe(
            (data) => {
              this.disabled = true;
              this.showTemplateNotificationInfo();
                // this.router.navigate(['/templates']);

            }
        );
        this.rectangleService.resetRects();
    }
  }

  reroute() {
    this.router.navigate(['/templates']);
  }

}

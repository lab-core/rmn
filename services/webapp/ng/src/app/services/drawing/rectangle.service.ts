import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class RectangleService {
  previous_mousex = 0;
  previous_mousey = 0;
  current_mousex = 0;
  current_mousey = 0;

  svgContainer : SVGGraphicsElement;
  svgRect : SVGGraphicsElement;

  isMouseDown = false;

  identificationRectCoords = {x1:null, x2:null, y1:null, y2:null};
  questionsRectCoords = {x1:null, x2:null, y1:null, y2:null}

  constructor() { }

  init(){
    this.svgContainer = document.querySelector('#svg');
    this.svgContainer.setAttribute( 'cursor', 'crosshair');

    const indentificationRect = document.querySelector('#identification');
    if(indentificationRect !== null){
      indentificationRect.setAttribute( 'cursor', 'default');
    }

    const questionsRect = document.querySelector('#questions');
    if(questionsRect !== null){
      questionsRect.setAttribute( 'cursor', 'default');
    }
  }

  resetRects(): void{ 
    this.questionsRectCoords = {x1:null, x2:null, y1:null, y2:null};
    this.identificationRectCoords = {x1:null, x2:null, y1:null, y2:null};
  }


  setIdentificationRectCoords(rectCoords): void  {
    this.identificationRectCoords = rectCoords; 
    console.log("identificationCoords", this.identificationRectCoords);
  }

  setquestionsRectCoords(rectCoords): void  {
    this.questionsRectCoords = rectCoords; 
  }

  getIdentificationRectCoords()  {
    return this.identificationRectCoords;
  }

  getQuestionsRectCoords()  {
    return this.questionsRectCoords;
  }


  mouseDown(event: MouseEvent, identification : boolean): void  {
    this.isMouseDown = true;
    // the existing zone is removed when the drag actually starts (mouseMove):
    // removing it here made a click without drag persist an empty 0x0 box

    this.svgContainer = document.querySelector('#svg');
    const svgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    this.svgRect = svgRect as SVGGraphicsElement;
    this.previous_mousex = event.offsetX;
    this.previous_mousey = event.offsetY;
  }

  mouseMove(event: MouseEvent, identification : boolean): void  {
    if(this.isMouseDown === true){
      if (!this.svgRect.isConnected) {
        // the drag starts: the previous zone of this kind goes
        document.getElementById(identification ? "identification" : "questions")?.remove();
      }
      this.current_mousex = event.offsetX;
      this.current_mousey = event.offsetY;
      const width = Math.abs(this.current_mousex - this.previous_mousex);
      const height = Math.abs(this.current_mousey - this.previous_mousey);
      this.svgRect.setAttribute('x', this.previous_mousex.toString());
      this.svgRect.setAttribute( 'y', this.previous_mousey.toString());
      this.svgRect.setAttribute( 'width', width.toString());
      this.svgRect.setAttribute( 'height', height.toString());
      this.svgRect.setAttribute( 'fill-opacity', "0.01");

      if (identification === true){
        this.svgRect.setAttribute( 'stroke', "#006eff");
        this.svgRect.setAttribute( 'id', "identification");
      }else{
        this.svgRect.setAttribute( 'stroke', "#1eff00");
        this.svgRect.setAttribute( 'id', "questions");
      }

      this.svgRect.setAttribute( 'stroke-width', '3');

      this.svgContainer.appendChild(this.svgRect);
    }
  } 

  mouseUp(event: MouseEvent, identification : boolean): void {
    this.isMouseDown = false;
    if (!this.drewSomething()) {
      return;  // a click without drag: the existing zone stays
    }

    const svgContainerWidth = this.svgContainer.clientWidth;
    const svgContainerHeight = this.svgContainer.clientHeight;

    const rectX1 = Number(this.svgRect.getAttribute('x'));
    const rectY1 = Number(this.svgRect.getAttribute('y'));
    const rectX2 = Number(this.svgRect.getAttribute('width')) + rectX1;
    const rectY2 = Number(this.svgRect.getAttribute('height')) + rectY1;

    const rectCoord = {x1:(rectX1/svgContainerWidth)*100, x2:(rectX2/svgContainerWidth)*100, y1:(rectY1/svgContainerHeight)*100, y2:(rectY2/svgContainerHeight)*100};

    if (identification === true){
      this.setIdentificationRectCoords(rectCoord);
    }else{
      this.setquestionsRectCoords(rectCoord);
    }
  }

  /** Whether the current drag produced a visible box. */
  private drewSomething(): boolean {
    if (!this.svgRect || !this.svgRect.isConnected) {
      return false;
    }
    const drawn = Number(this.svgRect.getAttribute('width')) > 0 && Number(this.svgRect.getAttribute('height')) > 0;
    if (!drawn) {
      this.svgRect.remove();
    }
    return drawn;
  }

  mouseLeave(event: MouseEvent, identification : boolean): void {
    if(this.isMouseDown === true && this.drewSomething()){
      const svgContainerWidth = this.svgContainer.clientWidth;
      const svgContainerHeight = this.svgContainer.clientHeight;

      const rectX1 = Number(this.svgRect.getAttribute('x'));
      const rectY1 = Number(this.svgRect.getAttribute('y'));
      const rectX2 = Number(this.svgRect.getAttribute('width')) + rectX1;
      const rectY2 = Number(this.svgRect.getAttribute('height')) + rectY1;

      const rectCoord = {x1:(rectX1/svgContainerWidth)*100, x2:(rectX2/svgContainerWidth)*100, y1:(rectY1/svgContainerHeight)*100, y2:(rectY2/svgContainerHeight)*100};

      if (identification === true){
        this.setIdentificationRectCoords(rectCoord);
      }else{
        this.setquestionsRectCoords(rectCoord);
      }
    }
    this.isMouseDown = false;
  }

  initExistingRects(): void  {
    const svgContainer = document.querySelector('#svg');

    const svgContainerWidth = svgContainer.clientWidth;
    const svgContainerHeight = svgContainer.clientHeight;

    const identification = this.getIdentificationRectCoords();
    const identificationCoords = {x1:null, x2:null, y1:null, y2:null};
    if(identification != null) {
      identificationCoords.x1 = identification.x1/100*svgContainerWidth;
      identificationCoords.x2 = identification.x2/100*svgContainerWidth;
      identificationCoords.y1 = identification.y1/100*svgContainerHeight;
      identificationCoords.y2 = identification.y2/100*svgContainerHeight;
    }
    

    const questions = this.getQuestionsRectCoords();
    const questionsCoords = {x1:null, x2:null, y1:null, y2:null};
    if (questions != null) {
      questionsCoords.x1 = questions.x1 / 100 * svgContainerWidth;
      questionsCoords.x2 = questions.x2 / 100 * svgContainerWidth;
      questionsCoords.y1 = questions.y1 / 100 * svgContainerHeight;
      questionsCoords.y2 = questions.y2 / 100 * svgContainerHeight;
    }

    //identification
    const identificationRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect') as SVGGraphicsElement;
    if(identification != null) {
      identificationRect.setAttribute('x', identificationCoords.x1.toString());
      identificationRect.setAttribute( 'y', identificationCoords.y1.toString());
      identificationRect.setAttribute( 'width', (identificationCoords.x2 - identificationCoords.x1).toString());
      identificationRect.setAttribute( 'height', (identificationCoords.y2 - identificationCoords.y1).toString());
    }
    identificationRect.setAttribute( 'fill-opacity', "0.01");
    identificationRect.setAttribute( 'stroke', "#006eff");
    identificationRect.setAttribute( 'id', "identification");
    identificationRect.setAttribute( 'stroke-width', '3');

    //questions
    const questionsRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect') as SVGGraphicsElement;
    if (questions != null) {
      questionsRect.setAttribute('x', questionsCoords.x1.toString());
      questionsRect.setAttribute( 'y', questionsCoords.y1.toString());
      questionsRect.setAttribute( 'width', (questionsCoords.x2 - questionsCoords.x1).toString());
      questionsRect.setAttribute( 'height', (questionsCoords.y2 - questionsCoords.y1).toString());
    }
    questionsRect.setAttribute( 'fill-opacity', "0.01");
    questionsRect.setAttribute( 'stroke', "#1eff00");
    questionsRect.setAttribute( 'id', "questions");
    questionsRect.setAttribute( 'stroke-width', '3');

    svgContainer.appendChild(identificationRect);
    svgContainer.appendChild(questionsRect);
  }
}

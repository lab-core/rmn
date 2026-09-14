import { Injectable } from '@angular/core';
import { RectangleService } from './rectangle.service';

@Injectable({
  providedIn: 'root'
})
export class SelectionService {
  svgContainer : SVGGraphicsElement;
  selectedRect : SVGGraphicsElement;

  selectedCircle : SVGGraphicsElement;

  rectOffsetX : number;
  rectOffsetY : number;

  constructor(private rectangleService : RectangleService) { }

  init(){
    this.svgContainer = document.querySelector('#svg');
    this.svgContainer.setAttribute( 'cursor', 'default');

    this.selectedRect = null;
    this.selectedCircle = null;

    const indentificationRect = document.querySelector('#identification');
    if(indentificationRect !== null){
      indentificationRect.setAttribute( 'cursor', 'grab');

      this.createControlPoints(indentificationRect, 'identification');
    }

    const questionsRect = document.querySelector('#questions');
    if(questionsRect !== null){
      questionsRect.setAttribute( 'cursor', 'grab');

      this.createControlPoints(questionsRect, 'questions');
    }
  }

  
  mouseDown(event: MouseEvent): void  {
    const selectedElement = event.target as SVGGraphicsElement;
    if (selectedElement.tagName === 'rect'){
      this.selectedRect = selectedElement;
      this.selectedRect.setAttribute( 'cursor', 'grabbing');

      const rectX = Number(this.selectedRect.getAttribute('x'));
      const rectY = Number(this.selectedRect.getAttribute('y'));

      this.rectOffsetX = event.offsetX - rectX;
      this.rectOffsetY = event.offsetY - rectY;
    }else if (selectedElement.tagName === 'circle'){
      this.selectedCircle = selectedElement;
      const assignedRect = '#' + this.selectedCircle.getAttribute('id').split('-')[0];
      this.selectedRect = document.querySelector(assignedRect);
    }
  }

  mouseMove(event: MouseEvent): void  {
    if (this.selectedRect && this.selectedCircle == null) {
      event.preventDefault();
      this.selectedRect.setAttributeNS(null, "x", (event.offsetX - this.rectOffsetX).toString());
      this.selectedRect.setAttributeNS(null, "y", (event.offsetY - this.rectOffsetY).toString());
      this.moveControlPoints(this.selectedRect,(event.offsetX - this.rectOffsetX),(event.offsetY - this.rectOffsetY), false, false);
    }else if(this.selectedCircle && this.selectedRect){
      this.scaleControlPoints(event);
    }
  } 

  mouseUp(event: MouseEvent): void {
    if (!this.selectedRect) {
      return;  // a click on the empty svg selects nothing
    }
    this.selectedRect.setAttribute( 'cursor', 'grab');

    this.checkForOutOfBounds();

    this.updatedRectCoords();
    this.selectedRect = null;
    this.selectedCircle = null;
  }

  mouseLeave(event: MouseEvent): void {
    if(this.selectedRect !== null){
      this.selectedRect.setAttribute( 'cursor', 'grab');
      this.checkForOutOfBounds();
      this.updatedRectCoords();
    }
    this.selectedRect = null;
    this.selectedCircle = null;
  }



  createControlPoints(rectangle : Element, type : string){
    const controlPointsCoords = {};

    //circle placed at half the rect width on top
    let circleX = Number(rectangle.getAttribute('x')) + (Number(rectangle.getAttribute('width'))/2);
    let circleY = Number(rectangle.getAttribute('y'));
    let id = type + '-' + 'circleX1';
    controlPointsCoords[id] = [circleX, circleY];

    //circle placed at half the rect width on bottom
    circleX = Number(rectangle.getAttribute('x')) + (Number(rectangle.getAttribute('width'))/2);
    circleY = Number(rectangle.getAttribute('y')) + Number(rectangle.getAttribute('height'));
    id = type + '-' + 'circleX2';
    controlPointsCoords[id] = [circleX, circleY];

    //circle placed at half the rect height on left
    circleX = Number(rectangle.getAttribute('x'));
    circleY = Number(rectangle.getAttribute('y')) + (Number(rectangle.getAttribute('height'))/2);
    id = type + '-' + 'circleY1';
    controlPointsCoords[id] = [circleX, circleY];

    //circle placed at half the rect height on right
    circleX = Number(rectangle.getAttribute('x')) + Number(rectangle.getAttribute('width'));
    circleY = Number(rectangle.getAttribute('y')) + (Number(rectangle.getAttribute('height'))/2);
    id = type + '-' + 'circleY2';
    controlPointsCoords[id] = [circleX, circleY];

    Object.keys(controlPointsCoords).forEach(key=>{
      const svgCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      svgCircle.setAttribute('cx', controlPointsCoords[key][0].toString());
      svgCircle.setAttribute( 'cy', controlPointsCoords[key][1].toString());
      svgCircle.setAttribute( 'r', "7");
      svgCircle.setAttribute( 'stroke', "#000000");
      svgCircle.setAttribute( 'stroke-width', '3');
      svgCircle.setAttribute( 'fill', "#ffffff");
      if(key.includes('X')){
        svgCircle.setAttribute( 'cursor', 'ns-resize');
      }else{
        svgCircle.setAttribute( 'cursor', 'ew-resize');
      }

      svgCircle.setAttribute( 'id', key);

      this.svgContainer.appendChild(svgCircle);
    })

  }


  moveControlPoints(rectangle : SVGGraphicsElement, coordX : number, coordY : number, scalingX2 : boolean, scalingY2 : boolean){
    const controlPointsCoords = {};
    const type = rectangle.getAttribute('id')

    //circle placed at half the rect width on top
    let circleX = coordX + (Number(rectangle.getAttribute('width'))/2);
    let circleY = coordY;
    let id = type + '-' + 'circleX1';
    controlPointsCoords[id] = [circleX, circleY];

    //circle placed at half the rect width on bottom
    if(!scalingX2){
      circleX = coordX + (Number(rectangle.getAttribute('width'))/2);
      circleY = coordY + Number(rectangle.getAttribute('height'));
      id = type + '-' + 'circleX2';
      controlPointsCoords[id] = [circleX, circleY];
    }

    //circle placed at half the rect height on left
    circleX = coordX;
    circleY = coordY + (Number(rectangle.getAttribute('height'))/2);
    id = type + '-' + 'circleY1';
    controlPointsCoords[id] = [circleX, circleY];

    //circle placed at half the rect height on right
    if(!scalingY2){
      circleX = coordX + Number(rectangle.getAttribute('width'));
      circleY = coordY + (Number(rectangle.getAttribute('height'))/2);
      id = type + '-' + 'circleY2';
      controlPointsCoords[id] = [circleX, circleY];
    }

    Object.keys(controlPointsCoords).forEach(key=>{
      const queryId = '#' + key
      const svgCircle = document.querySelector(queryId);
      svgCircle.setAttribute('cx', controlPointsCoords[key][0].toString());
      svgCircle.setAttribute( 'cy', controlPointsCoords[key][1].toString());
    })

  }


  scaleControlPoints(event: MouseEvent){
    const rectX1 = Number(this.selectedRect.getAttribute('x'));
    const rectY1 = Number(this.selectedRect.getAttribute('y'));

    if (this.selectedCircle.getAttribute('id').includes("circleX1")){
      const newHeight = Number(this.selectedRect.getAttribute('height')) - (event.offsetY - rectY1);
      if(newHeight >= 18 ){
        this.selectedRect.setAttribute( 'y', event.offsetY.toString());
        this.selectedRect.setAttribute( 'height', newHeight.toString());
      }
      this.moveControlPoints(this.selectedRect,rectX1, rectY1, true, false);
    }else if (this.selectedCircle.getAttribute('id').includes("circleX2")){
      const newHeight = event.offsetY - rectY1;
      if(newHeight < 18 ){
        this.selectedRect.setAttribute( 'height', '18');
      }else{
        this.selectedRect.setAttribute( 'height', newHeight.toString());
      }
      this.moveControlPoints(this.selectedRect,rectX1, rectY1, false, false);
    }else if (this.selectedCircle.getAttribute('id').includes("circleY1")){
      const newWidth = Number(this.selectedRect.getAttribute('width')) - (event.offsetX - rectX1);
      if(newWidth >= 18 ){
        this.selectedRect.setAttribute( 'x', event.offsetX.toString());
        this.selectedRect.setAttribute( 'width', newWidth.toString());
      }
      this.moveControlPoints(this.selectedRect,rectX1, rectY1, false, true);
    }else if (this.selectedCircle.getAttribute('id').includes("circleY2")){
      const newWidth = event.offsetX - rectX1;
      if(newWidth < 18 ){
        this.selectedRect.setAttribute( 'width', '18');
      }else{
        this.selectedRect.setAttribute( 'width', newWidth.toString());
      }
      this.moveControlPoints(this.selectedRect,rectX1, rectY1, false, false);
    }

    this.updatedRectCoords();
  }


  deleteControlPoints(){
    if(document.getElementById("identification-circleX1") !== null){
      document.getElementById("identification-circleX1").remove();
      document.getElementById("identification-circleX2").remove();
      document.getElementById("identification-circleY1").remove();
      document.getElementById("identification-circleY2").remove();
    }

    if(document.getElementById("questions-circleX1") !== null){
      document.getElementById("questions-circleX1").remove();
      document.getElementById("questions-circleX2").remove();
      document.getElementById("questions-circleY1").remove();
      document.getElementById("questions-circleY2").remove();
    }
  }

  updatedRectCoords(){
    const svgContainerWidth = this.svgContainer.clientWidth;
    const svgContainerHeight = this.svgContainer.clientHeight;

    const rectX1 = Number(this.selectedRect.getAttribute('x'));
    const rectY1 = Number(this.selectedRect.getAttribute('y'));
    const rectX2 = Number(this.selectedRect.getAttribute('width')) + rectX1;
    const rectY2 = Number(this.selectedRect.getAttribute('height')) + rectY1;

    const rectCoord = {x1:(rectX1/svgContainerWidth)*100, x2:(rectX2/svgContainerWidth)*100, y1:(rectY1/svgContainerHeight)*100, y2:(rectY2/svgContainerHeight)*100};

    if (this.selectedRect.getAttribute('id') === 'identification'){
      this.rectangleService.setIdentificationRectCoords(rectCoord);
    }else{
      this.rectangleService.setquestionsRectCoords(rectCoord);
    }
  }


  /** Keep the selected box inside the container: clamp each axis once (the
   *  previous version recursed until every side fitted and never returned for
   *  a box wider or taller than the container). */
  checkForOutOfBounds(){
    const svgContainerWidth = this.svgContainer.clientWidth;
    const svgContainerHeight = this.svgContainer.clientHeight;
    const width = Number(this.selectedRect.getAttribute('width'));
    const height = Number(this.selectedRect.getAttribute('height'));

    const clamp = (value: number, max: number) => Math.min(Math.max(value, 0), Math.max(max, 0));
    const x = clamp(Number(this.selectedRect.getAttribute('x')), svgContainerWidth - width);
    const y = clamp(Number(this.selectedRect.getAttribute('y')), svgContainerHeight - height);

    this.selectedRect.setAttribute('x', x.toString());
    this.selectedRect.setAttribute('y', y.toString());
    this.moveControlPoints(this.selectedRect, x, y, false, false);
  }
}


import { Injectable } from '@angular/core';
import { RectangleService } from './rectangle.service';

@Injectable({
  providedIn: 'root'
})
export class EraserService {
  svgContainer : SVGGraphicsElement;
  indentificationRect : SVGGraphicsElement;
  questionsRect : SVGGraphicsElement;


  constructor(private rectangleService : RectangleService) { }

  init(){
    this.svgContainer = document.querySelector('#svg');
    this.svgContainer.setAttribute( 'cursor', 'default');

    this.indentificationRect = document.querySelector('#identification');
    if(this.indentificationRect !== null){
      this.indentificationRect.setAttribute( 'cursor', 'pointer');
    }

    this.questionsRect = document.querySelector('#questions');
    if(this.questionsRect !== null){
      this.questionsRect.setAttribute( 'cursor', 'pointer');
    }
  }

  mouseDown(event: MouseEvent): void  {
    const svgElement = event.target as SVGGraphicsElement;
    if(svgElement === this.indentificationRect){
      svgElement.remove();
      const nullCoords = {x1:null, x2:null, y1:null, y2:null};
      this.rectangleService.setIdentificationRectCoords(nullCoords);
    }else if (svgElement === this.questionsRect){
      svgElement.remove();
      const nullCoords = {x1:null, x2:null, y1:null, y2:null};
      this.rectangleService.setquestionsRectCoords(nullCoords);
    }
  }

  mouseMove(event: MouseEvent): void  {
    //do nothing
  }

  mouseUp(event: MouseEvent): void {
    //do nothing
  }

  mouseLeave(event: MouseEvent): void {
    //do nothing
  }
}

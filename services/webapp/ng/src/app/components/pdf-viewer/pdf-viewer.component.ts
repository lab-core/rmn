import { Component, ElementRef, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges, ViewChild } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, FreeTextEditorAnnotation, InkEditorAnnotation,  PdfTextEditorComponent, PdfDrawEditorComponent, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';
import { NotificationService } from 'src/app/services/notification.service';
import { PDFSource } from 'src/app/services/documents.service';


class AnnotationsChange {
  path: any = undefined;
  annotation: InkEditorAnnotation = undefined;
  eraser: EraserChange = undefined;

  isEmpty() {
    return this.path === undefined &&
           this.annotation === undefined &&
           this.eraser === undefined;
  }
}

class EraserChange {
  used: boolean = false;
  annotationsSnapshot: InkEditorAnnotation[] = undefined;
  newAnnotations: BezierAnnotation[] = undefined;
  // number of annotation added after erasing (usefull when undo)
  nInkAnnotations: number = 0;

  constructor(annotationsSnapshot: InkEditorAnnotation[]) {
    this.annotationsSnapshot = annotationsSnapshot;
    this.newAnnotations = [];
    annotationsSnapshot.forEach(annotation => {
      this.newAnnotations.push(new BezierAnnotation(annotation));
    });
  }

  getInkAnnotations() {
    let inkAnnotations = new Array<InkEditorAnnotation>();
    this.newAnnotations.forEach(annotation => {
      if (annotation.paths.length > 0) {
        inkAnnotations.push(annotation.getInkAnnotation());
      }
    });
    // let i = 0;
    // this.newAnnotations.forEach(annotation => {
    //   if (annotation.paths.length > 0) {
    //     let inkAnnotation: InkEditorAnnotation = this.annotationsSnapshot[i];
    //     let newInkAnnotation = annotation.getInkAnnotation();
    //     inkAnnotation.paths = newInkAnnotation.paths;
    //     inkAnnotations.push(inkAnnotation);
    //   }
    //   i++;
    // });
    return inkAnnotations;
  }
}

class BezierPath {
  points: number[][] = [];
  bezier: number[][] = [];

  pushPoints(x, y) {
    this.points.push([x,y]);
  }

  pushBezier(x, y) {
    this.bezier.push([x, y]);
  }

  toObject() {
    let points = [], bezier = [];
    this.points.forEach(([x,y]) => {
      points.push(y);
      points.push(x);
    });
    this.bezier.forEach(([x,y]) => {
      bezier.push(y);
      bezier.push(x);
    });
    return {
      points: points,
      bezier: bezier
    }
  }

  generateBezierPoints() {
    const path = this.points;
    if (path.length <= 2) {
      this.bezier = [path[0], path[0], path[1], path[1]];
      return;
    }
    this.bezier = [];
    let i;
    let [x0, y0] = path[0];
    for (i = 1; i < path.length - 2; i++) {
      const [x1, y1] = path[i];
      const [x2, y2] = path[i + 1];
      const x3 = (x1 + x2) / 2;
      const y3 = (y1 + y2) / 2;
      const control1 = [x0 + 2 * (x1 - x0) / 3, y0 + 2 * (y1 - y0) / 3];
      const control2 = [x3 + 2 * (x1 - x3) / 3, y3 + 2 * (y1 - y3) / 3];
      this.bezier = [...this.bezier, [x0, y0], control1, control2];
      [x0, y0] = [x3, y3];
    }
    const [x1, y1] = path[i];
    const [x2, y2] = path[i + 1];
    const control1 = [x0 + 2 * (x1 - x0) / 3, y0 + 2 * (y1 - y0) / 3];
    const control2 = [x2 + 2 * (x1 - x2) / 3, y2 + 2 * (y1 - y2) / 3];
    this.bezier = [...this.bezier, [x0, y0], control1, control2, [x2, y2]];
  }
}

class BezierAnnotation {
  paths: BezierPath[];
  rect: number[];
  inkAnnotation: InkEditorAnnotation;

  constructor(inkAnnotation: InkEditorAnnotation) {
    this.inkAnnotation = structuredClone(inkAnnotation);
    this.rect = inkAnnotation.rect;
    this.paths = [];
    inkAnnotation.paths.forEach(path => {
      let newPath = new BezierPath();
      for (let i = 0; i < path.points.length; i+=2) {
        let y = path.points[i], x = path.points[i+1];
        newPath.pushPoints(x, y);
      }
      this.paths.push(newPath);
    });
  }

  getInkAnnotation() {
    this.inkAnnotation.rect = this.rect;
    this.inkAnnotation.paths = [];
    this.paths.forEach(path => {
      path.generateBezierPoints();
      this.inkAnnotation.paths.push(path.toObject());
    });
    return this.inkAnnotation;
  }
}

@Component({
  selector: 'app-pdf-viewer',
  templateUrl: './pdf-viewer.component.html',
  styleUrls: ['./pdf-viewer.component.css']
})
export class PDFViewerComponent implements OnInit, OnChanges {

  @Input({required: true}) pdfUrl: string;
  @Input() hideToolbar: boolean = false;

  pdfAnnotations: EditorAnnotation[] = [];
  pdfViewerInitialized: boolean = false;
  pdfModified: boolean = false;
  pdfRendered: boolean = false;

  annotationsHistory: AnnotationsChange[] = [];
  nInkAnnotations: number;
  eraserHistory: EraserChange[] = [];

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  @ViewChild(PdfTextEditorComponent)
  pdfTextEditor: PdfTextEditorComponent;

  @ViewChild(PdfDrawEditorComponent)
  pdfDrawEditor: PdfDrawEditorComponent;

  private isDrawing = false;
  private isErasing = false;
  private canvases: Map<number, HTMLCanvasElement[]>;

  private scaleFactor: number;
  private pageDefaultWidth = 612;
  private timeout: number = 50;
  radius: number = 20;

  constructor(private notificationService: NotificationService,
    private ngxService: NgxExtendedPdfViewerService) {
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
  }

  async ngOnInit(): Promise<void> {}

  async ngOnChanges(changes: SimpleChanges) {
    this.pdfModified = false;
    this.pdfRendered = false;
    this.isErasing = false;
    this.isDrawing = false;
  }

  public isWriting() {
    return this.pdfTextEditor.isSelected;
  }

  getLastEraserChange() {
    if (this.eraserHistory.length == 0) {
      return undefined;
    }
    return this.eraserHistory[this.eraserHistory.length - 1];
  }

  public async renderAnnotations(annotations: EditorAnnotation[]) {
    if (annotations) {
      this.pdfAnnotations = [ ...this.pdfAnnotations, ...annotations];
      // if pdf already rendered, call loadAnnotations(). Otherwise, it will be called naturlaly
      setTimeout(() => {
        if (this.pdfRendered) {
          setTimeout(() => { this.loadAnnotations(); }, this.timeout);
        }
      });
    }
  }

  public async getRenderedPdfFile(filename: string, onlyIfModified: boolean=false) {
    // check if pdf has been modified
    if (onlyIfModified && !this.pdfModified && this.annotationsHistory.length == 0) {
      return undefined;
    } else {
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      return new File([editedPdfData], filename, { type: editedPdfData.type });
    }
  }

  public getAnnotations() {
    return this.ngxService.getSerializedAnnotations();
  }

  async onPdfLoaded(e) {}

  async onPageRendered(e) {
    if (!this.pdfRendered) {
      this.pdfRendered = true;
      setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      setTimeout(() => { this.loadAnnotations() }, this.timeout);
    }
  }

  async onAnnotationEdited(e) {
    const annotations: EditorAnnotation[] = this.getInkAnnotations();
    if (!this.isWriting()) {
      if (annotations.length != this.nInkAnnotations) {
        this.annotationsHistory = [];  // flush history as at least one ink annotation has been added
        this.cleanInkEditors();
      }
    }
    this.pdfModified = true;
  }

  initializePdfViewer(): void {
    if (!this.pdfViewerInitialized) {
      try {
        this.ngxService.editorInkColor = '#FF0000';
        this.ngxService.editorInkThickness = 2;
        this.ngxService.editorFontColor = '#FF0000';
        this.ngxService.editorFontSize = 14;
        this.pdfViewerInitialized = true;
      } catch (e) {
        setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      }
    }
  }

  loadAnnotations() {
    setTimeout(() => {
      this.pdfAnnotations.forEach(a => {
        this.ngxService.addEditorAnnotation(a);
      });
      this.pdfAnnotations = [];
      this.onAnnotationsLoaded.emit(true);
    });
  }

  undoChange() {
    const inkAnnotations: InkEditorAnnotation[] = this.getInkAnnotations();
    const eraserChange: EraserChange = this.getLastEraserChange();
    this.nInkAnnotations = inkAnnotations.length;
    const change = new AnnotationsChange();
    // if any eraser to remove
    if (eraserChange !== undefined && eraserChange.nInkAnnotations === this.nInkAnnotations) {
      this.eraserHistory.pop();
      this.replaceAllInkAnnotations(eraserChange.annotationsSnapshot);
      change.eraser = eraserChange;
      this.annotationsHistory.push(change);
    }
    // if any ink annotations to remove
    else if (inkAnnotations.length > 0) {
      // get last annotation
      let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1];
      // remove last element
      if (lastInkAnnotation.paths.length > 1) {
        change.path = lastInkAnnotation.paths.pop();  // remove last element
      } else {
        // remove last annotation
        change.annotation = inkAnnotations.pop();
      }
      this.annotationsHistory.push(change);
      this.replaceAllInkAnnotations(inkAnnotations);
    } else {
      this.notificationService.showInfo("Aucune annotation à enlever. Veuillez utiliser une version précédente si nécessaire.", "Info");
    }
  }

  redoChange() {
    if (this.annotationsHistory.length > 0) {
      const change: AnnotationsChange = this.annotationsHistory.pop();
      if (change.path) {
        const inkAnnotations: InkEditorAnnotation[] = this.getInkAnnotations();
        let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1];
        lastInkAnnotation.paths.push(change.path);
        this.replaceAllInkAnnotations(inkAnnotations);
      } else if (change.annotation) {
        this.ngxService.addEditorAnnotation(change.annotation);
        this.nInkAnnotations += 1;
      } else {
        let eraserChange: EraserChange = change.eraser;
        let inkAnnotations = eraserChange.getInkAnnotations();
        this.replaceAllInkAnnotations(inkAnnotations);
        this.eraserHistory.push(eraserChange);
      }
    } else {
      this.notificationService.showInfo("Aucune annotation à rajouter.", "Info");
    }
  }

  getInkAnnotations(): InkEditorAnnotation[] {
    const annotations: EditorAnnotation[] = this.ngxService.getSerializedAnnotations() || [];
    // search for all InkEditorAnnotation (annotationType = 15)
    const inkAnnotations: InkEditorAnnotation[] = [];
    annotations.filter(a => a.annotationType == 15).forEach(annotation => {
      inkAnnotations.push(annotation as InkEditorAnnotation);
    });
    return inkAnnotations;
  }

  replaceAllInkAnnotations(inkAnnotations: InkEditorAnnotation[]) {
    this.removeAllInkAnnotations();
    // re add all of them minus the last element
    inkAnnotations.forEach(a => {
      this.ngxService.addEditorAnnotation(a);
    });
  }

  removeAllInkAnnotations() {
    // remove all InkEditorAnnotation (annotationType = 15)
    const filter = (serial: any) => serial.annotationType === 15;
    this.ngxService.removeEditorAnnotations(filter);
  }

  private cleanInkEditors() {
    let editorColl = document.getElementsByClassName('inkEditor');
    // add new rendered canvas
    for (let i = 0; i < editorColl.length; i++) {
      const element = editorColl[i];
      element['__zone_symbol__pointerdownfalse'] = [];  // remove drag
      element['style']['pointerEvents'] = 'none';
      element['classList'].remove('selectedEditor');
    }

    // disable ink annotation pointers event
    let annotationColl = document.getElementsByClassName('inkAnnotation');
    for (let i = 0; i < annotationColl.length; i++) {
      annotationColl[i]['style']['pointerEvents'] = 'none';
    }
  }

  stopEraser() {
    this.isErasing = false;
    this.isDrawing = false;
  }

  erase() {
    this.isErasing = !this.isErasing;
    this.isDrawing = false;
    if (this.isErasing) {
      this.addCanvasListeners();
    } else {
      this.disableCanvasInkEditor();
    }
  }

  private addCanvasListeners() {
    // register event for each page canvas
    this.canvases = new Map<number, HTMLCanvasElement[]>();
    let wrapperColl = document.getElementsByClassName('canvasWrapper');
    for (let i = 0; i < wrapperColl.length; i++) {
      const canvas: HTMLCanvasElement = wrapperColl[i]['childNodes'][0] as HTMLCanvasElement;
      this.canvases.set(i, []);
      canvas.addEventListener('mousedown', (event) => this.onMouseDown(event));
      canvas.addEventListener('mouseup', () => this.onMouseUp());
      canvas.addEventListener('mousemove', (event) => this.onMouseMove(i, event));
    }

    // store ink editor canvas associated with each page
    this.cleanInkEditors();
    let inkEditorColl = document.getElementsByClassName('inkEditor');
    // add new rendered canvas
    for (let i = 0; i < inkEditorColl.length; i++) {
      const element = inkEditorColl[i];
      const canvas: HTMLCanvasElement = element['childNodes'][1] as HTMLCanvasElement;
      let grandParent = element['parentNode']['parentNode'];
      let label = grandParent['ariaLabel'];
      let page = parseInt(label.match(/\d+/)[0]) - 1;
      this.canvases.get(page).push(canvas);
    }
  }

  private disableCanvasInkEditor() {
    let annotationColl = document.getElementsByClassName('inkAnnotation');
    for (let i = 0; i < annotationColl.length; i++) {
      delete annotationColl[i]['style']['pointerEvents'];
    }
  }

  private onMouseDown(e: Event): void {
    this.isDrawing = true;
    // store a snapshot of the annotations
    const inkAnnotations: InkEditorAnnotation[] = this.getInkAnnotations();
    const eraserChange = new EraserChange(inkAnnotations);
    this.eraserHistory.push(eraserChange);
  }

  private onMouseUp(): void {
    this.isDrawing = false;
    // remove the old annotations and add the new annotations if any
    const eraserChange = this.getLastEraserChange();
    if (eraserChange.used) {
      this.pdfModified = true;
      this.annotationsHistory = [];  // flush history as erasing
      let inkAnnotations = eraserChange.getInkAnnotations();
      this.replaceAllInkAnnotations(inkAnnotations);
      eraserChange.nInkAnnotations = inkAnnotations.length;
    } else {
      // as it has not been used -> remove it
      this.eraserHistory.pop();
    }
  }

  private onMouseMove(i: number, e: MouseEvent): void {
    // console.log(i, this.isErasing, this.isDrawing);
    if (!this.isDrawing || !this.isErasing) return;
    // erase drawing
    this.canvases.get(i).forEach(canvas => {
      // bounding box in browser
      const rect = canvas.getBoundingClientRect();
      // use position in browser
      if (rect.left <= e.clientX && e.clientX <= rect.right &&
          rect.top <= e.clientY && e.clientY <= rect.bottom) {
        // the mouse move on this canvas
        this.eraseDraw(canvas, e.clientX - rect.left, e.clientY - rect.top);
      }
    });
    // erase annotations
    const canvas: HTMLCanvasElement = e.target as HTMLCanvasElement;
    const center = this.canvasToPdf(e.offsetX, e.offsetY, canvas);
    this.eraseAnnotations(i, center[0], center[1]);
  }

  private getScaleFactor() {
    let viewer = document.getElementById('viewer');
    let style = viewer['style']['cssText'];
    let matches = style.match(/\d+\.\d+/);
    this.scaleFactor = parseFloat(matches[0]);
    return this.scaleFactor;
  }

  private eraseDraw(canvas: HTMLCanvasElement, centerX: number, centerY: number) {
    const ctx = canvas.getContext("2d");
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    ctx.arc(centerX, centerY, this.radius, 0, Math.PI*2, false);
    ctx.fill();
  }

  private eraseAnnotations(i: number, centerX: number, centerY: number) {
    const eraserChange = this.getLastEraserChange();
    const annotations: BezierAnnotation[] = eraserChange.newAnnotations;
    let modified = false;
    annotations.forEach(annotation => {
      modified = this.eraseAnnotation(i, centerX, centerY, annotation) || modified;
    });
    // mark eraserChange as used
    if (modified) eraserChange.used = true;
  }

  private eraseAnnotation(i: number, centerX: number, centerY: number, annotation: BezierAnnotation) {
    if (annotation.rect[1] < centerX && centerX < annotation.rect[3] &&
        annotation.rect[0] < centerY && centerY < annotation.rect[2]) {
      let newAnnotationPaths: BezierPath[] = [];
      annotation.paths.forEach(path => {
        const newPaths: BezierPath[] = this.erasePoints(centerX, centerY, path);
        newAnnotationPaths = [...newAnnotationPaths, ...newPaths];
      });
      annotation.paths = newAnnotationPaths;
      this.setRectangle(annotation);
      return true;
    }
    return false;
  }

  private erasePoints(centerX: number, centerY: number, path: BezierPath): BezierPath[] {
    // remove parts of the points => transform it in several paths
    const newPaths: BezierPath[] = [];
    let newPath: BezierPath = new BezierPath();
    let bezierIndex = 0, radius2 = Math.pow(this.radius, 2);
    for (let [x, y] of path.points) {
      // keep this (x,y) if far enough from center
      let dist = Math.pow(x-centerX, 2) + Math.pow(y-centerY, 2);
      if (dist >= radius2) {
        newPath.pushPoints(x, y);
      } else if (newPath.points.length > 1) {
        // do not consider a path too small or empty
        newPaths.push(newPath);
        newPath = new BezierPath();
      }
    }
    // add last new path
    if (newPath.points.length > 1) {
      newPaths.push(newPath);
    }
    return newPaths;
  }

  private setRectangle(annotation: BezierAnnotation) {
    const rect = [undefined, undefined, undefined, undefined];
    annotation.paths.forEach(path => {
      for (let [x, y] of path.points) {
        if (rect[0] === undefined || y < rect[0]) rect[0] = y;
        if (rect[1] === undefined || x < rect[1]) rect[1] = x;
        if (rect[2] === undefined || y > rect[2]) rect[2] = y;
        if (rect[3] === undefined || x > rect[3]) rect[3] = x;
      };
    });
    if (rect[0] !== undefined) {
      annotation.rect = [rect[0] - 1.5, rect[1] - 1.5, rect[2] + 1.5, rect[3] + 1.5];
    }
  }

  private canvasToPdf(cX, cY, canvas) {
    // rewrite current pointer position into the points coordinates with the right scale
    this.getScaleFactor();
    // 1- flip origin. Canvas => top left, Annotations => bottom right
    let pX = canvas.width - cX, pY = canvas.height - cY;
    // 2- Change scale
    return [pX / this.scaleFactor, pY / this.scaleFactor]
  }

  private pdfToCanvas(pX, pY, canvas) {
    // rewrite current pointer position into the points coordinates with the right scale
    const scaleFactor = this.pageDefaultWidth / canvas.width;
    // 1- Change scale
    let cX = pX * this.scaleFactor, cY = pY * this.scaleFactor;
    // 2- flip origin. Canvas => top left, Annotations => bottom right
    return [canvas.width - cX, canvas.height - cY]
  }
}

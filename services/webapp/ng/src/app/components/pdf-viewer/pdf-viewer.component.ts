import { Component, ElementRef, Input, Output, EventEmitter, OnInit, OnChanges, OnDestroy, SimpleChanges, ChangeDetectionStrategy, ViewChild, HostListener } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, FreeTextEditorAnnotation, InkEditorAnnotation,  PdfTextEditorComponent, PdfDrawEditorComponent, PDFWorker, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';
import { NotificationService } from 'src/app/services/notification.service';
import { PDFSource } from 'src/app/services/documents.service';


class AnnotationsChange {
  path: any = undefined;
  annotation: InkEditorAnnotation = undefined;
  eraser: EraserChange = undefined;
  rect;

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
    return inkAnnotations;
  }
}

class BezierPath {
  points: number[][] = [];
  bezier: number[][] = [];

  pushPoint(x, y) {
    this.points.push([x,y]);
  }

  pushBezierPoint(x, y) {
    this.bezier.push([x,y]);
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
      this.bezier = [path[0], path[0], path[path.length-1], path[path.length-1]];
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

const PADDING = [2, 2, 1, 1];

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
        newPath.pushPoint(x, y);
      }
      for (let i = 0; i < path.bezier.length; i+=2) {
        let y = path.bezier[i], x = path.bezier[i+1];
        newPath.pushBezierPoint(x, y);
      }
      this.paths.push(newPath);
    });
  }

  getInkAnnotation() {
    this.inkAnnotation.rect = this.rect;
    this.inkAnnotation.paths = [];
    this.paths.forEach(path => {
      if (path === undefined) {
        console.log('path undefined')
      }
      path.generateBezierPoints();
      this.inkAnnotation.paths.push(path.toObject());
    });
    return this.inkAnnotation;
  }

  computeRectangle() {
    const rect = [undefined, undefined, undefined, undefined];
    this.paths.forEach(path => {
      for (let [x, y] of [...path.points, ...path.bezier]) {
        if (rect[0] === undefined || y < rect[0]) rect[0] = y;
        if (rect[1] === undefined || x < rect[1]) rect[1] = x;
        if (rect[2] === undefined || y > rect[2]) rect[2] = y;
        if (rect[3] === undefined || x > rect[3]) rect[3] = x;
      };
    });
    if (rect[0] !== undefined) {
      this.rect = [rect[0] - PADDING[0], rect[1] - PADDING[1], rect[2] + PADDING[2], rect[3] + PADDING[3]];
    }
  }
}

@Component({
  selector: 'app-pdf-viewer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './pdf-viewer.component.html',
  styleUrls: ['./pdf-viewer.component.css']
})
export class PDFViewerComponent implements OnInit, OnChanges, OnDestroy {

  @Input({required: true}) pdfUrl: string;
  @Input() hideToolbar: boolean = false;

  pdfAnnotations: EditorAnnotation[] = [];
  pdfViewerInitialized: boolean = false;
  pdfModified: boolean = false;
  pdfRendered: boolean = false;

  annotationsHistory: AnnotationsChange[] = [];
  nInkAnnotations: number;
  flushHistoryActivated: boolean = true;
  eraserHistory: EraserChange[] = [];

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  @ViewChild(PdfTextEditorComponent)
  pdfTextEditor: PdfTextEditorComponent;

  @ViewChild(PdfDrawEditorComponent)
  pdfDrawEditor: PdfDrawEditorComponent;

  private isDrawing = false;
  private isErasing = false;
  private canvases: Map<number, HTMLCanvasElement[]>;
  private eventListeners = [];
  private pointerType = undefined;
  private eraserPointerType = undefined;

  private timeout: number = 80;
  radius: number = 20;

  observers = [];

  constructor(private notificationService: NotificationService,
    private ngxService: NgxExtendedPdfViewerService) {
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
  }

  async ngOnInit(): Promise<void> {
    console.log("PDF viewer init");
  }

  async ngOnChanges(changes: SimpleChanges) {
    this.pdfModified = false;
    this.pdfRendered = false;
    this.isDrawing = false;
    this.removeCanvasListeners();
    this.stopObservers();
  }

  async ngOnDestroy() {
    this.removeCanvasListeners();
    this.stopObservers();
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
      if (this.pdfRendered) {
        setTimeout(() => { this.loadAnnotations(); }, this.timeout);
      }
    }
  }

  public async getRenderedPdfFile(filename: string, onlyIfModified: boolean=false): Promise<File> {
    // check if pdf has been modified
    if (onlyIfModified && !this.pdfModified && this.annotationsHistory.length == 0) {
      return undefined;
    } else {
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      return new File([editedPdfData], filename, { type: editedPdfData.type });
    }
  }

  public getAnnotations() {
    return this.ngxService?.getSerializedAnnotations();
  }

  async waitRender() {
    let first = true;
    while (first || !this.ngxService?.isRenderQueueEmpty()) {
      first = false;
      await (new Promise((resolve) => setTimeout(resolve, this.timeout)));
    }
  }

  async onPdfLoaded(e) {
    console.log("Loaded");
    this.nInkAnnotations = 0;
    this.annotationsHistory = [];
    this.eraserHistory = [];
  }

  async onPageRendered(e) {
    if (!this.pdfRendered) {
      this.pdfRendered = true;
      setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      setTimeout(() => { this.loadAnnotations() }, this.timeout);
    }
  }

  async onAnnotationEdited(e) {
    const annotations: EditorAnnotation[] = this.getInkAnnotations();
    if (this.flushHistoryActivated && !this.isWriting() && annotations.length != this.nInkAnnotations) {
      this.annotationsHistory = [];  // flush history as at least one ink annotation has been added
    }
    this.pdfModified = true;
  }

  async initializePdfViewer(): Promise<void> {
    if (!this.pdfViewerInitialized) {
      await this.waitRender();
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
    setTimeout(async () => {
      await this.waitRender();
      this.pdfAnnotations.forEach(a => this.ngxService?.addEditorAnnotation(a));
      this.pdfAnnotations = [];
      this.onAnnotationsLoaded.emit(true);
      this.cleanInkEditors();
      if (this.isErasing) {
        this.addCanvasListeners();
      }
      this.observeAnnotationEditorLayer();
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
      this.nInkAnnotations = eraserChange.annotationsSnapshot.length;
      change.eraser = eraserChange;
      this.annotationsHistory.push(change);
    }
    // if any ink annotations to remove
    else if (inkAnnotations.length > 0) {
      // get last annotation
      let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1];
      // remove last element
      if (lastInkAnnotation.paths.length > 1) {
        change.rect = lastInkAnnotation.rect;
        change.path = lastInkAnnotation.paths.pop();  // remove last element
        // recompute the bounding box
        const bezierAnnotation = new BezierAnnotation(lastInkAnnotation);
        bezierAnnotation.computeRectangle();
        lastInkAnnotation.rect = bezierAnnotation.rect;
      } else {
        // remove last annotation
        change.annotation = inkAnnotations.pop();
        this.nInkAnnotations--;
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
        lastInkAnnotation.rect = change.rect;
        this.replaceAllInkAnnotations(inkAnnotations);
      } else if (change.annotation) {
        this.ngxService?.addEditorAnnotation(change.annotation);
        this.nInkAnnotations += 1;
      } else {
        let eraserChange: EraserChange = change.eraser;
        let inkAnnotations = eraserChange.getInkAnnotations();
        this.replaceAllInkAnnotations(inkAnnotations);
        this.nInkAnnotations = eraserChange.nInkAnnotations;
        this.eraserHistory.push(eraserChange);
      }
    } else {
      this.notificationService.showInfo("Aucune annotation à rajouter.", "Info");
    }
  }

  getInkAnnotations(): InkEditorAnnotation[] {
    const annotations: EditorAnnotation[] = this.ngxService?.getSerializedAnnotations() || [];
    // search for all InkEditorAnnotation (annotationType = 15)
    const inkAnnotations: InkEditorAnnotation[] = [];
    annotations.filter(a => a.annotationType == 15).forEach(annotation => {
      inkAnnotations.push(annotation as InkEditorAnnotation);
    });
    return inkAnnotations;
  }

  replaceAllInkAnnotations(inkAnnotations: InkEditorAnnotation[]) {
    this.flushHistoryActivated = false;
    this.removeAllInkAnnotations();
    // re add all of them minus the last element
    this.flushHistoryActivated = true;
    inkAnnotations.forEach(a => this.ngxService?.addEditorAnnotation(a));
  }

  removeAllInkAnnotations() {
    // remove all InkEditorAnnotation (annotationType = 15)
    const filter = (serial: any) => serial.annotationType === 15;
    this.ngxService?.removeEditorAnnotations(filter);
  }

  private cleanInkEditors() {
    // disable ink annotation pointers event
    let editorColl = document.getElementsByClassName('inkEditor');
    // add new rendered canvas
    for (let i = 0; i < editorColl.length; i++) {
      const element = editorColl[i];
      // do not touch to the editing canvas as necessary to draw etc ...
      element['__zone_symbol__pointerdownfalse'] = [];  // remove drag
      if (element['childNodes'].length > 1) {
        element['style']['pointerEvents'] = 'none';
        element['classList'].remove('selectedEditor');
        element['classList'].remove('draggable');
        element['childNodes'][0]['classList'].add('disabled');
        element['childNodes'][2]['classList'].add('disabled');
        element['childNodes'][0]['classList'].add('hidden');
        element['childNodes'][2]['classList'].add('hidden');
      }
    }

    // disable ink annotation pointers event
    let annotationColl = document.getElementsByClassName('inkAnnotation');
    for (let i = 0; i < annotationColl.length; i++) {
      annotationColl[i]['style']['pointerEvents'] = 'none';
    }
  }

  private observeAnnotationEditorLayer() {
    // Options for the observer (which mutations to observe)
    const config = { childList: true };
    var that = this;

    // Select the node that will be observed for mutations
    const editorColl = document.getElementsByClassName("annotationEditorLayer");
    for (let i = 0; i < editorColl.length; i++) {
      // Create an observer instance linked to the callback function
      const observer = new MutationObserver((mutationList, observer) => {
        setTimeout(() => { this.cleanInkEditors() });
      });
      // Start observing the target node for configured mutations
      observer.observe(editorColl[i], config);
      this.observers.push(observer);
    }
  }

  stopObservers() {
    this.observers.forEach(observer => {
      // Later, you can stop observing
      observer.disconnect();
    });
    this.observers = [];
  }

  closeOpenEditors() {
    let toolColl = document.getElementsByClassName('toolbarButton');
    for (let i = 0; i < toolColl.length; i++) {
      let eTool = toolColl[i] as HTMLButtonElement;
      // toolColl[i]['classList'].remove('toggled');
      if (eTool['id'].includes('Editor') && eTool['classList'].contains('toggled')) {
        eTool.click();
      }
    }
  }

  openEraser() {
    this.isErasing = true;
    this.isDrawing = false;
    document.getElementById('eraserParamsToolbar')['classList'].remove('hidden');
    document.getElementById('eraserTool')['classList'].add('toggled');
    this.cleanInkEditors();
    this.addCanvasListeners();
  }

  closeEraser() {
    this.isErasing = false;
    this.isDrawing = false;
    document.getElementById('eraserParamsToolbar')['classList'].add('hidden');
    document.getElementById('eraserTool')['classList'].remove('toggled');
    this.removeCanvasListeners();
  }

  erase(event: PointerEvent) {
    if (!this.isErasing) {
      this.eraserPointerType = this.pointerType;
      this.closeOpenEditors();
      setTimeout(() => { this.openEraser() });
    } else {
      this.closeEraser();
      this.eraserPointerType = undefined;
    }
  }

  private addCanvasListeners() {
    this.removeCanvasListeners();
    // register event for each page canvas
    this.eventListeners = [];
    let wrapperColl = document.getElementsByClassName('textLayer');
    for (let i = 0; i < wrapperColl.length; i++) {
      // const canvas: HTMLCanvasElement = wrapperColl[i]['childNodes'][0] as HTMLCanvasElement;
      const canvas: HTMLElement = wrapperColl[i] as HTMLElement;

      var self = this;
      const eventListeners = {};
      eventListeners['pointerdown'] = function(event: PointerEvent) { return self.onEraserStart(event) };
      eventListeners['pointerup'] = function(event: PointerEvent) { return self.onEraserEnd(event) };
      // eventListeners['pointerleave'] = function(event: PointerEvent) { return self.onEraserEnd(event) };
      eventListeners['pointermove'] = function(event: PointerEvent) { return self.onEraserMove(i, event) };
      eventListeners['touchmove'] = function(event: TouchEvent) { return self.onTouchMove(i, event) };
      for (let k in eventListeners) {
        canvas.addEventListener(k, eventListeners[k], { passive: false });
      }
      this.eventListeners.push(eventListeners);
    }
  }

  private removeCanvasListeners() {
    let wrapperColl = document.getElementsByClassName('textLayer');
    for (let i = 0; i < this.eventListeners.length; i++) {
      // remove the listeners on the child if the canvas still exists
      if (wrapperColl[i]) {
        const canvas: HTMLElement = wrapperColl[i] as HTMLElement;
        for (let k in this.eventListeners[i]) {
          canvas.removeEventListener(k, this.eventListeners[i][k], true);
        }
      }
    }
    this.eventListeners = [];
  }

  private updateCanvas() {
    // clear canvases and one array per page
    this.canvases = new Map<number, HTMLCanvasElement[]>();
    for (let i = 0; i<this.eventListeners.length; i++) {
      this.canvases.set(i, []);
    }
    // store ink editor canvas associated with each page
    let inkEditorColl = document.getElementsByClassName('inkEditor');
    for (let i = 0; i < inkEditorColl.length; i++) {
      const element = inkEditorColl[i];
      if (element['childNodes'].length > 1) {
        const canvas: HTMLCanvasElement = element['childNodes'][1] as HTMLCanvasElement;
        let grandParent = element['parentNode']['parentNode'];
        let label = grandParent['ariaLabel'];
        let page = parseInt(label.match(/\d+/)[0]) - 1;
        this.canvases.get(page).push(canvas);
      }
    }
  }

  @HostListener('window:pointerdown', ['$event'])
  onPointerDown(event: PointerEvent) {
    this.pointerType = event.pointerType;
    return true;  // do not prevent default
  }

  samePointerType(event=undefined) {
    return (event ? event.pointerType : this.pointerType) === this.eraserPointerType;
  }

  private onEraserStart(event: PointerEvent): void {
    if (this.isDrawing || !this.samePointerType(event)) {
      return;
    }
    this.isDrawing = true;
    // fetch canvases
    this.updateCanvas();
    // store a snapshot of the annotations
    const inkAnnotations: InkEditorAnnotation[] = this.getInkAnnotations();
    const eraserChange = new EraserChange(inkAnnotations);
    this.eraserHistory.push(eraserChange);
  }

  private onEraserEnd(event: PointerEvent): void {
    if (!this.isDrawing || !this.samePointerType(event)) {
      return;
    }
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

  private onTouchMove(i: number, event: TouchEvent): void {
    if (!this.isDrawing || !this.isErasing || !this.samePointerType()) return;
    // do not apply default behavior
    event.preventDefault();
  }

  private onEraserMove(i: number, event: PointerEvent): void {
    if (!this.isDrawing || !this.isErasing || !this.samePointerType(event)) return;
    // do not apply default behavior
    event.preventDefault();
    // erase drawing
    this.canvases.get(i).forEach(canvas => {
      // bounding box in browser
      const rect = canvas.getBoundingClientRect();
      // use position in browser
      if (rect.left <= event.clientX && event.clientX <= rect.right &&
          rect.top <= event.clientY && event.clientY <= rect.bottom) {
        // the mouse move on this canvas
        this.eraseDraw(canvas, event.clientX - rect.x, event.clientY - rect.y);
      }
    });
    // erase annotations
    const canvas: HTMLCanvasElement = event.target as HTMLCanvasElement;
    const rect = canvas.getBoundingClientRect();
    const offsetX = event.clientX - rect.x, offsetY = event.clientY - rect.y;
    const center = this.canvasToPdf(offsetX, offsetY, canvas);
    this.eraseAnnotations(i, center[0], center[1]);
  }

  private getScaleFactor() {
    let viewer = document.getElementById('viewer');
    let style = viewer['style']['cssText'];
    let matches = style.match(/\d+\.\d+/);
    return parseFloat(matches[0]);
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
      let modified = false;
      annotation.paths.forEach(path => {
        const newPaths: BezierPath[] = this.erasePoints(centerX, centerY, path);
        if (newPaths === undefined) {
          newAnnotationPaths.push(path);  // keep old unmodified path
        } else {
          modified = true;
          newAnnotationPaths = [...newAnnotationPaths, ...newPaths];
        }
      });
      annotation.paths = newAnnotationPaths;
      annotation.computeRectangle();
      return modified;
    }
    return false;
  }

  private erasePoints(centerX: number, centerY: number, path: BezierPath): BezierPath[] {
    // remove parts of the points => transform it in several paths
    const newPaths: BezierPath[] = [];
    let newPath: BezierPath = new BezierPath();
    let bezierIndex = 0, radius2 = Math.pow(this.radius, 2);
    let modified = false;
    for (let [x, y] of path.points) {
      // keep this (x,y) if far enough from center
      let dist = Math.pow(x-centerX, 2) + Math.pow(y-centerY, 2);
      if (dist >= radius2) {
        newPath.pushPoint(x, y);
      } else {
        modified = true;
        if (newPath.points.length > 1) {
          // do not consider a path too small or empty
          newPaths.push(newPath);
          newPath = new BezierPath();
        }
      }
    }

    if (modified) {
      // add last new path if necessary
      if (newPath.points.length > 1) {
        newPaths.push(newPath);
      }
      return newPaths;
    } else {
      return undefined;
    }
  }

  private canvasToPdf(cX, cY, canvas) {
    // rewrite current pointer position into the points coordinates with the right scale
    const scaleFactor = this.getScaleFactor();
    // 1- flip origin. Canvas => top left, Annotations => bottom right
    const rect = canvas.getBoundingClientRect();
    let pX = rect.width - cX, pY = rect.height - cY;
    // 2- Change scale
    return [pX / scaleFactor, pY / scaleFactor]
  }

  private pdfToCanvas(pX, pY, canvas) {
    // rewrite current pointer position into the points coordinates with the right scale
    const scaleFactor = this.getScaleFactor();
    // 1- Change scale
    let cX = pX * scaleFactor, cY = pY * scaleFactor;
    // 2- flip origin. Canvas => top left, Annotations => bottom right
    return [canvas.width - cX, canvas.height - cY]
  }
}

import { Component, ElementRef, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges, ViewChild } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, FreeTextEditorAnnotation, InkEditorAnnotation,  PdfTextEditorComponent, PdfDrawEditorComponent, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';
import { NotificationService } from 'src/app/services/notification.service';
import { PDFSource } from 'src/app/services/documents.service';


class AnnotationsChange {
  path: any = undefined;
  annotation: EditorAnnotation = undefined;
  annotationsSnapshot: EditorAnnotation[] = undefined;
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

  timeout: number = 50;

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  @ViewChild(PdfTextEditorComponent)
  pdfTextEditor: PdfTextEditorComponent;

  @ViewChild(PdfDrawEditorComponent)
  pdfDrawEditor: PdfDrawEditorComponent;

  private listenersAdded = false;
  private isDrawing = false;
  private isErasing = false;

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
    this.listenersAdded = false;
  }

  public isWriting() {
    return this.pdfTextEditor.isSelected;
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
    if (!this.isWriting() && annotations.length != this.nInkAnnotations) {
      this.annotationsHistory = [];  // flush history as at least one ink annotation has been added
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
    const inkAnnotations: EditorAnnotation[] = this.getInkAnnotations();
    this.nInkAnnotations = inkAnnotations.length;
    // if any ink annotations to remove
    if (inkAnnotations.length > 0) {
      const change = new AnnotationsChange();
      // remove last element
      let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1] as InkEditorAnnotation;
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
        const inkAnnotations: EditorAnnotation[] = this.getInkAnnotations();
        let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1] as InkEditorAnnotation;
        lastInkAnnotation.paths.push(change.path);
        this.replaceAllInkAnnotations(inkAnnotations);
      } else if (change.annotation) {
        this.ngxService.addEditorAnnotation(change.annotation);
        this.nInkAnnotations += 1;
      }
    } else {
      this.notificationService.showInfo("Aucune annotation à rajouter.", "Info");
    }
  }

  getInkAnnotations(): EditorAnnotation[] {
    let annotations: EditorAnnotation[] = this.ngxService.getSerializedAnnotations() || [];
    // search for all InkEditorAnnotation (annotationType = 15)
    return annotations.filter(a => a.annotationType == 15);
  }

  replaceAllInkAnnotations(inkAnnotations: EditorAnnotation[]) {
    // remove all InkEditorAnnotation (annotationType = 15)
    const filter = (serial: any) => serial.annotationType === 15;
    this.ngxService.removeEditorAnnotations(filter);
    // re add all of them minus the last element
    inkAnnotations.forEach(a => {
      this.ngxService.addEditorAnnotation(a);
    });
  }

  erase() {
    this.addCanvasListeners();
    this.isErasing = !this.isErasing;
    
  }

  private addCanvasListeners() {
    const canvasColl = document.getElementsByClassName("canvasWrapper");
    // add new rendered canvas (there are 2 canvas per page)
    if (!this.listenersAdded) {
      for (let i = 0; i < canvasColl.length; i++) {
        const element = canvasColl[i];
        const canvas: HTMLCanvasElement = element["childNodes"][0] as HTMLCanvasElement;
        canvas.addEventListener('mousedown', (event) => this.onMouseDown(i, event));
        canvas.addEventListener('mouseup', () => this.onMouseUp(i));
        canvas.addEventListener('mousemove', (event) => this.onMouseMove(i, event));
      }
      this.listenersAdded = true;
    }
  }

    private onMouseDown(page: number, event: MouseEvent): void {
      this.isDrawing = true;

    }

    private onMouseUp(page: number): void {
      this.isDrawing = false;

    }

    private onMouseMove(page: number, event: MouseEvent): void {
      if (!this.isDrawing) return;

      if (this.isErasing) {

      }
    }
}
